#!/usr/bin/env python3
"""moz 制图示例：把一个零件的三视图 + 剖视排成一张 A3 图，并导出 SVG/DXF/PDF。

    PYTHONPATH=py python3 py/drawing_demo.py

产物写到 build/out/drawing/（该目录不入库）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moz_drawing as dw
import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "out", "drawing")

# --- 零件：带中心孔的支座 ---
WIDTH, DEPTH, HEIGHT = 60.0, 40.0, 20.0
HOLE_RADIUS = 8.0
HOLE_OFFSET = 18.0

part = moz.difference(
    moz.cube([WIDTH, DEPTH, HEIGHT], center=True),
    moz.cylinder(r=HOLE_RADIUS, h=HEIGHT + 4, center=True, fn=64),
    moz.translate([-HOLE_OFFSET, 0, 0], moz.cylinder(r=4, h=HEIGHT + 4, center=True, fn=48)),
    moz.translate([+HOLE_OFFSET, 0, 0], moz.cylinder(r=4, h=HEIGHT + 4, center=True, fn=48)),
)
measured = part.measure
print(f"零件: 体积 {measured.volume:.1f} mm³, 表面积 {measured.area:.1f} mm², {measured.facets} 面")
print(f"      包围盒 {tuple(round(v, 1) for v in measured.bbox_min)} → "
      f"{tuple(round(v, 1) for v in measured.bbox_max)}")


def build_drawing(scale=1.5):
    drawing = dw.Drawing(
        size="A3", landscape=True, margin=12,
        title="支座", number="MZ-DEMO-01", material="Q235",
        author="luskyle", date="2026-09-22", scale_note=f"{scale:g}:1",
    )

    # 主视图（前视轮廓）：宽 × 高
    front = drawing.add_view("front", moz.outline(part, moz.FRONT),
                             at=(85, 175), scale=scale, label="主视图")
    # 俯视图：宽 × 深
    top = drawing.add_view("top", moz.outline(part, moz.UP),
                           at=(85, 110), scale=scale, label="俯视图")
    # 左视图：深 × 高
    side = drawing.add_view("side", moz.outline(part, moz.RIGHT),
                            at=(205, 175), scale=scale, label="左视图")
    # A—A 剖视：过中心孔的水平面，带剖面线
    sectioned = drawing.add_view("A-A", moz.section(part, moz.UP),
                                 at=(265, 110), scale=scale, label="A—A 剖视", hatched=True)

    # 总体尺寸（视图坐标）
    drawing.dim(front, "linear", (-WIDTH / 2, -HEIGHT / 2), (WIDTH / 2, -HEIGHT / 2), offset=-12)
    drawing.dim(front, "linear", (-WIDTH / 2, -HEIGHT / 2), (-WIDTH / 2, HEIGHT / 2), offset=12)
    drawing.dim(top, "linear", (-WIDTH / 2, -DEPTH / 2), (WIDTH / 2, -DEPTH / 2), offset=-12)
    drawing.dim(top, "linear", (-WIDTH / 2, DEPTH / 2), (-WIDTH / 2, -DEPTH / 2), offset=12)
    # 孔的直径标注
    drawing.dim(sectioned, "diameter", (0, 0), HOLE_RADIUS, angle=35)
    drawing.dim(side, "linear", (-DEPTH / 2, -HEIGHT / 2), (DEPTH / 2, -HEIGHT / 2), offset=-13)
    # 小孔定位尺寸 + 中心线
    drawing.dim(top, "linear", (-HOLE_OFFSET, -DEPTH / 2), (HOLE_OFFSET, -DEPTH / 2), offset=10)
    for center_x in (-HOLE_OFFSET, 0.0, HOLE_OFFSET):
        x, y = top.to_sheet((center_x, 0))
        radius = (HOLE_RADIUS if center_x == 0 else 4.0) * scale + 2
        drawing.add_centerline((x - radius, y), (x + radius, y))
        drawing.add_centerline((x, y - radius), (x, y + radius))

    drawing.add_note((25, 42), "技术要求：", size=4)
    drawing.add_note((25, 36), "1. 未注圆角 R2；", size=3.5)
    drawing.add_note((25, 31), "2. 去除毛刺锐边；", size=3.5)
    drawing.add_note((25, 26), "3. 中心孔 ⌀16H7。", size=3.5)
    return drawing


def check_font():
    """确认字体真的出中文：缺字形时引擎不报错，只画空心方框（每字 8 个面）。"""
    facets = dw.text_at((0, 0), "中").measure.facets
    ok = facets > 8
    print(f"字体: {dw.TEXT_FONT}（中文可渲染: {ok}）")
    if not ok:
        print("  ⚠ 这个字体没有中文字形，图上会出现空心方框：装个中文字体，"
              "或把 dw.TEXT_FONT 指到已装的家族名")
    return ok


def main():
    os.makedirs(OUT, exist_ok=True)
    check_font()
    drawing = build_drawing()
    sheet = drawing.build()
    print(f"图面: {sheet.dimension}D, {sheet.measure.facets} 个面, 面积 {sheet.measure.area:.0f} mm²")
    bbox = drawing.content_bbox()
    print(f"内容范围: ({bbox[0]:.1f}, {bbox[1]:.1f}) → ({bbox[2]:.1f}, {bbox[3]:.1f})"
          f"，图框内区 {drawing.inner}")
    print(f"版式自查（留一个线宽容差）: 全部在图框内 = {drawing.fits(tolerance=dw.THICK_WIDTH)}")
    for fmt in ("svg", "dxf", "pdf"):
        path = os.path.join(OUT, f"bracket.{fmt}")
        drawing.export(fmt, path)
        print(f"导出 {fmt}: {path}（{os.path.getsize(path)} 字节）")
    print("要用预览器看图：PYTHONPATH=py python3 -c "
          "\"import sys; sys.path.insert(0,'py'); import drawing_demo; drawing_demo.build_drawing().show()\"")
    print("产物目录 ->", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
