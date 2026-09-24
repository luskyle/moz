#!/usr/bin/env python3
"""用**现成的 DXF 语料**回归 P1 的解析/修复/成型（对应 docs/2d-to-3d.md 的 P1）。

语料（都在仓库里，不需要外部路径）：

- ``3rd/openscad/testdata/**/*.dxf``：上游 OpenSCAD 自带的 DXF 测试集，覆盖
  圆/圆弧/椭圆（含旋转与反向）/LWPOLYLINE（含闭合与 bulge）/块引用（INSERT）/凹多边形/
  多孔/自交/重叠/缺单位/缺省层名等边界情况——正是修复层最容易被现实打脸的地方；
- ``corpus/dxf/**/*.dxf``：公开仓库里抓来的真实图纸（LibreCAD 零件库与解析器测试集、
  dxf-viewer 的块/标注专项样例、FreeCAD 零件库、KiCad 的 PCB 板框与 Fusion360 样条，
  以及本项目的真实板框图）——来源、许可与更新方式见 ``corpus/dxf/README.md``；
- ``py/moz_data/drawings/*.dxf``：本项目 P1 的验收样例（见 scripts/make_dxf_samples.py）。

判定（三档，和 ``py/verify_examples.py`` 同风格）：

- **OK**：解析成功且能挤出正体积；
- **EMPTY**：文件里本来就没有能成环的实体（纯标注/纯文字/纯元数据，例如 dxf-viewer 的
  ``dimension-*`` 与 LibreCAD 的编码测试集）——"没有材料可建模"是事实，不是失败；判定前会用
  ezdxf **独立复核**：文件里真有能成环的实体却没产出轮廓，那就是 FAIL；
- **OPEN**：图纸本身没闭合（或互相重叠导致无法成环）→ 必须报"开口链"并**拒绝挤出**
  （不静默出一个坏模型）。注意：默认策略 ``open_chains="close"`` 会像引擎 ``import()`` 那样
  **隐式闭合**画断的链（并报出缺口大小），所以现在语料里没有 OPEN 档；这一档留给未来
  ``open_chains="report"`` 的严格场景；
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
    ("上游 testdata", os.path.join(ROOT, "3rd", "openscad", "testdata")),
    ("公开语料", os.path.join(ROOT, "corpus", "dxf")),
    ("P1 样例", os.path.join(ROOT, "py", "moz_data", "drawings")),
]

# 图纸本身没闭合 / 重叠到成不了环：预期报开口并拒绝挤出（当前语料里没有这类；默认策略
# open_chains="close" 会像引擎一样隐式闭合，严格模式见 py/moz_dxf.py 的 open_chains="report"）
EXPECTED_OPEN = set()
# 病态文件：预期解析失败（小数点写成逗号）
EXPECTED_BAD = {"nothing-decimal-comma-separated.dxf"}

# 能参与成环的实体类型：文件里连这些都没有，那"没有轮廓"就是事实而不是我们的 bug
LOOP_ENTITIES = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE", "HATCH"}


def has_loop_entities(path):
    """用 ezdxf 独立看一眼文件里有没有"能成环"的实体（用于区分"本来没几何"和"我们漏了"）。"""
    import ezdxf

    document = ezdxf.readfile(path)
    return any(entity.dxftype() in LOOP_ENTITIES for entity in document.modelspace())


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

    if not drawing.contours and not drawing.open_contours:
        # 完全没有轮廓：先独立看一眼文件里有没有"能成环"的实体——没有就是"没材料可建模"
        # （纯标注/纯文字/纯元数据文件，例如 dxf-viewer 的 dimension-* 与 LibreCAD 的编码测试集），
        # 有却说没有轮廓才是我们的 bug
        try:
            loops = has_loop_entities(path)
        except Exception as exc:
            return "FAIL", f"复核失败：{type(exc).__name__}: {str(exc)[:40]}"
        detail = (f"无成环实体（标注 {len(drawing.dimensions)}，忽略 {sum(drawing.unsupported.values())}）"
                  f"→ 没有材料可建模")
        return ("EMPTY" if not loops else "FAIL"), detail if not loops else (
            f"文件里有能成环的实体（{dict(drawing.entity_counts)}）却没产出轮廓")

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

    groups = [
        (title, sorted(glob.glob(os.path.join(directory, "**", "*.dxf"), recursive=True)))
        for title, directory in CORPORA
    ]
    if args.extra:
        groups.append(("附加图纸", args.extra))

    totals = {"OK": 0, "EMPTY": 0, "OPEN": 0, "BAD": 0, "FAIL": 0}
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

    print(f"\n汇总: OK={totals['OK']} EMPTY={totals['EMPTY']}（本来就没材料）"
          f" OPEN={totals['OPEN']}（预期开口） BAD={totals['BAD']}（预期坏图） FAIL={totals['FAIL']}")
    for path, detail in failures:
        print(f"  失败: {path} —— {detail}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
