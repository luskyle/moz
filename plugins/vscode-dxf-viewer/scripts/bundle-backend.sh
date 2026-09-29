#!/usr/bin/env bash
# 把渲染后端打包进扩展：py/moz_cadio.py、py/moz_cadview.py + 构建出的 libmozcadio.so
# → 扩展的 python/（moz_data/lib 布局，正好是 moz_cadio.py 的默认加载目录）。
# 由 `npm run bundle-backend` 调用；`npm run package` 会先跑它。
set -euo pipefail

EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$EXT_DIR/../.." && pwd)"
SO="$REPO_ROOT/build/lib/libmozcadio.so"

if [[ ! -f "$SO" ]]; then
  echo "缺少 $SO —— 先在仓库根跑：bash scripts/build_moz_cadio.sh" >&2
  exit 1
fi

mkdir -p "$EXT_DIR/python/moz_data/lib"
cp "$REPO_ROOT/py/moz_cadio.py" "$EXT_DIR/python/"
cp "$REPO_ROOT/py/moz_cadview.py" "$EXT_DIR/python/"
cp "$SO" "$EXT_DIR/python/moz_data/lib/"
echo "已打包后端 → python/（py/moz_cadio.py、py/moz_cadview.py、moz_data/lib/$(basename "$SO")）"