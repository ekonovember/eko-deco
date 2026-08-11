# Subsurface deco oracle (test-only, GPL-2.0)

This directory vendors the **unmodified** Bühlmann/gradient-factor model code
from the Subsurface dive log (`core/deco.cpp` and the headers it needs,
GPL-2.0, pinned commit in `upstream/UPSTREAM.txt`) plus ~150 lines of stub
headers (`stubs/`) so it compiles standalone:

```
./build.sh   →  libsubsurface_deco.so     (needs g++, C++20)
```

The library is used **only** by `tests/test_subsurface_crosscheck.py`, via the
ctypes wrapper `tests/subsurface_deco.py`, as a reference implementation to
compare eko-deco's output against. It is not part of the eko-deco library and
is never imported at runtime.

## License boundary — read before touching

The full GPL-2.0 text is in [`COPYING`](COPYING), as the license requires of
anyone redistributing this code. The upstream files keep their original
`SPDX-License-Identifier: GPL-2.0` headers and copyright notices, unmodified;
`upstream/UPSTREAM.txt` pins the commit they came from.

eko-deco is MIT; everything under this directory is **GPL-2.0**. Comparing
numerical output against it is fine. Copying code, constants-with-expression
structure, or comments from here into `buhlmann.py` (or anywhere outside this
directory) is **not** — that would relicense the project. Keep fixes to the
Python model clean-room: work from Bühlmann/Baker's published papers and the
numeric disagreement, not from this source.

If g++ is unavailable the cross-check test module skips itself; the rest of
the test suite stays pure-stdlib.
