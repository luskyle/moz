#!/usr/bin/env bash
# 把渲染后端打包进扩展：py/moz_cadio.py、py/moz_cadview.py + **build/lib 里存在的
# 各平台 libmozcadio 动态库**（libmozcadio.so / .dylib / mozcadio.dll）→ 扩展的
# python/（moz_data/lib 布局，moz_cadio.py 运行时按平台选库名；文件名与 backend.ts
# 的 libName() 一致）。
# - 本地开发只有本平台库 → 打包成单平台 vsix；
# - CI 发布把三平台库合并进 build/lib 后再跑本脚本 → 生成**通用 vsix**（一个包
#   装到哪个平台都能跑）。
# 由 `npm run bundle-backend` 调用；`npm run package` 会先跑它。
set -euo pipefail

EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$EXT_DIR/../.." && pwd)"

ALL_LIBS=("libmozcadio.so" "libmozcadio.dylib" "mozcadio.dll")
COPIED=()
for LIB_NAME in "${ALL_LIBS[@]}"; do
  LIB="$REPO_ROOT/build/lib/$LIB_NAME"
  if [[ -f "$LIB" ]]; then
    COPIED+=("$LIB_NAME")
  fi
done

if [[ ${#COPIED[@]} -eq 0 ]]; then
  echo "build/lib 下没有 libmozcadio 动态库 —— 先在仓库根跑：bash scripts/build_moz_cadio.sh" >&2
  exit 1
fi

mkdir -p "$EXT_DIR/python/moz_data/lib"
cp "$REPO_ROOT/py/moz_cadio.py" "$EXT_DIR/python/"
cp "$REPO_ROOT/py/moz_cadview.py" "$EXT_DIR/python/"
for LIB_NAME in "${COPIED[@]}"; do
  cp "$REPO_ROOT/build/lib/$LIB_NAME" "$EXT_DIR/python/moz_data/lib/"
done
echo "已打包后端 → python/（py/moz_cadio.py、py/moz_cadview.py、moz_data/lib/$(IFS=,; echo "${COPIED[*]}")）"