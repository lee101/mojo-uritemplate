# mojo-uritemplate

[RFC 6570](https://www.rfc-editor.org/rfc/rfc6570) URI Template expansion
implemented in Mojo and exposed to Python. It covers the public API of
Python's `uritemplate` package for the value types listed below, so covered
code needs only an import change:

```python
import mojo_uritemplate as uritemplate

url = uritemplate.expand(
    "https://api.example.com/repos{/owner}{/repo}{?fields*}",
    {
        "owner": "python-hyper",
        "repo": "uritemplate",
        "fields": ["name", "updated at"],
    },
)
assert url == (
    "https://api.example.com/repos/python-hyper/uritemplate"
    "?fields=name&fields=updated%20at"
)
```

The implementation is not a stub around Python quoting. Python converts
values into a typed byte stream; the expression parser, value lookup, prefix
handling, explode logic, UTF-8 percent encoding, joining, and rendering all
run in the compiled Mojo library.

## Coverage

The covered API is:

- `expand(uri, var_dict=None, **kwargs)`
- `partial(uri, var_dict=None, **kwargs)`
- `variables(uri)`
- `URITemplate`, including `expand`, `partial`, string/repr/equality/hash,
  `variables`, and ordered `variable_names`
- scalar, list/tuple, mapping, and ordered list-of-pairs values
- all RFC operators: simple, reserved, fragment, label, path, path parameter,
  query, and query continuation
- explode (`*`), Unicode-aware prefix (`:n`), undefined and empty values, and
  the legacy `name=default` syntax supported by upstream

The RFC examples are asserted directly and the broader behavior suite compares
against `uritemplate` 4.2.0. This repository does not replace upstream's
internal `Operator` enum and quoting helper modules; callers using those
undocumented implementation details still need upstream. Template validation
also follows upstream's permissive behavior rather than adding a stricter RFC
syntax checker. Like upstream 4.2.0, composite detection is limited to
list/tuple, `dict`, and mutable-mapping values; arbitrary immutable `Sequence`
or `Mapping` implementations are not covered.

## Install and run

The Pixi environment supplies Python, the pinned Mojo nightly, pytest, and the
upstream parity dependency. From a source checkout:

```bash
pixi install
pixi run build
pixi run test
pixi run bench
```

`pixi run build` creates `dist/libmojo-uritemplate.so`. Importing the Python
package also rebuilds the library if the Mojo source is newer. A packaged
deployment can set `MOJO_URITEMPLATE_LIB` to an already-built shared library.
This repository does not currently publish a wheel containing the native
library; the supported installation is the Pixi source environment above.
Run the usage example with `pixi run python`.

## Benchmarks

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz, Linux
x86-64, Python 3.13.14. Times are best per call after warm-up and include
Python value serialization, ctypes, native expansion, and UTF-8 decoding.

| case | mojo-uritemplate | uritemplate 4.2.0 | relative |
| --- | ---: | ---: | ---: |
| API URL, scalar + list | 55.0 µs | 45.5 µs | 1.21x slower |
| percent-encode 64 KiB | 315.4 µs | 2.70 ms | 8.57x faster |
| percent-encode 1 MiB | 10.17 ms | 50.51 ms | 4.97x faster |
| explode 10k path segments | 8.25 ms | 38.64 ms | 4.69x faster |
| explode 5k query pairs | 8.12 ms | 15.47 ms | 1.91x faster |
| cached template, 100 scalars | 146.4 µs | 369.9 µs | 2.53x faster |

These are the complete benchmark cases, not selected wins. The smallest case
still includes the fixed FFI boundary; the larger cases show the benefit of
performing byte classification, percent encoding, and joining in one native
pass.

The native byte classification and bounded-copy loops use SIMD with scalar
tails. Expansion remains serial because values produce variable-length output,
so parallel writing would require an additional count and prefix-offset pass;
the measured workloads do not repay that overhead.

There is intentionally no GPU path. URI expansion is branch-heavy byte
classification and copying with essentially no floating-point work, well below
two arithmetic operations per byte moved. Host/device transfer and launch
overhead would dominate.

## How it works

The Python wrapper merges `var_dict` and keyword overrides using upstream's
rules, then encodes each value as one of four wire types: undefined, scalar,
sequence, or ordered mapping. Lengths are little-endian 32-bit integers and
all string payloads are UTF-8. Mapping order is resolved in Python exactly as
upstream does; no Python expansion or quoting is performed.

The shared-library function receives the template, value stream, and output
buffer as `Int` addresses. Inside the exported `abi("C")` boundary they become
`UnsafePointer[UInt8, AnyOrigin[mut=True]]` values. Mojo scans the template and
wire data without allocating, writing into caller-owned memory. The ABI entry
rejects null pointers, invalid top-level lengths, unknown wire tags, and any
nested field that would exceed the supplied wire length before rendering. The
mutable wire buffer crosses the FFI boundary zero-copy and Python keeps the
template and wire owners alive for the complete native call. If the first
output buffer is too small, Mojo returns the required byte count and Python
retries at that exact size. Python owns every allocation and decodes the
finished UTF-8 buffer to `str`.

The Mojo code is one compilation unit because shared-library build cost is
mostly fixed for this toolchain.

## License

MIT.
