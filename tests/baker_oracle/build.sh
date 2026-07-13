#!/bin/sh
# Build Erik Baker's original GFDECO program (test oracle).
set -e
cd "$(dirname "$0")"
gfortran -std=legacy -O2 -o gfdeco gfdeco.f
echo "built $(pwd)/gfdeco"
