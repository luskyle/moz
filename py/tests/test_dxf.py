"""DXF 图纸 → 参数化模型（P1）测试。

样例图纸由 ``scripts/make_dxf_samples.py`` 生成在 ``py/moz_data/drawings/``，手算的验收值：

- ``plate.dxf``：外轮廓 5600 mm²（120×40 + 40×20 凸台），4 个 r5 孔（π5² 每个）
- ``bracket.dxf``：外轮廓 4000-(4-π)·8² = 3945.06 mm²，腰形孔 30×10+π5² = 378.54 mm²
- ``messy.dxf``：板 2400 mm²，孔 π6²；脏处＝缺口 0.02、底/左边重复 3 段、SCRAP 层领结自交 1 处

面积对照一律用**测试里自己实现的鞋带公式**算（不调用被测模块的实现），圆弧离散的误差单独界定。
"""

import json
import math
from pathlib import Path

import pytest

pytest.importorskip("ezdxf", reason="需要 ezdxf 才能解析 DXF")
import moz_dxf  # noqa: E402

DRAWINGS = Path(__file__).resolve().parents[1] / "moz_data" / "drawings"


def shoelace(points):
    """独立实现的鞋带公式（与模块内部实现无关联）。"""
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def fixture(name):
    path = DRAWINGS / f"{name}.dxf"
    if not path.exists():
        pytest.skip(f"缺少样例图纸 {path}（跑 scripts/make_dxf_samples.py 生成）")
    return str(path)


# --- plate：异形轮廓 + 孔层 + 命名标注 ---


def test_plate_contours_and_roles(moz):
    drawing = moz_dxf.read_dxf(fixture("plate"))
    assert len(drawing.outlines) == 1
    assert len(drawing.holes) == 4
    assert not drawing.open_contours
    # 孔画在 HOLES 层，靠「显式孔层」归类；外轮廓在 OUTLINE 层
    assert {contour.layer for contour in drawing.holes} == {"HOLES"}
    assert drawing.outlines[0].layer == "OUTLINE"


def test_plate_outline_area_is_exact(moz):
    """全是直线段的轮廓，面积必须逐位对上（相对误差 0，不是"约等于"）。"""
    drawing = moz_dxf.read_dxf(fixture("plate"))
    assert shoelace(drawing.outlines[0].points) == pytest.approx(5600.0, rel=1e-12)


def test_plate_holes_are_discretized_circles(moz):
    """圆孔按弦高离散：与 πr² 的差就是离散误差，调小弦高容差应当更接近。"""
    drawing = moz_dxf.read_dxf(fixture("plate"))
    polygons = sum(shoelace(contour.points) for contour in drawing.holes)
    assert polygons == pytest.approx(4 * math.pi * 25, rel=2e-3)
    finer = moz_dxf.read_dxf(fixture("plate"), arc_chord_tolerance=0.002)
    finer_polygons = sum(shoelace(contour.points) for contour in finer.holes)
    assert abs(finer_polygons - 4 * math.pi * 25) < abs(polygons - 4 * math.pi * 25)


def test_plate_volume_matches_section_times_height(moz):
    """体积 = 截面 × 高；截面用测试自己算的鞋带值（外轮廓 - 孔）。"""
    drawing = moz_dxf.read_dxf(fixture("plate"))
    height = 5.0
    expected = (shoelace(drawing.outlines[0].points)
                - sum(shoelace(contour.points) for contour in drawing.holes)) * height
    part = drawing.extrude(height=height)
    assert part.measure.volume == pytest.approx(expected, rel=1e-6)


def test_plate_parameters_match_engine_dxf_dim(moz):
    """参数与引擎的 dxf_dim(file, name) 认的是同一列，必须对得上。"""
    path = fixture("plate")
    drawing = moz_dxf.read_dxf(path)
    assert drawing.parameters() == {"bodywidth": 120.0, "plateheight": 40.0}
    for name, value in drawing.parameters().items():
        engine = moz.number(f'dxf_dim(file = "{path}", name = "{name}")')
        assert engine == pytest.approx(value, rel=1e-12)


def test_plate_without_units_warns(moz):
    """R12 老图没有 $INSUNITS：按 mm 处理，但要留一条警告（不静默）。"""
    drawing = moz_dxf.read_dxf(fixture("plate"))
    assert "无单位信息" in drawing.units
    assert any("单位" in warning for warning in drawing.warnings)


def test_unit_scale_override(moz):
    """unit_scale 覆盖图纸单位：面积按平方换算。"""
    inches = moz_dxf.read_dxf(fixture("plate"), unit_scale=25.4)
    assert shoelace(inches.outlines[0].points) == pytest.approx(5600.0 * 25.4 ** 2, rel=1e-12)


# --- bracket：圆角（圆弧）+ bulge 腰形孔 + 中心线/虚线层 ---


def test_bracket_layer_roles_and_contours(moz):
    drawing = moz_dxf.read_dxf(fixture("bracket"))
    assert len(drawing.outlines) == 1 and len(drawing.holes) == 1
    assert drawing.roles["CENTER"] == "center"      # 中心线层
    assert drawing.roles["HIDDEN"] == "hidden"      # 虚线层
    assert drawing.roles["DIM"] == "dim"            # 标注层
    # 中心线/虚线/标注都不进几何
    assert {contour.layer for contour in drawing.contours} == {"OUTLINE"}
    assert drawing.layer_counts["CENTER"] == 2 and drawing.layer_counts["HIDDEN"] == 1


def test_bracket_rounded_outline_area(moz):
    """圆角轮廓：4 条直线 + 4 段 R8 圆弧，面积对 4000-(4-π)8²。"""
    drawing = moz_dxf.read_dxf(fixture("bracket"))
    assert shoelace(drawing.outlines[0].points) == pytest.approx(4000 - (4 - math.pi) * 64, rel=5e-4)


def test_bracket_slot_is_a_hole(moz):
    """腰形孔（LWPOLYLINE 的 bulge 半圆端）要能被展开并判成孔。"""
    drawing = moz_dxf.read_dxf(fixture("bracket"))
    slot = drawing.holes[0]
    assert shoelace(slot.points) == pytest.approx(30 * 10 + math.pi * 25, rel=2e-3)
    assert slot.role == "hole" and slot.depth == 1


def test_bracket_volume_and_height_parameter(moz):
    """同一个图纸换高度重生成：体积随高度线性变。"""
    drawing = moz_dxf.read_dxf(fixture("bracket"))
    low = drawing.extrude(height=6.0).measure.volume
    high = drawing.extrude(height=12.0).measure.volume
    assert high == pytest.approx(low * 2, rel=1e-9)


# --- messy：脏图修复 + 确定性 ---


def test_messy_reports_repairs(moz):
    drawing = moz_dxf.read_dxf(fixture("messy"))
    assert drawing.repairs.get("duplicate", 0) >= 3      # 底边/左边的重复段（含反向）
    assert drawing.repairs.get("bridge", 0) == 1         # 顶边 0.02 mm 缺口
    assert len(drawing.outlines) == 1 and len(drawing.holes) == 1
    assert not drawing.open_contours


def test_messy_area_after_repair(moz):
    """修复后就是一张干净的 60×40 板（缺口 0.02 在桥接容差内，面积不受影响）。"""
    drawing = moz_dxf.read_dxf(fixture("messy"))
    assert shoelace(drawing.outlines[0].points) == pytest.approx(2400.0, rel=1e-12)


def test_messy_is_deterministic(moz):
    first = moz_dxf.read_dxf(fixture("messy")).extrude(height=4.0).measure
    second = moz_dxf.read_dxf(fixture("messy")).extrude(height=4.0).measure
    assert (first.volume, first.facets) == (second.volume, second.facets)


def test_messy_self_intersection_is_diagnosed(moz):
    """构造线层默认按角色排除；显式把它当轮廓读进来时，领结必须出现在诊断报告里。"""
    drawing = moz_dxf.read_dxf(fixture("messy"), layers=("OUTLINE", "CONSTRUCTION"))
    assert drawing.repairs.get("self_intersection", 0) >= 1
    assert "自交" in drawing.report()


def test_open_contour_is_reported_not_silently_dropped(moz, tmp_path):
    """一条画不完的折线：要报"开口链"，而不是悄悄变成闭合轮廓。"""
    import ezdxf

    doc = ezdxf.new("R2000", setup=False)
    msp = doc.modelspace()
    doc.layers.add("OUTLINE", color=7)
    for start, end in [((0, 0), (10, 0)), ((10, 0), (10, 10))]:      # 缺第三段
        msp.add_line(start, end, dxfattribs={"layer": "OUTLINE"})
    path = tmp_path / "open.dxf"
    doc.saveas(path)

    drawing = moz_dxf.read_dxf(str(path))
    assert drawing.repairs.get("open_chain", 0) == 1
    assert len(drawing.open_contours) == 1
    with pytest.raises(moz.OpenSCADError):
        drawing.extrude(height=1.0)                # 没有闭合轮廓 → 明确报错


# --- 便捷入口与报告 ---


def test_module_level_helpers(moz):
    path = fixture("plate")
    assert moz_dxf.parameters(path)["bodywidth"] == 120.0
    assert "轮廓" in moz_dxf.report(path)
    part = moz_dxf.extrude(path, 3.0, layers=("OUTLINE",))
    assert part.measure.volume == pytest.approx(5600.0 * 3.0, rel=1e-6)   # 只要外轮廓


def test_report_mentions_every_section(moz):
    text = moz_dxf.read_dxf(fixture("bracket")).report()
    for keyword in ("图纸", "版本", "图层", "实体", "轮廓", "截面", "修复", "标注"):
        assert keyword in text


def test_write_parameters_round_trip(moz, tmp_path):
    drawing = moz_dxf.read_dxf(fixture("plate"))
    target = tmp_path / "parameters.json"
    drawing.write_parameters(str(target))
    assert json.loads(target.read_text(encoding="utf-8")) == {"bodywidth": 120.0, "plateheight": 40.0}


def test_missing_file_raises(moz, tmp_path):
    with pytest.raises(moz.OpenSCADError):
        moz_dxf.read_dxf(str(tmp_path / "nope.dxf"))


def test_samples_are_shipped_in_the_package(moz):
    """样例图纸要能通过随包数据的路径取到（打包不变式）。"""
    for name in ("plate", "bracket", "messy"):
        assert Path(moz.data_path("drawings", f"{name}.dxf")).is_file()
