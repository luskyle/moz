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
# 病态文件：预期连 ezdxf 的修复模式都读不出来（LWPOLYLINE 缺子类标记）
# 注意：`nothing-decimal-comma-separated.dxf`（小数点写成逗号）**已经不在这一档**——
# 加了 ezdxf 修复模式回退之后它也能读了（挤出 4 mm³），现在按正常文件判定。
EXPECTED_BAD = {"test__data__blocks.dxf"}

# 能参与成环的实体类型
LOOP_ENTITIES = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE", "HATCH"}
# 自己就能成环的（圆/椭圆/闭合多段线）：文件里有这些，我们就**必须**产出轮廓
SELF_CLOSED = {"CIRCLE", "ELLIPSE"}


def _entity_endpoints(entity):
    """实体的两个端点（用于独立判断"这些线能不能接成环"）。"""
    kind = entity.dxftype()
    if kind == "LINE":
        return [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    if kind == "ARC":
        return [(entity.start_point.x, entity.start_point.y), (entity.end_point.x, entity.end_point.y)]
    if kind in ("LWPOLYLINE", "POLYLINE"):
        points = [(p[0], p[1]) for p in entity.get_points("xy")]
        return [points[0], points[-1]] if len(points) >= 2 else []
    if kind == "SPLINE":
        points = [(float(p[0]), float(p[1])) for p in getattr(entity, "control_points", [])]
        return [points[0], points[-1]] if len(points) >= 2 else []
    return []


def loop_evidence(path):
    """独立（不经我们的解析器）判断文件里"有没有能成环的可能"，返回：

    ``("none", n)``   没有能成环的实体（纯标注/文字/元数据）；
    ``("closed", n)`` 有自己就能成环的实体（圆/椭圆/闭合多段线）——我们必须产出轮廓；
    ``("shared", n)`` 端点被两条以上段共享——有可能接成环；
    ``("loose", n)``  有直线/圆弧但彼此不共享端点（例如"每层一条独立线"）——成不了环。
    """
    import ezdxf

    document = ezdxf.readfile(path)
    kinds, endpoints = [], []
    for entity in document.modelspace():
        kind = entity.dxftype()
        if kind not in LOOP_ENTITIES:
            continue
        kinds.append(kind)
        if kind in SELF_CLOSED or (kind in ("LWPOLYLINE", "POLYLINE") and entity.closed):
            return "closed", len(kinds)
        endpoints.extend(_entity_endpoints(entity))
    rounded = [(round(x, 6), round(y, 6)) for x, y in endpoints]
    if len(rounded) != len(set(rounded)):
        return "shared", len(kinds)
    return ("loose" if kinds else "none"), len(kinds)


def check(path):
    """检查一个文件，返回 (判定, 说明)。判定取值 OK / EMPTY / OPEN / BAD / FAIL。"""
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
        # 完全没有轮廓：独立复核"文件里到底能不能成环"——
        # 有自闭合实体、或有共享端点却没产出轮廓，才是我们的 bug；其余是"没有材料可建模"
        try:
            evidence, count = loop_evidence(path)
        except Exception as exc:
            return "FAIL", f"复核失败：{type(exc).__name__}: {str(exc)[:40]}"
        rejected = sum(drawing.unsupported.values())
        if evidence == "closed" or (evidence == "shared" and rejected < count):
            return "FAIL", (f"文件里有能成环的几何（{evidence}，{count} 个实体，我们明确拒绝 {rejected} 个）"
                            f"却没产出轮廓（实体 {dict(drawing.entity_counts)}）")
        shape = {"none": "没有能成环的实体", "shared": "几何成不了环", "loose": "线段彼此不连通"}[evidence]
        detail = (f"{shape}（{count} 个实体，明确拒绝 {rejected} 个；标注 {len(drawing.dimensions)}）"
                  f"→ 没有材料可建模")
        return "EMPTY", detail

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
