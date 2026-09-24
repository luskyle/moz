#!/usr/bin/env python3
"""用**现成的 DXF 语料**回归 P1 的解析/修复/成型（对应 docs/2d-to-3d.md 的 P1）。

语料（都在仓库里，不需要外部路径）：

- ``3rd/openscad/testdata/dxf/*.dxf``：上游 OpenSCAD 自带的 DXF 测试集，覆盖
  圆/圆弧/椭圆（含旋转与反向）/LWPOLYLINE（含闭合与 bulge）/块引用（INSERT）/凹多边形/
  多孔/自交/重叠/缺单位/缺省层名等边界情况——正是修复层最容易被现实打脸的地方；
- ``py/moz_data/drawings/*.dxf``：本项目 P1 的验收样例（见 scripts/make_dxf_samples.py）。

判定（三档，和 ``py/verify_examples.py`` 同风格）：

- **OK**：解析成功且能挤出正体积；
- **OPEN**：图纸本身没闭合（或互相重叠导致无法成环）→ 必须报"开口链"并**拒绝挤出**
  （不静默出一个坏模型），这类文件是**预期**的，不是失败；
- **BAD**：预期解析失败的病态文件（例如小数点写成逗号），必须抛 ``OpenSCADError``。

另外可以附加自己的图纸（直接当位置参数给）：

    PYTHONPATH=py python3 py/verify_dxf.py 客户图.dxf /path/to/other.dxf
"""

import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py"))

import moz_dxf  # noqa: E402
import moz_openscad as moz  # noqa: E402

CORPORA = [
    ("上游 testdata", os.path.join(ROOT, "3rd", "openscad", "testdata", "dxf")),
    ("P1 样例", os.path.join(ROOT, "py", "moz_data", "drawings")),
]

# 图纸本身没闭合 / 重叠到成不了环：预期报开口并拒绝挤出
EXPECTED_OPEN = {
    "open-polyline.dxf",
    "polygon-overlap.dxf",
    "issue22127_fusion360_splines.dxf",
}
# 病态文件：预期解析失败（小数点写成逗号）
EXPECTED_BAD = {"nothing-decimal-comma-separated.dxf"}


def check(path):
    """检查一个文件，返回 (判定, 说明)。判定取值 OK / OPEN / BAD / FAIL。"""
    name = os.path.basename(path)
    try:
        drawing = moz_dxf.read_dxf(path)
    except moz.OpenSCADError as exc:
        if name in EXPECTED_BAD:
            return "BAD", f"按预期解析失败：{str(exc)[:60]}"
        return "FAIL", f"意外解析失败：{str(exc)[:80]}"
    except Exception as exc:                     # 任何非 OpenSCADError 的异常都算失败
        return "FAIL", f"抛出未归类异常 {type(exc).__name__}: {str(exc)[:60]}"

    if not drawing.report().strip():
        return "FAIL", "报告为空"

    if drawing.open_contours:
        try:
            drawing.extrude(height=1.0)
        except moz.OpenSCADError:
            detail = (f"外{len(drawing.outlines)} 孔{len(drawing.holes)} 开口{len(drawing.open_contours)}"
                      f" → 拒绝挤出（符合预期）")
            return ("OPEN" if name in EXPECTED_OPEN else "FAIL"), detail
        return "FAIL", "有开口链却仍然挤出了模型（不该发生）"

    try:
        volume = drawing.extrude(height=1.0).measure.volume
    except moz.OpenSCADError as exc:
        return "FAIL", f"挤出失败：{str(exc)[:60]}"
    if volume <= 0:
        return "FAIL", f"体积为 {volume:g}"

    summary = (f"外{len(drawing.outlines)} 孔{len(drawing.holes)} 体积 {volume:.3f} mm³"
               f" 修复{sum(drawing.repairs.values())} 警告{len(drawing.warnings)}")
    if name in EXPECTED_BAD:
        return "FAIL", f"本该解析失败却成功了：{summary}"
    return "OK", summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="用现成 DXF 语料回归 P1")
    parser.add_argument("extra", nargs="*", help="附加要检查的 DXF（例如你自己的图纸）")
    args = parser.parse_args(argv)

    groups = [(title, sorted(glob.glob(os.path.join(directory, "*.dxf")))) for title, directory in CORPORA]
    if args.extra:
        groups.append(("附加图纸", args.extra))

    totals = {"OK": 0, "OPEN": 0, "BAD": 0, "FAIL": 0}
    failures = []
    for title, files in groups:
        if not files:
            print(f"[跳过] {title}：没有 DXF")
            continue
        print(f"--- {title}（{len(files)} 个）---")
        for path in files:
            verdict, detail = check(path)
            totals[verdict] += 1
            print(f"[{verdict:4s}] {os.path.basename(path):44s} {detail}")
            if verdict == "FAIL":
                failures.append((path, detail))

    print(f"\n汇总: OK={totals['OK']} OPEN={totals['OPEN']}（预期开口）"
          f" BAD={totals['BAD']}（预期坏图） FAIL={totals['FAIL']}")
    for path, detail in failures:
        print(f"  失败: {path} —— {detail}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
