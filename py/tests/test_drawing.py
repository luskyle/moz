"""2D 工程图（moz_drawing）测试。

关注点：图元几何是否按预期落在图面上、标注的坐标换算（视图坐标 → 图面坐标）、
剖面线只出现在实体内部、以及三种 2D 导出格式真的产出对应格式的文件。
"""

from pathlib import Path

import moz_drawing as dw
import pytest


def bbox(shape):
    low, high = shape.measure.bbox
    return tuple(round(v, 3) for v in low), tuple(round(v, 3) for v in high)


# --- 图元 ---


def test_line_is_thin_rectangle_between_points(moz):
    low, high = bbox(dw.line((0, 0), (10, 0)))
    assert low == pytest.approx((-0.0, -0.125, 0.0))
    assert high == pytest.approx((10.0, 0.125, 0.0))
    # 斜线：包围盒中心在两点中点，尺寸为投影长度（±线宽）
    low, high = bbox(dw.line((0, 0), (10, 10)))
    assert (low[0] + high[0]) / 2 == pytest.approx(5.0, abs=0.2)
    assert (low[1] + high[1]) / 2 == pytest.approx(5.0, abs=0.2)


def test_line_requires_distinct_points(moz):
    with pytest.raises(ValueError):
        dw.line((1, 1), (1, 1))


def test_polyline_spans_all_vertices(moz):
    low, high = bbox(dw.polyline([(0, 0), (10, 0), (10, 5)]))
    assert low == pytest.approx((0.0, -0.125, 0.0), abs=1e-6)
    assert high == pytest.approx((10.125, 5.0, 0.0), abs=1e-6)   # 竖段的 ± 线宽在 x 方向


def test_arrow_tip_is_at_given_point(moz):
    low, high = bbox(dw.arrow((0, 0), (1, 0), length=3.0, width=1.0))
    assert high[0] == pytest.approx(0.0, abs=1e-6)      # 尖端在 x=0
    assert low[0] == pytest.approx(-3.0, abs=1e-6)      # 箭身沿 -x 展开
    assert high[1] - low[1] == pytest.approx(1.0, abs=1e-6)


# --- 尺寸标注 ---


@pytest.mark.parametrize("value,expected", [
    (40.0, "40"), (3.5, "3.5"), (0.0, "0"), (12.345, "12.35"), (100.0, "100"),
])
def test_label_formatting(moz, value, expected):
    assert dw._format_value(value) == expected


def test_dim_linear_geometry(moz):
    dim = dw.dim_linear((0, 0), (40, 0), offset=10.0, extension=2.0, gap=1.0)
    low, high = bbox(dim)
    # 尺寸线在 +y = 10 上；界线超出到 12，文字再往上一点
    assert high[1] >= 10.0
    assert high[1] <= 12.0 + dw.DIM_TEXT_SIZE
    # 两端不超出量取点（线宽 0.25 所以留 0.2 余量）
    assert low[0] == pytest.approx(0.0, abs=0.2)
    assert high[0] == pytest.approx(40.0, abs=0.2)
    # 尺寸界线下端从 gap 处起画，不再往下延伸
    assert low[1] == pytest.approx(1.0, abs=0.2)


def test_dim_linear_offset_side_follows_normal(moz):
    """offset 为正时尺寸线落在 p1→p2 的左侧（+x 方向的左侧是 +y）。"""
    above = dw.dim_linear((0, 0), (40, 0), offset=10.0)
    below = dw.dim_linear((0, 0), (40, 0), offset=-10.0)
    assert above.measure.bbox[1][1] > 0
    assert below.measure.bbox[0][1] < 0


def test_dim_linear_vertical_text_is_rotated(moz):
    """竖直尺寸的文字必须平行于尺寸线：文字变长只往尺寸线方向（y）长，不会把图撑宽。

    （曾经文字横躺，一条竖直尺寸能横向多占好几个毫米，把标注顶出图框。
    用「文字比尺寸线还长」的构造来证明朝向：旋转后高度被撑开、宽度基本不变。）
    """
    label = "12345678"
    vertical = dw.dim_linear((0, 0), (0, 5), offset=10.0, text=label)
    plain = dw.dim_linear((0, 0), (0, 5), offset=10.0, text="")          # 无文字基线
    vertical_box = vertical.measure.bbox
    plain_box = plain.measure.bbox
    assert (vertical_box[1][1] - vertical_box[0][1]) > (plain_box[1][1] - plain_box[0][1]) + 8
    assert (vertical_box[1][0] - vertical_box[0][0]) - (plain_box[1][0] - plain_box[0][0]) < 4
    # 水平尺寸是它的镜像：宽度被撑开、高度基本不变
    horizontal = dw.dim_linear((0, 0), (5, 0), offset=10.0, text=label)
    horizontal_box = horizontal.measure.bbox
    assert (horizontal_box[1][0] - horizontal_box[0][0]) == pytest.approx(
        vertical_box[1][1] - vertical_box[0][1], abs=0.01)


def test_dim_linear_requires_distinct_points(moz):
    with pytest.raises(ValueError):
        dw.dim_linear((5, 5), (5, 5))


def test_dim_diameter_reaches_leader(moz):
    dim = dw.dim_diameter((0, 0), 8.0, angle=0.0, leader=6.0)
    low, high = bbox(dim)
    assert low[0] == pytest.approx(5.0, abs=0.3)        # 箭身（3mm）朝圆心一侧展开
    assert high[0] >= 14.0                              # 引线到 8 + 6


def test_dim_radius_reaches_leader(moz):
    dim = dw.dim_radius((0, 0), 5.0, angle=0.0, leader=6.0)
    assert bbox(dim)[1][0] >= 11.0


# --- 剖面线 / 中心线 ---


def test_hatch_is_inside_shape(moz):
    square = moz.square([40, 40], center=True)
    filled = dw.hatch(square, spacing=4.0)
    assert 0 < filled.measure.area < 1600
    low, high = bbox(filled)
    assert low == pytest.approx((-20.0, -20.0, 0.0), abs=1.0)
    assert high == pytest.approx((20.0, 20.0, 0.0), abs=1.0)


def test_hatch_of_empty_shape_is_empty(moz):
    empty = moz.section(moz.cube(10, center=True), moz.UP, through=(0, 0, 50))
    assert dw.hatch(empty).is_empty


def test_centerline_is_dashed_and_extended(moz):
    """40 长、两端各伸 2 的中心线：长划-间隙交替，且两端以长划收尾。"""
    dashed = dw.centerline((0, 0), (40, 0), extension=2.0)
    solid = dw.line((0, 0), (40, 0))
    assert dashed.measure.area < solid.measure.area           # 确实是虚线
    assert dashed.measure.area > solid.measure.area * 0.7     # 长划占比高（4:1.5）
    assert dashed.measure.facets >= 6 * 4                     # 至少 6 段长划
    low, high = bbox(dashed)
    assert low[0] == pytest.approx(-2.0, abs=0.2)             # 两端各伸出 extension
    assert high[0] == pytest.approx(42.0, abs=0.2)


def test_centerline_requires_distinct_points(moz):
    with pytest.raises(ValueError):
        dw.centerline((0, 0), (0, 0))


# --- 图面 ---


def test_drawing_inner_area_for_pages(moz):
    portrait = dw.Drawing(size="A4")
    assert portrait.page == (210.0, 297.0)
    assert portrait.inner == (10.0, 10.0, 200.0, 287.0)

    landscape = dw.Drawing(size="A4", landscape=True)
    assert landscape.page == (297.0, 210.0)

    custom = dw.Drawing(size=(100.0, 50.0), margin=5.0)
    assert custom.inner == (5.0, 5.0, 95.0, 45.0)


def test_empty_sheet_is_just_border_and_title_block(moz):
    """空图面：只有图框与标题栏，且都落在图框内区域里。"""
    drawing = dw.Drawing(size="A4", title="空图")
    low, high = bbox(drawing.build())
    x0, y0, x1, y1 = drawing.inner
    assert low == pytest.approx((x0, y0, 0.0), abs=0.01)
    assert high[0] == pytest.approx(x1, abs=0.01)
    assert high[1] <= y1


def test_view_placement_and_scale(moz):
    drawing = dw.Drawing(size="A4", landscape=True)
    view = drawing.add_view("v", moz.square([20, 20], center=True), at=(100, 100), scale=2.0)
    low, high = bbox(view.placed())
    assert low == pytest.approx((80.0, 80.0, 0.0), abs=1e-6)
    assert high == pytest.approx((120.0, 120.0, 0.0), abs=1e-6)
    assert view.to_sheet((0, 0)) == (100.0, 100.0)
    assert view.to_sheet((10, -5)) == (120.0, 90.0)


def test_dimension_on_view_uses_view_coordinates(moz):
    """标注给的是视图坐标：视图缩放 0.5 后，40 长的尺寸只占图面 20。"""
    drawing = dw.Drawing(size="A4", landscape=True)
    view = drawing.add_view("v", moz.square([40, 40], center=True), at=(100, 100), scale=0.5)
    before = len(drawing.annotations)
    drawing.dim(view, "linear", (-20, -20), (20, -20), offset=-10.0)
    assert len(drawing.annotations) == before + 1        # 标注进了注释列表

    # 视图坐标 (-20,-20)→(20,-20) 经 scale=0.5 与 at=(100,100) 换算到 (90,90)→(110,90)；
    # 尺寸线在 y = 90 - 10 = 80（低于视图）
    dim = drawing.annotations[-1]
    low, high = bbox(dim)
    assert low[0] == pytest.approx(90.0, abs=0.3)        # 40 宽 × 0.5 = 20 宽
    assert high[0] == pytest.approx(110.0, abs=0.3)
    assert high[1] == pytest.approx(91.0, abs=0.3)       # 界线从 gap 处起（视图侧）
    assert low[1] == pytest.approx(80.0 - 0.5, abs=0.3)  # 箭头半宽在尺寸线下方


def test_drawing_with_section_and_hatching(moz):
    model = moz.difference(moz.cube([40, 40, 20], center=True),
                           moz.cylinder(r=8, h=40, center=True, fn=64))
    drawing = dw.Drawing(size="A4", landscape=True, title="剖视件", number="MZ-2")
    drawing.add_view("A-A", moz.section(model, moz.UP), at=(100, 100), label="A—A", hatched=True)
    sheet = drawing.build()
    assert sheet.dimension == 2
    # 剖视面积 ≈ 外框 - 内孔（40×40 - 64 边形）
    import math
    hole = 32 * 8 ** 2 * math.sin(2 * math.pi / 64)
    assert sheet.measure.area >= 1600 - hole


def test_drawing_with_empty_view_still_builds(moz):
    drawing = dw.Drawing(size="A4", landscape=True)
    drawing.add_view("miss", moz.section(moz.cube(10, center=True), moz.UP, through=(0, 0, 50)),
                     at=(100, 100), hatched=True)
    assert drawing.build().dimension == 2


def test_drawing_exports_2d_formats(moz, tmp_path):
    drawing = dw.Drawing(size="A4", landscape=True, title="导出件")
    drawing.add_view("v", moz.outline(moz.cube([20, 10, 5], center=True), moz.UP), at=(60, 120))
    signatures = {"svg": b"<?xml", "dxf": b"  0\nSECTION", "pdf": b"%PDF"}
    for fmt, signature in signatures.items():
        path = tmp_path / f"sheet.{fmt}"
        drawing.export(fmt, str(path))
        data = path.read_bytes()
        assert data.startswith(signature), fmt
        assert len(data) > 500, fmt


def test_drawing_rejects_3d_export_formats(moz, tmp_path):
    """图面是 2D，导出 3D 格式应报错（引擎的维度校验）。"""
    drawing = dw.Drawing(size="A4")
    with pytest.raises(moz.OpenSCADError):
        drawing.export("binstl", str(tmp_path / "nope.stl"))


def test_unsupported_dimension_kind(moz):
    drawing = dw.Drawing(size="A4", landscape=True)
    view = drawing.add_view("v", moz.square(10, center=True), at=(50, 50))
    with pytest.raises(ValueError):
        drawing.dim(view, "angle", (0, 0), 5)


# --- 字体 ---
#
# 引擎的默认字体（内置 Liberation Sans）只有拉丁字形，中文会**静默**变成空心方框，
# 所以制图层默认指到随仓库分发的 Moz Sans SC。缺字形时每字恰好画 8 个面（方框）。

BUNDLED_FONT_DIR = Path(dw.__file__).resolve().parents[1] / "assets" / "fonts"
needs_bundled_font = pytest.mark.skipif(
    not BUNDLED_FONT_DIR.is_dir(), reason="自带字库 assets/fonts 不存在（见 scripts/make_cjk_subset_font.py）"
)


def test_text_at_defaults_to_bundled_cjk_font(moz):
    assert dw.TEXT_FONT == "Moz Sans SC"
    assert 'font = "Moz Sans SC"' in dw.text_at((0, 0), "A").source


def test_text_at_font_can_be_overridden(moz):
    assert 'font = "Liberation Sans"' in dw.text_at((0, 0), "A", font="Liberation Sans").source
    assert "font" not in dw.text_at((0, 0), "A", font="").source    # "" = 引擎默认字体


@needs_bundled_font
def test_default_font_renders_chinese_not_boxes(moz):
    real = dw.text_at((0, 0), "技术要求").measure
    boxes = dw.text_at((0, 0), "技术要求", font="").measure
    assert boxes.facets == 8 * len("技术要求")     # 引擎默认字体：4 个空心方框
    assert real.facets > boxes.facets             # 自带字库：真字形
    assert real.bbox_max[0] > boxes.bbox_max[0]


def test_drawing_font_reaches_notes_labels_dims_and_title_block(moz):
    drawing = dw.Drawing(size="A4", landscape=True, title="图名", font="Liberation Sans")
    view = drawing.add_view("v", moz.square(10, center=True), at=(50, 50), label="主视图")
    drawing.dim(view, "linear", (-5, -5), (5, -5), offset=-5)
    drawing.add_note((10, 10), "技术要求")
    source = drawing.build().source
    # 标题栏栏位名 + 视图名 + 尺寸文字 + 说明文字都用图面字体
    assert source.count('font = "Liberation Sans"') >= 4
    assert "Moz Sans SC" not in source
    assert 'font = "Moz Sans SC"' in dw.Drawing(size="A4", title="图名").title_block().source


def test_add_note_font_overrides_drawing_font(moz):
    drawing = dw.Drawing(size="A4", font="Liberation Sans", title="图名")
    drawing.add_note((10, 10), "技术要求", font="Moz Sans SC")
    source = drawing.build().source
    assert 'font = "Moz Sans SC"' in source
    assert 'font = "Liberation Sans"' in source        # 标题栏仍是图面字体
