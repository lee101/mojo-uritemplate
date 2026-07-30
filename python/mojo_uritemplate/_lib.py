"""ctypes bridge and Python-value wire encoding."""

from __future__ import annotations

import collections.abc
import ctypes
import os
import struct
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIB_PATH = Path(
    os.environ.get(
        "MOJO_URITEMPLATE_LIB", ROOT / "dist/libmojo-uritemplate.so"
    )
)

I = ctypes.c_int64
U32 = struct.Struct("<I")
_library: ctypes.CDLL | None = None


class BuildError(RuntimeError):
    pass


def build(force: bool = False) -> Path:
    source = ROOT / "src/uritemplate.mojo"
    if not force and LIB_PATH.exists() and (
        not source.exists() or LIB_PATH.stat().st_mtime >= source.stat().st_mtime
    ):
        return LIB_PATH
    script = ROOT / "build/build.sh"
    if not script.exists():
        raise BuildError(f"shared library not found at {LIB_PATH}")
    process = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=1800,
    )
    if process.returncode or not LIB_PATH.exists():
        raise BuildError((process.stderr or process.stdout).strip())
    return LIB_PATH


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        _library = ctypes.CDLL(str(build()))
        fn = _library.mut_expand
        fn.argtypes = [I, I, I, I, I, I, I]
        fn.restype = I
    return _library


def _key_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return str(value).encode()


def _is_pairs(value: Any) -> bool:
    return bool(value) and isinstance(value, (list, tuple)) and all(
        isinstance(item, tuple) and len(item) == 2 for item in value
    )


def encode_values(values: collections.abc.Mapping[str, Any]) -> bytearray:
    pack = U32.pack
    payload = bytearray(pack(len(values)))
    append = payload.append
    extend = payload.extend
    for key, value in values.items():
        if isinstance(key, str):
            key_data = key.encode()
        else:
            key_data = b"\xff" + _key_bytes(key)
        extend(pack(len(key_data)))
        extend(key_data)
        if value is None:
            append(0)
            continue
        if isinstance(value, (list, tuple)):
            pairs = _is_pairs(value)
            if not pairs:
                append(2)
                extend(pack(len(value)))
                for item in value:
                    append(item is None)
                    if item is not None:
                        if isinstance(item, bytes):
                            data = item.decode().encode()
                        elif isinstance(item, str):
                            data = item.encode()
                        else:
                            data = str(item).encode()
                        extend(pack(len(data)))
                        extend(data)
                continue
            items = value
        elif isinstance(value, dict):
            items = sorted(value.items())
        elif isinstance(value, (str, bytes, int, float, bool)):
            items = None
        elif isinstance(value, collections.abc.MutableMapping):
            items = sorted(value.items())
        else:
            items = None
        if items is not None:
            append(3)
            extend(pack(len(items)))
            for item_key, item_value in items:
                if isinstance(item_key, bytes):
                    item_key_data = item_key
                elif isinstance(item_key, str):
                    item_key_data = item_key.encode()
                else:
                    item_key_data = str(item_key).encode()
                extend(pack(len(item_key_data)))
                extend(item_key_data)
                append(item_value is None)
                if item_value is not None:
                    if isinstance(item_value, bytes):
                        item_data = item_value.decode().encode()
                    elif isinstance(item_value, str):
                        item_data = item_value.encode()
                    else:
                        item_data = str(item_value).encode()
                    extend(pack(len(item_data)))
                    extend(item_data)
            continue
        if isinstance(value, bytes):
            append(5 if value else 6)
        elif isinstance(value, str) and not value:
            append(7)
        else:
            append(1 if value else 4)
        if isinstance(value, bytes):
            data = value.decode().encode()
        elif isinstance(value, str):
            data = value.encode()
        else:
            data = str(value).encode()
        extend(pack(len(data)))
        extend(data)
    return payload


def expand_native(
    template: str | bytes,
    values: collections.abc.Mapping[str, Any],
    partial: bool,
) -> str:
    template_data = template.encode() if isinstance(template, str) else template
    wire_data = encode_values(values)
    source = ctypes.c_char_p(template_data)
    source_addr = ctypes.cast(source, ctypes.c_void_p).value
    wire = ctypes.c_ubyte.from_buffer(wire_data)
    wire_addr = ctypes.addressof(wire)
    capacity = max(64, len(template_data) + len(wire_data) * 3)
    while True:
        destination = ctypes.create_string_buffer(capacity)
        needed = lib().mut_expand(
            source_addr,
            len(template_data),
            wire_addr,
            len(wire_data),
            ctypes.addressof(destination),
            capacity,
            int(partial),
        )
        if needed < 0:
            raise RuntimeError(f"native URI expansion failed with status {needed}")
        if needed <= capacity:
            if capacity <= 4096:
                return destination.raw[:needed].decode()
            return ctypes.string_at(destination, needed).decode()
        capacity = needed
