#!/bin/sh
# Build swmm524-perched as a wasm32-wasi module with Zig's C toolchain (pip install ziglang).
# -O2, no fast-math and no FP contraction; the shim supplies mkstemp, which wasi-libc lacks.
set -e
cd "$(dirname "$0")/.."
python3 -m ziglang cc -target wasm32-wasi -O2 -fno-fast-math -ffp-contract=off \
  -D_WASI_EMULATED_SIGNAL -D_WASI_EMULATED_PROCESS_CLOCKS -include wasm/wasi_shim.h -Wl,--strip-all \
  -o wasm/swmm524-perched.wasm src/solver/*.c src/run/main.c wasm/wasi_shim.c \
  -I src/solver -I src/solver/include -lm -lwasi-emulated-signal -lwasi-emulated-process-clocks
echo "built wasm/swmm524-perched.wasm"
# run it under Node:  node wasm/runwasi.mjs wasm/swmm524-perched.wasm model.inp model.rpt model.out
