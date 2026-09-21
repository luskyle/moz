#!/usr/bin/env bash
# 构建 OpenSCAD 2021.01 无 GUI 核心为共享库 libmozopenscad.so
#
# 依赖（Ubuntu 22.04）:
#   sudo apt-get update
#   sudo apt-get install -y libcgal-dev libgmp-dev libmpfr-dev libopencsg-dev \
#     libglew-dev libdouble-conversion-dev libzip-dev lib3mf-dev libgettextpo-dev \
#     libglib2.0-dev libcairo2-dev libfreetype-dev libfontconfig1-dev libharfbuzz-dev \
#     libxml2-dev qtbase5-dev libeigen3-dev libboost-all-dev
#
# 环境变量:
#   NULLGL=ON  无 OpenGL / OpenCSG 依赖（PNG 渲染为空实现，仅几何验证用）
#   JOBS=N     并行度
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENSCAD="$ROOT/3rd/openscad"
BUILD="$ROOT/build/3rd/openscad"
OUT="$ROOT/build/lib"

NULLGL="${NULLGL:-OFF}"
JOBS="${JOBS:-$(nproc)}"

cmake -S "$OPENSCAD" -B "$BUILD" \
  -DHEADLESS=ON \
  -DNULLGL="$NULLGL" \
  -DINFO=OFF \
  -DBUILD_TESTING=OFF \
  -DCMAKE_BUILD_TYPE=Release

cmake --build "$BUILD" --target mozopenscad -j"$JOBS"

mkdir -p "$OUT"
# 原子替换（同文件系统 rename）：原地覆盖正在被进程映射的 .so，会让那个进程在换页时
# 收到 SIGBUS（总线错误）——实测踩过一次，整个验证跑直接崩掉。
cp "$BUILD/objects/libopenscad_moz.so" "$OUT/.libmozopenscad.so.tmp"
mv -f "$OUT/.libmozopenscad.so.tmp" "$OUT/libmozopenscad.so"
echo "OK -> $OUT/libmozopenscad.so"