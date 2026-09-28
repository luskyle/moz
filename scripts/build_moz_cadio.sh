#!/usr/bin/env bash
# 构建 libmozcadio.so —— libdxfrw（上游 2.0.0，DXF/DWG 解析核心）+ 我们的 C ABI
#
# 依赖：只需 cmake + g++（**没有** Qt、没有 zlib、不需要几何内核）
#
# 环境变量:
#   JOBS=N   并行度（默认 nproc）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/3rd/libdxfrw/moz"
BUILD="$ROOT/build/3rd/libdxfrw"
OUT="$ROOT/build/lib"
JOBS="${JOBS:-$(nproc)}"

cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --target mozcadio -j"$JOBS"

mkdir -p "$OUT"
# 原子替换（同文件系统 rename）：原地覆盖正被进程映射的 .so 会让那个进程收到 SIGBUS
cp "$BUILD/libcadio_moz.so" "$OUT/.libmozcadio.so.tmp"
mv -f "$OUT/.libmozcadio.so.tmp" "$OUT/libmozcadio.so"
echo "OK -> $OUT/libmozcadio.so"