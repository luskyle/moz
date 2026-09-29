#!/usr/bin/env bash
# 构建 libmozcadio 动态库 —— libdxfrw（上游 2.0.0，DXF/DWG 解析核心）+ 我们的 C ABI
#
# 依赖：只需 cmake + 编译器（**没有** Qt、没有 zlib、不需要几何内核）
#   Linux:   cmake + g++        -> build/lib/libmozcadio.so
#   macOS:   cmake + clang      -> build/lib/libmozcadio.dylib
#   Windows: cmake + MSVC       -> build/lib/mozcadio.dll
#
# 环境变量:
#   JOBS=N   并行度（默认 nproc）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/3rd/libdxfrw/moz"
BUILD="$ROOT/build/3rd/libdxfrw"
OUT="$ROOT/build/lib"
JOBS="${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)}"

# 平台 → 源库名（CMake OUTPUT_NAME=cadio_moz 的平台产物）与最终发布名（与
# backend.ts 的 libName() 及 moz_cadio._lib_names() 一致）
case "$(uname -s)" in
  Darwin*)
    LIB_FILE="libcadio_moz.dylib"
    LIB_NAME="libmozcadio.dylib"
    BUILD_ARGS=(--config Release)
    ;;
  MSYS*|MINGW*|CYGWIN*)
    LIB_FILE="Release/cadio_moz.dll"      # MSVC 多配置：输出在 <build>/<config>/
    LIB_NAME="mozcadio.dll"
    BUILD_ARGS=(--config Release)
    ;;
  *)
    LIB_FILE="libcadio_moz.so"
    LIB_NAME="libmozcadio.so"
    BUILD_ARGS=()
    ;;
esac

cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --target mozcadio -j"$JOBS" "${BUILD_ARGS[@]}"

mkdir -p "$OUT"
# 原子替换（同文件系统 rename）：原地覆盖正被进程映射的库会让那个进程收到 SIGBUS
cp "$BUILD/$LIB_FILE" "$OUT/.$LIB_NAME.tmp"
mv -f "$OUT/.$LIB_NAME.tmp" "$OUT/$LIB_NAME"
echo "OK -> $OUT/$LIB_NAME"