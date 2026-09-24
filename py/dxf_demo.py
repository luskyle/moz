#!/usr/bin/env python3
"""把一张 DXF 图纸变成模型（P1 演示）。

    PYTHONPATH=py python3 py/dxf_demo.py <图纸.dxf> [选项]

默认行为：打印解析 + 修复报告、截面/体积/重量，然后按需导出。示例：

    # 看一眼这张图画了什么（解析报告 + 体积）
    PYTHONPATH=py python3 py/dxf_demo.py py/moz_data/drawings/plate.dxf --height 5

    # 只要某个图层（例如激光切割的轮廓层），导出 STL + 参数表
    PYTHONPATH=py python3 py/dxf_demo.py 客户图.dxf --layer OUTLINE --height 6 \
        --parameters-json build/out/params.json --export-stl build/out/part.stl

    # 走完整闭环：图纸 → 模型 → 再出图（SVG/DXF/PDF）
    PYTHONPATH=py python3 py/dxf_demo.py 客户图.dxf --height 6 --drawing build/out/part.pdf
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import moz_dxf
import moz_openscad as moz


def build_parser():
    parser = argparse.ArgumentParser(description="DXF 图纸 → 参数化模型（P1）")
    parser.add_argument("dxf", help="输入 DXF 路径")
    parser.add_argument("--height", type=float, default=5.0, help="挤出高度（mm，默认 5）")
    parser.add_argument("--layer", action="append", default=None,
                        help="只处理这些图层（可重复；不指定则按图层名语义判断）")
    parser.add_argument("--exclude-layer", action="append", default=None, help="排除的图层（可重复）")
    parser.add_argument("--hole-layer", action="append", default=None, help="强制当作孔的图层（可重复）")
    parser.add_argument("--arc-chord-tolerance", type=float, default=0.01,
                        help="圆弧离散的弦高容差（mm，默认 0.01）")
    parser.add_argument("--bridge-tolerance", type=float, default=0.05,
                        help="缺口桥接容差（mm，默认 0.05）")
    parser.add_argument("--unit-scale", type=float, default=None, help="覆盖图纸单位换算（例如 25.4）")
    parser.add_argument("--density", type=float, default=7.85,
                        help="材料密度 g/cm³（默认 7.85 = 钢），用于估算重量")
    parser.add_argument("--parameters-json", default=None, help="把命名标注写成 JSON")
    parser.add_argument("--export-stl", default=None, help="导出模型（.stl）")
    parser.add_argument("--drawing", default=None, help="反向出图（.pdf/.svg/.dxf），图幅 A4 横放")
    return parser


def make_drawing(part, path, title):
    """把模型再画回一张图（复用已有的制图层）——也就是"图纸 ⇄ 模型"闭环的右半边。"""
    import moz_drawing as dw

    outline = moz.outline(part, moz.UP)
    low, high = outline.measure.bbox
    size = max(high[0] - low[0], high[1] - low[1]) or 1.0
    half = ((high[0] - low[0]) / 2, (high[1] - low[1]) / 2)
    scale = min(150.0 / size, 3.0)
    # 视图以自己中心为原点（add_view 是"按原坐标平移 + 缩放"，所以要先居中）
    centered = moz.translate([-low[0] - half[0], -low[1] - half[1]], outline)

    sheet = dw.Drawing(size="A4", landscape=True, margin=12, title=title, scale_note=f"{scale:g}:1")
    view = sheet.add_view("top", centered, at=(148.0, 108.0), scale=scale,
                          label="俯视图（轮廓）", label_at=(148.0, 60.0))
    sheet.dim(view, "linear", (-half[0], -half[1]), (half[0], -half[1]), offset=-10)   # 宽
    sheet.dim(view, "linear", (-half[0], -half[1]), (-half[0], half[1]), offset=10)     # 高
    sheet.export(os.path.splitext(path)[1].lstrip("."), path)
    return sheet


def main(argv=None):
    args = build_parser().parse_args(argv)

    drawing = moz_dxf.read_dxf(
        args.dxf,
        layers=args.layer,
        exclude_layers=args.exclude_layer,
        hole_layers=args.hole_layer,
        arc_chord_tolerance=args.arc_chord_tolerance,
        bridge_tolerance=args.bridge_tolerance,
        unit_scale=args.unit_scale,
    )
    print(drawing.report())

    part = drawing.extrude(height=args.height)
    measured = part.measure
    print(f"模型    : 挤出高度 {args.height:g} mm → {measured.facets} 面，"
          f"体积 {measured.volume:.1f} mm³，表面积 {measured.area:.1f} mm²")
    print(f"重量    : {measured.volume * args.density / 1000:.2f} g"
          f"（密度 {args.density:g} g/cm³）")

    if args.parameters_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.parameters_json)), exist_ok=True)
        drawing.write_parameters(args.parameters_json)
        print(f"参数表  : {args.parameters_json}（{len(drawing.parameters())} 个命名标注）")

    if args.export_stl:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_stl)), exist_ok=True)
        part.export("binstl", args.export_stl)
        print(f"导出 STL: {args.export_stl}（{os.path.getsize(args.export_stl)} 字节）")

    if args.drawing:
        os.makedirs(os.path.dirname(os.path.abspath(args.drawing)), exist_ok=True)
        sheet = make_drawing(part, args.drawing, os.path.basename(args.dxf))
        print(f"反向出图: {args.drawing}（{os.path.getsize(args.drawing)} 字节，"
              f"版式自查 {sheet.fits(tolerance=1.0)}）")

    if not (args.parameters_json or args.export_stl or args.drawing):
        print("\n（没有指定导出项：加 --export-stl / --drawing / --parameters-json 试试）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
