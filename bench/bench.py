"""Benchmark Mojo expansion against uritemplate 4.x on identical inputs."""

from __future__ import annotations

import math
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import mojo_uritemplate as mojo  # noqa: E402
import uritemplate as upstream  # noqa: E402


def time_call(function, minimum: float = 0.15, repeat: int = 3) -> float:
    iterations = 1
    while True:
        start = time.perf_counter()
        for _ in range(iterations):
            function()
        elapsed = time.perf_counter() - start
        if elapsed >= minimum:
            break
        iterations *= max(2, math.ceil(minimum / max(elapsed, 1e-9)))
    best = math.inf
    for _ in range(repeat):
        start = time.perf_counter()
        for _ in range(iterations):
            function()
        best = min(best, (time.perf_counter() - start) / iterations)
    return best


def cpu_name() -> str:
    if sys.platform == "linux":
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown CPU"


def cases():
    short_template = "https://api.example.test{/owner}{/repo}{?page,fields*}"
    short_values = {
        "owner": "python-hyper",
        "repo": "uritemplate",
        "page": 3,
        "fields": ["name", "updated at", "language"],
    }
    yield (
        "API URL, scalar + list",
        lambda: mojo.expand(short_template, short_values),
        lambda: upstream.expand(short_template, short_values),
    )

    escaped_64k = ("alpha beta/gamma?delta=é&" * 2600)[:65_536]
    yield (
        "percent-encode 64 KiB",
        lambda: mojo.expand("{value}", value=escaped_64k),
        lambda: upstream.expand("{value}", value=escaped_64k),
    )

    escaped_1m = ("alpha beta/gamma?delta=é&" * 42_000)[:1_048_576]
    yield (
        "percent-encode 1 MiB",
        lambda: mojo.expand("{value}", value=escaped_1m),
        lambda: upstream.expand("{value}", value=escaped_1m),
    )

    segments = [f"segment {index}/value" for index in range(10_000)]
    yield (
        "explode 10k path segments",
        lambda: mojo.expand("{/segments*}", segments=segments),
        lambda: upstream.expand("{/segments*}", segments=segments),
    )

    query = {f"key{index:05d}": f"value {index}/x" for index in range(5_000)}
    yield (
        "explode 5k query pairs",
        lambda: mojo.expand("{?query*}", query=query),
        lambda: upstream.expand("{?query*}", query=query),
    )

    names = [f"v{index}" for index in range(100)]
    many_template = "/items{?" + ",".join(names) + "}"
    many_values = {name: f"value {index}" for index, name in enumerate(names)}
    ours_compiled = mojo.URITemplate(many_template)
    theirs_compiled = upstream.URITemplate(many_template)
    yield (
        "cached template, 100 scalars",
        lambda: ours_compiled.expand(many_values),
        lambda: theirs_compiled.expand(many_values),
    )


def display_time(seconds: float) -> str:
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f} µs"
    return f"{seconds * 1e3:.2f} ms"


def main() -> None:
    print(f"Machine: {cpu_name()}; {platform.system()} {platform.machine()}; Python {platform.python_version()}")
    print()
    print("| case | mojo-uritemplate | uritemplate | relative |")
    print("| --- | ---: | ---: | ---: |")
    for name, ours, theirs in cases():
        assert ours() == theirs()
        mojo_time = time_call(ours)
        upstream_time = time_call(theirs)
        ratio = upstream_time / mojo_time
        result = (
            f"{ratio:.2f}x faster"
            if ratio >= 1
            else f"{1 / ratio:.2f}x slower"
        )
        print(
            f"| {name} | {display_time(mojo_time)} | "
            f"{display_time(upstream_time)} | {result} |"
        )


if __name__ == "__main__":
    main()
