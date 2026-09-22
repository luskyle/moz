#!/usr/bin/env bash
# 打一个自带 libmozopenscad.so 与运行时数据的 wheel（平台相关，如 py3-none-linux_x86_64）。
#
# 步骤：
#   1) 缺共享库时先构建（scripts/build_moz_openscad.sh）
#   2) 把 build/lib/libmozopenscad.so 拷进 py/moz_data/lib/（该目录不入库）
#   3) bdist_wheel，并检查 wheel 里真的带上了 .so、配色方案、字体、MCAD 字形表、示例数据
#
# 用法：
#     bash scripts/build_wheel.sh
#     OUT=/tmp/wheels bash scripts/build_wheel.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SO="$ROOT/build/lib/libmozopenscad.so"
DEST="$ROOT/py/moz_data/lib"
OUT="${OUT:-$ROOT/build/dist}"
# 平台标签：纯 C ABI 的 .so 不需要 cp3xx 标签，但必须带上平台（否则会在别的平台上被装上）
PLAT="$(python3 -c "import sysconfig; print(sysconfig.get_platform().replace('-', '_').replace('.', '_'))")"

if [[ ! -f "$SO" ]]; then
  echo "== 没有 $SO，先构建共享库 =="
  bash "$ROOT/scripts/build_moz_openscad.sh"
fi

mkdir -p "$DEST" "$OUT"
# 原子替换：正在跑的进程可能映射着旧文件，直接覆盖会 SIGBUS
cp -f "$SO" "$DEST/libmozopenscad.so.tmp"
mv -f "$DEST/libmozopenscad.so.tmp" "$DEST/libmozopenscad.so"
echo "== 已就位: $DEST/libmozopenscad.so ($(du -h "$DEST/libmozopenscad.so" | cut -f1)) =="

# 注意 --build-base：setuptools 默认的暂存目录就是 build/lib，正好是原生 .so 的输出目录，
# 撞在一起会把那份 .so 额外带一份到 wheel 根目录，所以这里换到 build/wheel。
cd "$ROOT"
python3 setup.py build --build-base "$ROOT/build/wheel" bdist_wheel --plat-name "$PLAT" --dist-dir "$OUT" >/dev/null

WHEEL="$(ls -t "$OUT"/moz_openscad-*.whl | head -1)"
echo "== wheel: $WHEEL ($(du -h "$WHEEL" | cut -f1)) =="
python3 - "$WHEEL" <<'EOF'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    names = archive.namelist()

def count(prefix):
    return sum(1 for name in names if name.startswith(prefix))

checks = {
    "moz_openscad.py": "moz_openscad.py" in names,
    "moz_drawing.py": "moz_drawing.py" in names,
    "类型存根": "moz_openscad.pyi" in names,
    "moz_data/lib/libmozopenscad.so": "moz_data/lib/libmozopenscad.so" in names,
    "没有多余的顶层 .so": "libmozopenscad.so" not in names,
    "配色方案": count("moz_data/color-schemes/render/") > 0,
    "引擎字体": count("moz_data/fonts/Liberation-2.00.1/ttf/") > 0,
    "中文字库": "moz_data/fonts/MozSansSC-Regular.ttf" in names,
    "MCAD 字形表": "moz_data/libraries/MCAD/fonts.scad" in names,
    "示例数据": count("moz_data/examples/") > 0,
}
for label, ok in checks.items():
    print(f"  {'OK  ' if ok else '缺失'} {label}")
if not all(checks.values()):
    sys.exit("wheel 内容不完整")
print(f"  （共 {len(names)} 个文件）")
EOF