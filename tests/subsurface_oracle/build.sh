#!/bin/sh
# Build libsubsurface_deco.so from the unmodified upstream deco.cpp + shim.
set -e
cd "$(dirname "$0")"
g++ -std=c++20 -O2 -fPIC -shared \
    -I stubs -I upstream \
    upstream/deco.cpp stubs/shim.cpp \
    -o libsubsurface_deco.so
echo "built $(pwd)/libsubsurface_deco.so"
