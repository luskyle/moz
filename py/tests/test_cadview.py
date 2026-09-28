"""`py/moz_cadview.py` 的用例：直画看图器（离散口径、块展开、图层/颜色、导出、兜底读取）。

全部**无显示器**跑：用 Qt 的 offscreen 平台，导出的 PNG/SVG 落在 tmp_path。
PySide6 缺失时整个模块 skip。
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = ROOT / "py" / "moz_data" / "drawings"
CORPUS = ROOT / "corpus" / "dxf"
DWGS = ROOT / "corpus" / "dwg"
LIBDXFRW = ROOT / "3rd" / "librecad" / "libraries" / "libdxfrw"


@pytest.fixture(scope="module")
def cadview():
    module = pytest.importorskip("moz_cadview")
    cadio = pytest.importorskip("moz_cadio")
    try:
        cadio.read(str(DRAWINGS / "plate.dxf"))
    except cadio.CadIoError as exc:
        pytest.skip(f"libmozcadio.so 不可用：{str(exc)[:120]}")
    return module


@pytest.fixture(scope="module")
def qt_app():
    widgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtSvg")
    application = widgets.QApplication.instance() or widgets.QApplication([__name__])
    return application


def scene_of(cadview, path):
    cad = cadview.load(str(path))
    scene, per_layer, counts, missing = cadview.build_scene(cad)
    return cad, scene, per_layer, counts, missing


# --- 离散口径（几何正确性） ---


def test_bulge_semicircle_math(cadview):
    """bulge=1 是半圆：从 (0,0) 到 (10,0) 应当过 (5,-5)（正 bulge = 逆时针）。"""
    points = cadview.moz_cadio.bulge_arc_points((0.0, 0.0), (10.0, 0.0), 1.0)
    assert len(points) == 33
    middle = points[len(points) // 2]
    assert middle[0] == pytest.approx(5.0, abs=1e-9)
    assert middle[1] == pytest.approx(-5.0, abs=1e-9)
    assert points[0][0] == pytest.approx(0.0, abs=1e-12)
    assert points[0][1] == pytest.approx(0.0, abs=1e-12)
    assert points[-1][0] == pytest.approx(10.0, abs=1e-12)
    assert points[-1][1] == pytest.approx(0.0, abs=1e-12)


def test_arc_tessellation_hits_chord_tolerance(cadview):
    """弧的段数由弦高容差反算：段数越多，误差越小。"""
    cadio = cadview.moz_cadio
    cad = cadio.read(str(DRAWINGS / "bracket.dxf"))
    arc = cad.by_kind("ARC")[0]
    coarse = cadio.entity_polylines(arc, chord_tolerance=0.5)[0]
    fine = cadio.entity_polylines(arc, chord_tolerance=0.001)[0]
    assert len(fine) > len(coarse)
    for chain in (coarse, fine):
        for x, y in chain:
            radius = ((x - arc.p1[0]) ** 2 + (y - arc.p1[1]) ** 2) ** 0.5
            assert radius == pytest.approx(arc.radius, rel=1e-9)


def test_spline_is_evaluated_inside_control_hull(cadview):
    """样条要按 NURBS 求值（不是控制多边形），且求出来的点落在控制点的凸包内。"""
    cadio = cadview.moz_cadio
    cad = cadio.read(str(CORPUS / "three-dxf" / "sample__data__demo.dxf"))
    splines = cad.by_kind("SPLINE")
    if not splines:
        pytest.skip("语料缺失 SPLINE")
    spline = splines[0]
    points = cadio.spline_points(spline)
    control = [(spline.points[2 * i], spline.points[2 * i + 1])
               for i in range(len(spline.points) // 2)]
    assert len(points) >= len(control)
    low_x = min(p[0] for p in control)
    high_x = max(p[0] for p in control)
    low_y = min(p[1] for p in control)
    high_y = max(p[1] for p in control)
    for x, y in points:
        assert low_x - 1e-6 <= x <= high_x + 1e-6
        assert low_y - 1e-6 <= y <= high_y + 1e-6


def test_polyline_bulge_becomes_curve(cadview):
    """腰形孔的半圆端（bulge）要展开成曲线，而不是直线段。"""
    cadio = cadview.moz_cadio
    cad = cadio.read(str(DRAWINGS / "bracket.dxf"))
    slot = cad.by_kind("LWPOLYLINE")[0]
    chain = cadio.entity_polylines(slot)[0]
    assert len(chain) > 8                       # 4 个顶点 + 两段半圆
    assert max(point[1] for point in chain) == pytest.approx(30.0, abs=1e-6)
    assert min(point[1] for point in chain) == pytest.approx(20.0, abs=1e-6)


# --- 颜色与线型 ---


def test_aci_table(cadview):
    table = cadview.AciTable(background_dark=True)
    assert table.rgb(1) == (255, 0, 0)
    assert table.rgb(7) == (255, 255, 255)
    assert cadview.AciTable(background_dark=False).rgb(7) == (0, 0, 0)
    grey = table.rgb(253)
    assert grey[0] == grey[1] == grey[2]
    for index in range(10, 250):
        red, green, blue = table.rgb(index)
        assert all(0 <= value <= 255 for value in (red, green, blue))


def test_by_layer_colour_follows_the_layer(cadview):
    """实体是 BYLAYER 时颜色要跟着图层走。"""
    cadio = cadview.moz_cadio
    entity = cadio.Entity(kind="LINE", layer="HIDDEN", aci=cadio.BYLAYER)
    layer = cadio.Layer(name="HIDDEN", aci=8)
    assert cadview.resolve_colour(entity, layer, cadview.AciTable()) == (128, 128, 128)
    entity.color24 = 0x00FF00
    assert cadview.resolve_colour(entity, layer, cadview.AciTable()) == (0, 255, 0)


def test_linetype_patterns(cadview):
    assert cadview.linetype_pattern("CONTINUOUS") is None
    assert cadview.linetype_pattern(None) is None
    assert cadview.linetype_pattern("CENTER") is not None
    assert cadview.linetype_pattern("不认识的线型") is None


# --- 场景装配 ---


def test_scene_counts_for_our_fixture(cadview, qt_app):
    _cad, _scene, per_layer, counts, _missing = scene_of(cadview, DRAWINGS / "bracket.dxf")
    assert counts == {"LINE": 11, "ARC": 4, "POINT": 3, "SOLID": 2, "LWPOLYLINE": 1, "MTEXT": 1}
    assert set(per_layer) >= {"OUTLINE", "CENTER", "HIDDEN", "DIM"}


def test_dimension_geometry_comes_from_its_block(cadview, qt_app):
    """标注画的是它的匿名块内容（线/箭头/文字），所以 LINE/SOLID 的计数比模型空间多。"""
    cad, _scene, _per_layer, counts, _missing = scene_of(cadview, DRAWINGS / "plate.dxf")
    model_lines = len([e for e in cad.entities if e.kind == "LINE" and e.owner == ""])
    assert len(cad.by_kind("DIMENSION")) == 2
    assert counts["LINE"] > model_lines
    assert counts.get("TEXT", 0) >= 2                      # 标注文字（bodywidth/plateheight）


def test_insert_is_expanded(cadview, qt_app):
    cadio = cadview.moz_cadio
    cad = cadio.read(str(DRAWINGS / "bracket.dxf"))
    assert cad.by_kind("INSERT")                            # 样例里有块参照
    drawn = list(cadio.iter_draw(cad))
    assert len(drawn) > len([e for e in cad.entities if e.owner == ""])


def test_degenerate_entities_do_not_crash(cadview, qt_app):
    """缺点的实体（空多段线、没有边界的剖面线）不能把渲染带崩。"""
    import moz_cadio as cadio
    cad = cadio.CadFile(path="synthetic.dxf")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="SOLID", layer="0"))          # 一个点都没有
    cad.entities.append(cadio.Entity(kind="HATCH", layer="0"))          # 没有环
    cad.entities.append(cadio.Entity(kind="LWPOLYLINE", layer="0"))     # 没有顶点
    cad.entities.append(cadio.Entity(kind="RAY", layer="0", p1=(0, 0, 0), p2=(0, 0, 0)))
    _scene, _per_layer, counts, _missing = cadview.build_scene(cad)[:4]
    assert counts == {}


def test_big_corpus_file_is_fast(cadview, qt_app):
    """2.7 MB 的整图也要秒级画出来（N2 的验收项之一）。"""
    import time
    path = CORPUS / "dxf-parser" / "samples__data__api-cw750-details.dxf"
    if not path.exists():
        pytest.skip("大图语料缺失")
    started = time.time()
    _cad, _scene, per_layer, counts, _missing = scene_of(cadview, path)
    elapsed = time.time() - started
    assert sum(len(items) for items in per_layer.values()) > 1000
    assert elapsed < 10.0, f"画了 {elapsed:.2f} 秒，太慢"


def test_dwg_block_expansion_reports_missing_blocks(cadview, qt_app):
    """DWG 的匿名块名会被上游截断（实测 `*U19` → `*U`），于是查不到块定义——

    这时要**报出来**（`missing`），不能静默画空。
    """
    path = DWGS / "acadsharp" / "samples__dynamic-blocks__BLOCKVISIBILITYPARAMETER.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    _cad, _scene, _per_layer, _counts, missing = scene_of(cadview, path)
    assert missing and all(name.startswith("*") for name in missing)


def test_dwg_scene_has_curves_and_hatches(cadview, qt_app):
    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    _cad, _scene, _per_layer, counts, _missing = scene_of(cadview, path)
    assert sum(counts.values()) > 100
    assert {"LINE", "HATCH", "SPLINE", "CIRCLE"} <= set(counts)


# --- 兜底读取 ---


def test_ezdxf_fallback_for_files_libdxfrw_cannot_read(cadview, qt_app):
    """libdxfrw 读不了的 DXF（对象段啃不动的二进制样本）要能靠 ezdxf 兜底看上。"""
    pytest.importorskip("ezdxf")
    path = LIBDXFRW / "screw2012binary.dxf"
    cad = cadview.load(str(path))
    assert any("ezdxf 兜底" in warning for warning in cad.warnings)
    assert sum(1 for _ in cadview.moz_cadio.iter_draw(cad)) > 0


def test_libdxfrw_stays_primary(cadview, qt_app):
    """能读的图不会去走 ezdxf（主路径仍是 libdxfrw）。"""
    cad = cadview.load(str(DRAWINGS / "plate.dxf"))
    assert cad.format == "dxf"
    assert not any("兜底" in warning for warning in cad.warnings)


# --- 导出与命令行 ---


def test_export_png_and_svg(cadview, qt_app, tmp_path):
    png = tmp_path / "out.png"
    svg = tmp_path / "out.svg"
    counts, missing = cadview.export(cadview.load(str(DRAWINGS / "bracket.dxf")), str(png),
                                    width=800, height=600, dark=False)
    assert counts and not missing
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 5000

    cadview.export(cadview.load(str(DRAWINGS / "plate.dxf")), str(svg), width=800, height=600)
    text = svg.read_text(encoding="utf-8")
    assert "<svg" in text and text.count("<path") >= 5


def test_cli_report_and_layers(cadview, capsys):
    assert cadview.main([str(DRAWINGS / "bracket.dxf"), "--report"]) == 0
    out = capsys.readouterr().out
    assert "格式：dxf" in out and "图元：" in out

    assert cadview.main([str(DRAWINGS / "bracket.dxf"), "--layers"]) == 0
    out = capsys.readouterr().out
    assert "OUTLINE" in out and "CENTER" in out


def test_cli_missing_file(cadview, capsys, tmp_path):
    assert cadview.main([str(tmp_path / "nope.dxf"), "--report"]) == 2
    assert "读不了" in capsys.readouterr().err
