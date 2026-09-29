"""`py/moz_cadview.py` 的用例：直画看图器（离散口径、块展开、图层/颜色、导出、兜底读取）。

全部**无显示器**跑：用 Qt 的 offscreen 平台，导出的 PNG/SVG 落在 tmp_path。
PySide6 缺失时整个模块 skip。
"""

import os
import shutil
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
    scene, per_layer, counts, missing, notes = cadview.build_scene(cad)
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


# --- model_as_json（VS Code 插件的可交互 JSON 通路，纯 Python、不碰 Qt） ---


def test_model_as_json_uses_same_geometry_and_colour(cadview):
    """`--model-json`：可交互 JSON 与 Qt 看图器共用同一套几何/颜色口径。

    图元带算好的 #rrggbb 颜色、可选 points/closed/text/pos/h/rot；layers 是出现顺序；
    模块层不 import PySide6（纯函数，直接调得起）。
    """
    import moz_cadview

    header = open(moz_cadview.__file__, encoding="utf-8").read().split("def ")[0]
    assert "PySide6" not in header, "模块层不得 import PySide6（--model-json 是纯 Python 通路）"
    model = cadview.model_as_json(cadview.load(str(DRAWINGS / "plate.dxf")))
    assert model["format"] == "dxf"
    assert model["layers"] and model["items"]
    assert model["layers"] == list(dict.fromkeys(it["layer"] for it in model["items"]))
    for item in model["items"]:
        assert item["color"].startswith("#") and len(item["color"]) == 7
        assert (item.get("points") is not None) or (item.get("text") is not None)
    line = next(item for item in model["items"] if item["kind"] == "LINE")
    assert len(line["points"]) >= 4            # 至少一条线段（x0,y0,x1,y1）
    texts = [item for item in model["items"] if item.get("text")]
    assert texts, "plate.dxf 有标注文字（bodywidth/plateheight）"
    for text in texts:
        assert len(text["pos"]) == 2 and text["h"] > 0
        assert isinstance(text["rot"], int | float)


def test_model_as_json_line_colour_follows_layer(cadview):
    """浅色模型：BYLAYER 的 7 号色实体 = 黑线 #000000（Webview 浅底上可见）。"""
    model = cadview.model_as_json(cadview.load(str(DRAWINGS / "bracket.dxf")))
    by_layer = [item for item in model["items"]
                if item["kind"] in ("LINE", "ARC") and item["layer"] == "OUTLINE"]
    assert by_layer and all(item["color"] == "#000000" for item in by_layer)
    assert any(item["color"] != "#000000" for item in model["items"])   # 别的层有颜色


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


def test_dwg_block_expansion_resolves_truncated_names(cadview, qt_app):
    """DWG 的匿名块名在上游那里会被截断（实测 `*U19` → `*U`、`*T9` → `*T`）——

    截断名查不到块定义。读完整张图后按「块记录句柄 → 块实体名」补回真名，于是这些块
    参照全都画得出来、`missing` 是空的（修复前这张图全是 `*U`/`*T` 找不到块定义）。
    """
    path = DWGS / "acadsharp" / "samples__dynamic-blocks__BLOCKVISIBILITYPARAMETER.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    cad, _scene, _per_layer, counts, missing = scene_of(cadview, path)
    assert not missing
    assert sum(counts.values()) > 10
    names = {entity.name for entity in cad.entities if entity.kind == "INSERT"}
    definitions = {block.name for block in cad.blocks}
    assert names <= definitions, f"块参照仍指向不存在的块：{names - definitions}"
    assert not [name for name in names if len(name or "") == 2 and name[0] == "*"]


def test_dwg_scene_has_curves_and_hatches(cadview, qt_app):
    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    _cad, _scene, _per_layer, counts, _missing = scene_of(cadview, path)
    assert sum(counts.values()) > 100
    assert {"LINE", "HATCH", "SPLINE", "CIRCLE"} <= set(counts)


def test_dwg_entity_families_reach_the_scene(cadview, qt_app):
    """整族实体以前在面板里是"忽略 N 个…"，现在是**画出来的东西**（且不再有告警）。

    计数按图元算：3 个多线展开成 6 条平行线，但面板里记 MLINE 3。
    """
    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    cad, scene, _per_layer, counts, missing = scene_of(cadview, path)
    assert not missing and not cad.warnings, (missing, cad.warnings)
    assert {"MESH", "MLINE", "MLEADER", "WIPEOUT", "UNDERLAY", "SHAPE", "IMAGE"} <= set(counts)
    assert counts["MLINE"] == 3 and counts["MESH"] == 2
    assert counts["MLEADER"] == 15
    assert len(scene.items()) > 200


def test_only_mleader_drawing_is_no_longer_blank(cadview, qt_app):
    """语料里那张只有 MLEADER 的图以前判成"空白"（`drawable_count` 为 0），现在画得出来。"""
    path = CORPUS / "dxf-parser" / "test__data__mleader.dxf"
    if not path.exists():
        pytest.skip("DXF 语料缺失")
    cad = cadview.load(str(path))
    assert cadview.drawable_count(cad) > 0
    _scene, _per_layer, counts, missing, notes = cadview.build_scene(cad)
    assert counts.get("MLEADER", 0) >= 1 and not missing
    assert not notes                                             # 多重引线是完整几何，不需要说明
    texts = [item.text() for item in _scene.items() if hasattr(item, "text")]
    assert texts


def test_fit_ignores_infinite_lines(cadview, qt_app, tmp_path):
    """适应视角/导出的取景要**排除 RAY/XLINE**——它们是按图纸尺度放大 20 倍画出来的。

    不排除的话，场景框会被两组构造线撑成几万单位、真实几何被压成几个像素，用户看到的就是
    一张白纸（实测 `samples__sample_AC1015.dwg`：场景框 204634×161647，真实几何几百单位）。
    """
    dxf = tmp_path / "ray.dxf"
    dxf.write_text(
        "0\nSECTION\n2\nENTITIES\n"
        "0\nLINE\n8\n0\n10\n0\n20\n0\n30\n0\n11\n100.\n21\n0.\n31\n0.\n"
        "0\nLINE\n8\n0\n10\n0\n20\n0\n30\n0\n11\n0.\n21\n100.\n31\n0.\n"
        "0\nRAY\n8\n0\n10\n50.\n20\n0.\n30\n0.\n11\n1.\n21\n0.\n31\n0.\n"
        "0\nENDSEC\n0\nEOF\n",
        encoding="utf-8")
    cad = cadview.load(str(dxf))
    scene, _per_layer, _counts, _missing, _notes = cadview.build_scene(cad)
    drawable = cadview.view_extent(scene)
    full = scene.itemsBoundingRect()
    assert full.width() > 1000                        # 场景框确实被 RAY 撑大了（放大 20 倍）
    assert drawable.width() < 300 and drawable.height() < 300     # 取景只剩有限几何

    out = tmp_path / "out.png"
    cadview.export(cad, str(out), width=400, height=300, dark=False)
    from PySide6.QtGui import QImage

    image = QImage(str(out))
    assert (image.width(), image.height()) == (400, 300)
    ink = sum(1 for x in range(0, 400, 2) for y in range(0, 300, 2)
              if (image.pixel(x, y) & 0xFFFFFF) != 0xFFFFFF)
    assert ink >= 100, f"图线被压成碎点：只有 {ink} 个墨迹像素"


def test_dwg_fit_is_not_blown_up_by_rays(cadview, qt_app):
    """真实 DWG：适应视角的范围必须落在图纸内容上（含 RAY/XLINE 的样本以前整张空白）。"""
    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    cad = cadview.load(str(path))
    scene, _per_layer, counts, _missing, _notes = cadview.build_scene(cad)
    assert counts.get("RAY", 0) >= 1 and counts.get("XLINE", 0) >= 1
    assert scene.itemsBoundingRect().width() > 10000          # 场景框含无限长线
    drawable = cadview.view_extent(scene)
    assert drawable.width() < 10000 and drawable.width() > 100
    assert drawable.height() > 100


def test_images_show_pixels_or_generated_placeholders(qt_app, tmp_path):
    """IMAGE：找到图片文件就**真的载入像素**（画在外框里），找不到就**造一张占位图**。

    `examples_dxf__image__images.dxf` 引用的 image1..4 图已补进语料（MIT）——image4.jpg
    上游 ezdxf 自己都没放（树里查不到），所以：63 张真像素 + 1 张占位图，说明只提 image4；
    把图抽走/换成临时的验证文件，能同时钉住"全缺 → 全占位"和"补齐 → 真像素、无说明"。
    """
    import shutil

    import moz_cadview as cadview
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QGraphicsPixmapItem

    src = CORPUS / "ezdxf" / "examples_dxf__image__images.dxf"
    if not src.exists():
        pytest.skip("DXF 语料缺失")

    def pixmap_items(scene):
        return [item for item in scene.items() if isinstance(item, QGraphicsPixmapItem)]

    def distinct_colors(item):
        image = item.pixmap().toImage()
        colors = set()
        for x in range(0, image.width(), 7):
            for y in range(0, image.height(), 7):
                colors.add(image.pixel(x, y) & 0xFFFFFF)
        return len(colors)

    # ① 语料现在带了真图：image1/2/3 是真像素（照片、颜色多），image4 上游缺失 → 1 张占位图
    cad = cadview.load(str(src))
    scene, _per, counts, _missing, notes = cadview.build_scene(cad)
    assert counts.get("IMAGE", 0) >= 60
    items = pixmap_items(scene)
    assert len(items) >= 60
    assert any("占位图" in note and "image4.jpg" in note for note in notes), notes
    assert not any("image1.jpg" in note or "image2.png" in note or "image3.jpg" in note
                   for note in notes), notes
    color_counts = sorted(distinct_colors(item) for item in items)
    assert sum(1 for count in color_counts if count <= 60) == 1, "只有 image4 是占位图"
    assert sum(1 for count in color_counts if count > 60) >= 60, "其余都是真像素（照片）"

    # ② 把图抽走（拷到没有图的临时目录）：64 张占位图，尺寸 = 各自的外框
    dst = tmp_path / "images.dxf"
    shutil.copy(src, dst)
    cad = cadview.load(str(dst))
    scene, _per, counts, _missing, notes = cadview.build_scene(cad)
    items = pixmap_items(scene)
    assert len(items) >= 60
    assert all(0 < item.sceneBoundingRect().width() < 40 for item in items)
    assert any("占位图" in note for note in notes)

    # ③ 再补齐成可读的图：真像素、无占位说明（验证"找到文件就载入"）
    image = QImage(64, 48, QImage.Format_RGB32)
    image.fill(QColor(200, 30, 30))                       # 左红
    QPainter(image).fillRect(0, 0, 32, 48, QColor(30, 200, 30))   # 右绿
    for name, fmt in (("image1.jpg", "JPG"), ("image2.png", "PNG"),
                      ("image3.jpg", "JPG"), ("image4.jpg", "JPG")):
        assert image.save(str(tmp_path / name), fmt), f"Qt 的 {name} 编解码器没工作"

    cad = cadview.load(str(dst))
    scene, _per, counts, _missing, notes = cadview.build_scene(cad)
    items = pixmap_items(scene)
    assert len(items) >= 60
    assert not any("占位图" in note for note in notes), notes
    pixel = items[0].pixmap().toImage().pixel(0, 0)
    red, green = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF
    assert (red > 150 and green < 100) or (green > 150 and red < 100), \
        f"载入的是真图片像素（强红或强绿）：#{pixel & 0xFFFFFF:06x}"


def test_dwg_image_loads_real_pixels_from_the_corpus(qt_app):
    """ACadSharp 样本的 IMAGE 引用语料里的 image.JPG —— 显示真照片、占位图说明消失。"""
    import moz_cadview as cadview
    from PySide6.QtWidgets import QGraphicsPixmapItem

    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    scene, _per, _counts, _missing, notes = cadview.build_scene(cadview.load(str(path)))
    assert not any("IMAGE 用了占位图" in note for note in notes), notes
    pixmaps = [item for item in scene.items() if isinstance(item, QGraphicsPixmapItem)]
    assert pixmaps
    image = pixmaps[0].pixmap().toImage()
    colors = {image.pixel(x, y) & 0xFFFFFF
              for x in range(0, image.width(), 7) for y in range(0, image.height(), 7)}
    assert len(colors) > 100, f"载入的是真照片，不是占位图（颜色 {len(colors)} 种）"


def test_underlay_pdf_is_rendered_onto_the_page(qt_app, tmp_path):
    r"""UNDERLAY 引用的 PDF **第 1 页要真的渲染出来**（不再只是画边界/十字标记）。

    ACadSharp 样本引用 `..\pdf-definition.pdf`（语料里有）：渲染成一整张 A4 页面
    （595×842 pt × scale 1）放在插入点；文件缺失/打不开就落回"边界占位 + 说明"。
    """
    import shutil

    import moz_cadview as cadview
    from PySide6.QtWidgets import QGraphicsPixmapItem

    path = DWGS / "acadsharp" / "samples__sample_AC1021.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")

    # 有 PDF：渲染出页面像素，且没有"UNDERLAY 只画了占位"的说明
    scene, _per, counts, _missing, notes = cadview.build_scene(cadview.load(str(path)))
    assert counts.get("UNDERLAY", 0) >= 1
    assert not any("UNDERLAY 只画了占位" in note for note in notes), notes
    pixmaps = [item for item in scene.items() if isinstance(item, QGraphicsPixmapItem)]
    assert any(abs(item.sceneBoundingRect().width() - 595) < 1
               and abs(item.sceneBoundingRect().height() - 842) < 1
               for item in pixmaps), "PDF 页面应按 595×842(pt)×scale 画在外框里"

    # 没有 PDF（拷到临时目录）：落回占位说明 + 边界照样画
    dst = tmp_path / "sample_AC1021.dwg"
    shutil.copy(path, dst)
    scene, _per, counts, _missing, notes = cadview.build_scene(cadview.load(str(dst)))
    assert counts.get("UNDERLAY", 0) >= 1
    assert any("UNDERLAY 只画了占位" in note and "pdf-definition" in note for note in notes)


def test_pdf_page_is_not_upside_down(qt_app):
    """渲染的 PDF 页必须**正着**贴在外框里——PDF 像素 y 向下、图纸 y 向上。

    实测没处理时整页倒着、文字镜像。现在外框起点放在页面顶上、v 反掉：
    像素第 0 行（页面上边）对准世界"上"边；最后一行落在插入点（页面下边）。
    """
    import moz_cadview as cadview

    path = DWGS / "acadsharp" / "samples__sample_AC1021.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    cad = cadview.load(str(path))
    underlay, = cad.by_kind("UNDERLAY")
    pixmap, corners = cadview._underlay_pdf(underlay, str(path))
    assert pixmap is not None

    c0 = underlay.p1[:2]                       # scale=(1,1)、rotation=0、页面 595×842 pt
    assert corners[1] == (595.0, 0.0)          # u：宽沿 +x
    assert corners[2] == (0.0, -842.0)         # v：反掉 → 像素向下 = 世界向下
    assert corners[0] == (c0[0], c0[1] + 842.0)   # 起点在页面**顶上**（页面上边对准世界"上"边）
    # 用外框造出来的 item：最后一个像素行（页面下边）必须落在插入点 c0 上
    item = cadview._pixmap_item(pixmap, corners, cadview.moz_cadio.IDENTITY_MATRIX)
    bottom_edge = item.mapToScene(0, item.boundingRect().height())
    assert abs(bottom_edge.x() - c0[0]) < 1e-6 and abs(bottom_edge.y() - c0[1]) < 1e-6


def test_switching_drawings_does_not_jump_the_list(qt_app, tmp_path):
    """鼠标按顺序点图纸时，列表**不能跳**——可见项再换图不该滚动。

    以前选中即"居中滚动"，每点一张列表就跳一次，点中的是记忆里的位置 → 跳图。
    """
    import moz_cadview as cadview

    for index in range(30):
        shutil.copy(DRAWINGS / "plate.dxf", tmp_path / f"d{index:02d}.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "d00.dxf")), recursive=True)
    view.warn_on_error = False
    scrollbar = view.drawings.verticalScrollBar()
    before = scrollbar.value()                      # 第一张在顶部：值应为 0
    assert before == 0
    assert view.open_path(str(tmp_path / "d01.dxf")) is True
    assert scrollbar.value() == before, "第一行可见时换第二张不该滚动列表（不然点一个跳一个）"


def test_mouse_drag_pans_the_view(qt_app):
    """看图区**左键按住拖动 ≡ 内容跟手**（1:1，放大后也一样跟）。

    以前用 ``view.translate()``：在 AnchorUnderMouse 下会被 Qt 的锚点逻辑抵消——实测拖
    120px 视口只动 0.3px。现在按设备像素调滚动条：拖多少、内容走多少。
    """
    import math

    import moz_cadview as cadview
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        path = DWGS / "libdxfrw" / "tests__fixtures__dwg__large_radial.dwg"
    view = cadview.CadView(cadview.load(str(path)))
    view.window.show()
    qt_app.processEvents()
    for _ in range(6):                                   # 放大，让滚动条有行程
        view.view.scale(1.3, 1.3)
    qt_app.processEvents()
    transform = view.view.viewportTransform()
    scale_px = math.hypot(transform.m11(), transform.m12())

    center = view.view.viewport().rect().center()
    hbar_before = view.view.horizontalScrollBar().value()
    vbar_before = view.view.verticalScrollBar().value()
    before = view.view.mapToScene(center)
    drag = QPoint(120, 80)
    QTest.mousePress(view.view.viewport(), Qt.LeftButton, pos=center)
    for x, y in ((30, 0), (60, 20), (120, 80)):          # 分段拖动（最后一个点 = 净位移）
        QTest.mouseMove(view.view.viewport(), center + QPoint(x, y))
        qt_app.processEvents()
    QTest.mouseRelease(view.view.viewport(), Qt.LeftButton, pos=center + drag)
    qt_app.processEvents()

    hbar_after = view.view.horizontalScrollBar().value()
    vbar_after = view.view.verticalScrollBar().value()
    assert hbar_before - hbar_after == 120 and vbar_before - vbar_after == 80, \
        f"滚动条位移应等于拖动像素：({hbar_before - hbar_after}, {vbar_before - vbar_after})"
    after = view.view.mapToScene(center)
    screen_shift = math.hypot((before.x() - after.x()) * scale_px,
                              (before.y() - after.y()) * scale_px)
    assert abs(screen_shift - math.hypot(drag.x(), drag.y())) < 30, \
        f"内容应 1:1 跟手：屏幕位移 {screen_shift:.0f}px（拖动 {math.hypot(*drag):.0f}px）"
    view.window.close()


def test_mtext_formatting_codes_are_not_displayed(qt_app, tmp_path):
    r"""MTEXT 的排版码（`\A1;`、`\C1;`、`\H`、`\f`…）不能原样画出来。

    实测 `qcad/support__data__tests__dimstyle__acad_archticks.dxf`：标注文字是 `\A1;30`
    （\A1; = 对齐指令），以前画面上直接显示 `\A1;30`。模型保持原文，显示层剥码。
    """
    import moz_cadview as cadview

    assert cadview.mtext_to_display("\\A1;30") == "30"                 # 对齐码
    assert cadview.mtext_to_display("a\\Pb\\Pc") == "a\nb\nc"          # 换行
    assert cadview.mtext_to_display("\\fSimSun;\\C1;\\H1.5x;你好") == "你好"
    assert cadview.mtext_to_display("\\S1^2;") == "1/2"                # 堆叠摊平
    assert cadview.mtext_to_display("\\U+03B1") == "α"                 # 字符转义
    assert cadview.mtext_to_display("普通文字") == "普通文字"
    assert cadview.mtext_to_display("\\x未知;") == "\\x未知;"          # 未知码保留

    path = CORPUS / "qcad" / "support__data__tests__dimstyle__acad_archticks.dxf"
    if not path.exists():
        pytest.skip("DXF 语料缺失")
    scene, _per, _counts, _missing, _notes = cadview.build_scene(cadview.load(str(path)))
    texts = [item.text() for item in scene.items() if hasattr(item, "text")]
    assert "30" in texts and not any("\\A1" in tag for tag in texts)


def test_window_actually_paints_the_drawing(qt_app, tmp_path):
    """窗口的绘图区要**真的有内容**（不是面板里有数字、画布上一片白）。

    两个样本都踩过：①取景被无限长线撑爆；②更隐蔽的——QGraphicsView 默认白背景，
    而图纸颜色按 dark 调色板配（浅色线），浅线画在白底上=看不见。这里 grab 视口数墨迹。
    """
    import moz_cadview as cadview

    paths = [DWGS / "libdxfrw" / "tests__fixtures__dwg__large_radial.dwg",
             DWGS / "acadsharp" / "samples__sample_AC1015.dwg"]
    canvas = [p for p in paths if p.exists()][:1] or paths
    for path in canvas:
        view = cadview.CadView(cadview.load(str(path)))       # dark=True 默认
        view.window.show()
        qt_app.processEvents()
        brush = view.view.backgroundBrush().color()
        assert brush.name() == "#1e1e1e", "背景必须跟 dark 调色板一致"
        image = view.view.viewport().grab().toImage()
        background = image.pixel(2, 2) & 0xFFFFFF
        total = ink = 0
        for x in range(0, image.width(), 2):
            for y in range(0, image.height(), 2):
                total += 1
                if abs((image.pixel(x, y) & 0xFFFFFF) - background) > 0x101010:
                    ink += 1
        assert ink / total >= 0.001, f"{path.name}：画布是空的（墨迹 {ink}/{total}）"
        view.window.close()

    light = cadview.CadView(cadview.load(str(paths[0])), dark=False) if paths[0].exists() else None
    if light is not None:
        assert light.view.backgroundBrush().color().name() == "#ffffff"
        light.window.close()


# --- 目录与"方便打开"（图纸列表、点击切换、拖拽、demo） ---


def test_list_drawings_recursive_and_flat(cadview, tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("a.dxf", "b.DWG", "note.txt"):
        (tmp_path / name).write_text("0\nEOF\n", encoding="utf-8")
    (tmp_path / "sub" / "c.dxf").write_text("0\nEOF\n", encoding="utf-8")

    flat = cadview.list_drawings(str(tmp_path))
    assert [Path(p).name for p in flat] == ["a.dxf", "b.DWG"]          # 不递归、认大小写后缀
    deep = cadview.list_drawings(str(tmp_path), recursive=True)
    assert [Path(p).name for p in deep] == ["a.dxf", "b.DWG", "c.dxf"]
    assert cadview.list_drawings(str(tmp_path), limit=2, recursive=True)  # 有上限
    assert cadview.list_drawings(str(tmp_path / "empty-missing")) == []


def test_view_lists_directory_and_switches_by_click(cadview, qt_app, tmp_path):
    """打开一张图后，「图纸」面板（目录树）列出同目录的图纸，点一下就换图。"""
    for source in ("plate", "bracket", "messy"):
        shutil.copy(DRAWINGS / f"{source}.dxf", tmp_path / f"{source}.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "plate.dxf")))
    view.warn_on_error = False                     # 失败时别弹模态框（测试里会挂）
    assert cadview.tree_file_count(view.drawings) == 3
    root = view.drawings.topLevelItem(0)
    assert root.text(0) == tmp_path.name           # 根节点 = 扫描目录名
    labels = [root.child(i).text(0) for i in range(root.childCount())]
    assert labels == ["bracket.dxf", "messy.dxf", "plate.dxf"]   # 叶子显示短文件名

    chosen = root.child(0)                         # 点第一个
    view._on_drawing_clicked(chosen)
    assert Path(view.cad.path).name == "bracket.dxf"
    assert view.drawings.currentItem().text(0) == "bracket.dxf"


def test_drawings_tree_and_keyboard_switching(cadview, qt_app, tmp_path):
    """图纸列表是**目录树**，↑/↓ 键盘能切换图纸（目录节点跳过、只换图不重开）。"""
    import os

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    (tmp_path / "sub").mkdir()
    shutil.copy(DRAWINGS / "plate.dxf", tmp_path / "a.dxf")
    shutil.copy(DRAWINGS / "messy.dxf", tmp_path / "b.dxf")
    shutil.copy(DRAWINGS / "bracket.dxf", tmp_path / "sub" / "c.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "a.dxf")), recursive=True)
    view.warn_on_error = False
    root = view.drawings.topLevelItem(0)
    assert root.childCount() == 3                  # a、b 两个文件 + "sub" 目录节点
    sub = next(root.child(i) for i in range(root.childCount())
               if root.child(i).text(0) == "sub")
    assert sub.childCount() == 1                   # c 在子目录节点下
    assert cadview.tree_file_count(view.drawings) == 3
    current = os.path.abspath(view.drawings.currentItem().data(0, Qt.UserRole))
    assert current == os.path.abspath(str(tmp_path / "a.dxf"))

    view.drawings.setFocus()
    QTest.keyClick(view.drawings, Qt.Key_Down)     # ↑/↓ 在树里移动当前项 → currentItemChanged
    assert Path(view.cad.path).name == "b.dxf"
    QTest.keyClick(view.drawings, Qt.Key_Down)     # 经过"sub"目录节点不换图，落到 c
    assert Path(view.cad.path).name == "c.dxf"
    QTest.keyClick(view.drawings, Qt.Key_Up)       # 再往上：经过目录节点回到 b
    assert Path(view.cad.path).name == "b.dxf"


def test_view_open_directory_lists_all(cadview, qt_app, tmp_path):
    """打开目录：连子目录一起列出来，并自动看第一张。"""
    (tmp_path / "nested").mkdir()
    shutil.copy(DRAWINGS / "plate.dxf", tmp_path / "one.dxf")
    shutil.copy(DRAWINGS / "bracket.dxf", tmp_path / "nested" / "two.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "one.dxf")))
    view.warn_on_error = False
    assert view.open_directory(str(tmp_path)) is True
    assert cadview.tree_file_count(view.drawings) == 2
    assert Path(view.cad.path).name == "one.dxf"    # 已经在目录里就不换当前这张
    assert Path(view.directory) == tmp_path
    view.open_any(str(tmp_path / "nested"))         # open_any 也认目录
    assert Path(view.cad.path).name == "two.dxf"


def test_open_path_failure_keeps_current_view(cadview, qt_app, tmp_path):
    view = cadview.CadView(cadview.load(str(DRAWINGS / "bracket.dxf")))
    view.warn_on_error = False
    before = view.counts
    assert view.open_path(str(tmp_path / "nope.dxf")) is False
    assert view.counts == before                    # 当前视图没被动过
    assert "打不开" in view.window.statusBar().currentMessage()


def test_unnamed_block_reference_is_reported(cadview, qt_app):
    """块名本身就是空的参照（实测有些 DWG 的标注这样）也要报出来，不能静默不画。"""
    import moz_cadio as cadio
    cad = cadio.CadFile(path="synthetic.dxf")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="INSERT", layer="0"))
    cad.entities.append(cadio.Entity(kind="DIMENSION", layer="0"))
    missing = []
    assert list(cadio.iter_draw(cad, missing=missing)) == []
    assert "(无名块参照)" in missing and "(无名标注块)" in missing


def test_dropped_path_accepts_drawings_and_directories(cadview, qt_app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl

    class FakeEvent:                                # 只用到 mimeData().urls()
        def __init__(self, paths):
            self._data = QMimeData()
            self._data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])

        def mimeData(self):
            return self._data

    drawing = tmp_path / "a.dxf"
    drawing.write_text("0\nEOF\n", encoding="utf-8")
    other = tmp_path / "readme.txt"
    other.write_text("hi", encoding="utf-8")

    assert cadview._dropped_path(FakeEvent([drawing])) == str(drawing)
    assert cadview._dropped_path(FakeEvent([tmp_path])) == str(tmp_path)
    assert cadview._dropped_path(FakeEvent([other])) is None


def test_demo_startup_dialog_has_file_and_directory_buttons(cadview, qt_app, monkeypatch):
    """启动弹窗就是**两个按钮**：选择文件 / 选择目录（外加取消），点谁就走哪条路。"""
    demo = pytest.importorskip("cadview_demo")
    from PySide6.QtWidgets import QMessageBox

    seen = {}

    def fake_exec(self):                            # 不真弹窗
        seen["labels"] = [button.text() for button in self.buttons()]
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    def clicking(label):
        def clicked(self):
            return next(button for button in self.buttons() if button.text().startswith(label))
        return clicked

    monkeypatch.setattr(QMessageBox, "clickedButton", clicking("选择文件"))
    assert demo.ask_choice() == "file"
    monkeypatch.setattr(QMessageBox, "clickedButton", clicking("选择目录"))
    assert demo.ask_choice() == "directory"

    assert seen["labels"] == ["选择文件…", "选择目录…", "取消"]


def test_demo_start_dir_is_the_project_root(cadview):
    """对话框默认目录 = 本项目所在路径（这里就是仓库根）。"""
    demo = pytest.importorskip("cadview_demo")
    assert Path(demo.project_root()) == ROOT
    assert Path(demo.start_dir()) == ROOT


def test_demo_start_dir_falls_back_to_samples(cadview, monkeypatch):
    """不在仓库里（装成 wheel）时按"样例目录 → 当前目录"退，而不是给个空地方。"""
    demo = pytest.importorskip("cadview_demo")
    monkeypatch.setattr(demo.moz_cadview, "__file__", "/tmp/nowhere/cadview/moz_cadview.py")
    assert demo.project_root() is None
    assert Path(demo.start_dir()) == Path.cwd()        # 样例目录也不存在 → 退回当前目录
    monkeypatch.setattr(demo, "sample_dir", lambda: str(DRAWINGS))
    assert Path(demo.start_dir()) == DRAWINGS          # 样例目录在 → 用它


def test_drawing_list_reports_truncation(cadview, qt_app, tmp_path):
    """撞上列表上限要说明（项目根这种目录里图纸上千张，不能假装只有这些）。"""
    for index in range(3):
        shutil.copy(DRAWINGS / "plate.dxf", tmp_path / f"copy{index}.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "copy0.dxf")), recursive=True)
    view.warn_on_error = False
    view.open_directory(str(tmp_path))
    assert cadview.tree_file_count(view.drawings) == 3       # 没撞上限：正常
    view.set_directory(str(tmp_path), recursive=True, limit=2)
    assert cadview.tree_file_count(view.drawings) == 2
    assert "只列了前 2 张" in view.window.statusBar().currentMessage()


def test_wheel_zooms_the_view(cadview, qt_app):
    """看图区域要能**鼠标滚轮缩放**（上滚放大、下滚缩小），事件要被吃掉（不再滚动）。"""
    from PySide6.QtCore import QPoint

    class Wheel:
        def __init__(self, delta):
            self._delta = delta
            self.accepted = False

        def angleDelta(self):
            return QPoint(0, self._delta)

        def accept(self):
            self.accepted = True

    view = cadview.CadView(cadview.load(str(DRAWINGS / "plate.dxf")))
    view.warn_on_error = False
    before = view.view.transform().m11()
    zoom_in = Wheel(120)
    view.view.wheelEvent(zoom_in)
    assert zoom_in.accepted
    assert view.view.transform().m11() > before
    view.view.wheelEvent(Wheel(-120))
    assert view.view.transform().m11() == pytest.approx(before, rel=1e-6)


def test_directory_stays_when_clicking_inside_it(cadview, qt_app, tmp_path):
    """打开目录（递归）后点子目录里的图纸，列表**保持**是那个选中的目录，不收窄到子目录。"""
    (tmp_path / "nested").mkdir()
    shutil.copy(DRAWINGS / "plate.dxf", tmp_path / "one.dxf")
    shutil.copy(DRAWINGS / "bracket.dxf", tmp_path / "nested" / "two.dxf")
    view = cadview.CadView(cadview.load(str(tmp_path / "one.dxf")))
    view.warn_on_error = False
    view.open_directory(str(tmp_path))
    assert cadview.tree_file_count(view.drawings) == 2
    assert view.open_path(str(tmp_path / "nested" / "two.dxf")) is True
    assert cadview.tree_file_count(view.drawings) == 2        # 列表没被收窄
    assert Path(view.directory) == tmp_path
    assert view.drawings.currentItem().text(0) == "two.dxf"  # 树叶子显示文件名（目录节点表示层级）


def test_empty_drawing_shows_a_notice(cadview, qt_app):
    """什么都不画的图要在画面上写清原因，而不是给一块白板。"""
    import moz_cadio as cadio
    cad = cadio.CadFile(path="empty.dxf")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="INSERT", layer="0"))       # 无名、文件里也没别的块
    scene, per_layer, counts, _missing, _notes = cadview.build_scene(cad)
    assert counts == {} and per_layer == {}
    texts = [item.text() for item in scene.items() if hasattr(item, "text")]
    assert any("没有可绘制的图元" in text and "无名块参照" in text for text in texts)


def test_unnamed_block_is_inferred_when_it_is_the_only_one(cadview, qt_app):
    """块名为空、文件里只有一个**非 `*D`** 块时按它画（否则该块永远没人引用，整张空白）。

    `*D` 名字的块走"按匿名标注块补画"那条路（见下一个用例），这里用别的名字把推断那条路钉住。
    """
    import moz_cadio as cadio
    cad = cadio.CadFile(path="one-block.dxf")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="DIMENSION", layer="0"))            # 无名标注
    cad.entities.append(cadio.Entity(kind="LINE", layer="0", owner="CONTAINER",
                                     p1=(0, 0, 0), p2=(10, 0, 0)))            # 唯一的块内容
    notes = []
    drawn = list(cadio.iter_draw(cad, notes=notes))
    assert len(drawn) == 1 and drawn[0][0].kind == "LINE"
    assert notes and "*D1" not in notes[0] and "CONTAINER" in notes[0]
    assert list(cadio.iter_draw(cad, notes=[]))[0][0].kind == "LINE"


def test_unnamed_dimension_blocks_are_drawn_when_the_count_matches(cadview, qt_app):
    """DWG 的标注块名上游不给（`DRW_Dimension::parseDwg` 不读那个句柄），但块在文件里。

    无名标注数 ≥ 没被引用的 `*D` 块数时按这些块整体补画（实测 `samples__sample_AC1015.dwg`
    里是 11 : 11，块内几何已经是 WCS）；每个块只画一次，`missing` 里不再有"无名标注块"。
    """
    import moz_cadio as cadio
    cad = cadio.CadFile(path="dims.dwg")
    cad.layers.append(cadio.Layer(name="0"))
    for _index in range(2):
        cad.entities.append(cadio.Entity(kind="DIMENSION", layer="0"))            # 2 个无名标注
    for index in range(2):                                                        # 2 个候选块
        for x in (0.0, 1.0):
            cad.entities.append(cadio.Entity(kind="LINE", layer="0", owner=f"*D{index + 3}",
                                             p1=(x, 0, 0), p2=(x, 1, 0)))
    missing, notes = [], []
    drawn = list(cadio.iter_draw(cad, missing=missing, notes=notes))
    assert len(drawn) == 4                       # 2 个块 × 2 条线，各画一次
    assert not missing
    assert len(notes) == 1 and "2 个标注的图形按匿名块补画" in notes[0] and "*D3" in notes[0]


def test_dwg_dimensions_get_their_graphics_drawn(cadview, qt_app):
    """实测的 DWG 档：11 个标注的图形补画出来了（MTEXT 箭头线都在块里），且没有"没画出来的"。"""
    path = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if not path.exists():
        pytest.skip("DWG 语料缺失")
    _scene, _per_layer, counts, missing, notes = cadview.build_scene(cadview.load(str(path)))
    assert not missing, missing
    assert counts.get("MTEXT", 0) >= 10 and counts.get("SOLID", 0) >= 10
    assert any("标注的图形按匿名块补画" in text and "*D" in text for text in notes)


def test_first_drawable_skips_an_empty_first_entry(cadview, monkeypatch, tmp_path):
    """打开目录时别停在整张空白的图纸上（取前几张里画得出来的那张）。"""
    import moz_cadio as cadio

    empty = tmp_path / "a_empty.dxf"
    good = tmp_path / "b_good.dxf"
    for path in (empty, good):
        path.write_text("0\nEOF\n", encoding="utf-8")

    def fake_load(path):
        if Path(path).name == "a_empty.dxf":
            cad = cadio.CadFile(path=str(path))
            cad.layers.append(cadio.Layer(name="0"))
            return cad
        cad = cadio.read(str(DRAWINGS / "plate.dxf"))
        cad.path = str(path)                       # 假装就是这张（真读的是样例）
        return cad

    monkeypatch.setattr(cadview, "load", fake_load)
    view = cadview.CadView(fake_load(empty), directory=str(tmp_path))
    view.warn_on_error = False
    assert Path(view._first_drawable([str(empty), str(good)])).name == "b_good.dxf"
    assert view.open_directory(str(tmp_path)) is True
    # 已经看的是目录里的某张：不擅自换走（列表照样列出全部）
    assert Path(view.cad.path).name == "a_empty.dxf"

    other = tmp_path / "other"                             # 换到另一个目录：挑一张画得出来的
    other.mkdir()
    (other / "a_empty.dxf").write_text("0\nEOF\n", encoding="utf-8")
    (other / "b_good.dxf").write_text("0\nEOF\n", encoding="utf-8")
    assert view.open_directory(str(other)) is True
    assert Path(view.cad.path).name == "b_good.dxf"


def test_problem_panel_shows_the_whole_story(cadview, qt_app):
    """下方「问题」面板给**全文**（状态栏那行会被截断）：计数、没画出来的原因、推断、读取告警。"""
    view = cadview.CadView(cadview.load(str(DRAWINGS / "bracket.dxf")))
    view.warn_on_error = False
    text = view.report.toPlainText()
    assert "文件：" in text and "画出来的：" in text
    assert "没有告警：这张图读得干净。" in text

    dwg = DWGS / "acadsharp" / "samples__sample_AC1015.dwg"
    if dwg.exists():
        view.open_path(str(dwg))
        text = view.report.toPlainText()
        # 这张图现在**读得干净**：没画出来的、读取告警都没有，只剩"推断/近似"说明
        assert "推断出来的" in text
        assert "标注的图形按匿名块补画" in text
        assert "1 个 SHAPE 是只标了插入点" in text and "1 个 WIPEOUT" in text   # 近似画法说明
        assert "没画出来的原因" not in text
        assert "读取时的告警" not in text
        assert len(text) > len(view.window.statusBar().currentMessage())   # 面板比状态栏详细


def test_problem_panel_explains_a_failure(cadview, qt_app, tmp_path):
    """打不开时面板给出原因与常见原因清单（不再只有一行截断的 label）。"""
    from PySide6.QtWidgets import QApplication

    view = cadview.CadView(cadview.load(str(DRAWINGS / "plate.dxf")))
    view.warn_on_error = False
    assert view.open_path(str(tmp_path / "nope.dwg")) is False
    text = view.report.toPlainText()
    assert "打不开" in text and "常见原因" in text and "R2.5" in text

    view.copy_report()                                   # 一键复制（好贴出来）
    assert "打不开" in QApplication.clipboard().text()


def test_leader_and_image_are_drawn(cadview, qt_app):
    """引线按折点画、图片画出它的一条边（以前两者都被整条忽略、只在告警里提一句）。"""
    import moz_cadio as cadio

    leader = cadio.Entity(kind="LEADER", layer="0", points=(0.0, 0.0, 10.0, 5.0, 20.0, 0.0))
    chains = cadio.entity_polylines(leader)
    assert len(chains) == 1 and chains[0] == [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]

    image = cadio.Entity(kind="IMAGE", layer="0", p1=(0, 0, 0), p2=(5, 0, 0))
    assert cadio.entity_polylines(image)[0] == [(0.0, 0.0), (5.0, 0.0)]
    assert cadio.entity_polylines(cadio.Entity(kind="IMAGE", layer="0")) == []

    path = DWGS / "acadsharp" / "samples__sample_AC1014.dwg"
    if path.exists():                                   # 语料里这张既有引线也有图片
        _cad, _scene, _per, counts, _m = scene_of(cadview, path)
        assert counts.get("LEADER", 0) >= 1 and counts.get("IMAGE", 0) >= 1


def test_unnamed_dimension_explains_the_candidates(cadview, qt_app):
    """候选 `*D` 块比无名标注多（数量对不上）就不补画，只报清"文件里有几个没被引用的 *D 块"。"""
    import moz_cadio as cadio
    cad = cadio.CadFile(path="dims.dwg")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="DIMENSION", layer="0"))                 # 无名
    for index in range(3):                                                        # 3 个候选块
        cad.entities.append(cadio.Entity(kind="LINE", layer="0", owner=f"*D{index + 3}",
                                         p1=(0, 0, 0), p2=(1, 0, 0)))
    missing = []
    assert list(cadio.iter_draw(cad, missing=missing)) == []
    assert missing and "*D 块" in missing[0] and "3 个" in missing[0]


def test_drawable_count_matches_what_gets_drawn(cadview, qt_app):
    """`drawable_count()` 的判据要跟真正画出来的东西一致（空图返回 0）。"""
    for name in ("plate", "bracket", "messy"):
        assert cadview.drawable_count(cadview.load(str(DRAWINGS / f"{name}.dxf"))) > 0

    import moz_cadio as cadio
    empty = cadio.CadFile(path="empty.dxf")
    empty.layers.append(cadio.Layer(name="0"))
    empty.entities.append(cadio.Entity(kind="HATCH", layer="0"))       # 没有边界环
    empty.entities.append(cadio.Entity(kind="LWPOLYLINE", layer="0"))  # 没有顶点
    assert cadview.drawable_count(empty) == 0


def test_unmatched_block_gets_a_candidate_hint(cadview, qt_app):
    """找不到块定义时要说清"文件里有没有名字相近的块"（实测 DWG 匿名块名会这样对不上）。"""
    import moz_cadio as cadio
    cad = cadio.CadFile(path="anon.dwg")
    cad.layers.append(cadio.Layer(name="0"))
    cad.entities.append(cadio.Entity(kind="INSERT", layer="0", name="*U"))          # 对不上
    cad.entities.append(cadio.Entity(kind="LINE", layer="0", owner="*U19",
                                     p1=(0, 0, 0), p2=(1, 0, 0)))                   # 块定义
    hint = cadview._missing_hint(cad, "*U")
    assert "找不到块定义 *U" in hint and "*U19" in hint and "匿名块名" in hint
    assert cadview._missing_hint(cad, "(无名块参照)") == "(无名块参照)"              # 已经是说明了
    assert cadview._missing_hint(cad, "别的名字") == "找不到块定义 别的名字"        # 没有相近的就不猜


def test_empty_and_truncated_dwg_errors_are_explicit(cadview, tmp_path):
    """0 字节/半截的 .dwg 要说清是"没下完或不是 DWG"，而不是丢一句 DXF 解析失败。"""
    import moz_cadio as cadio

    empty = tmp_path / "empty.dwg"
    empty.write_bytes(b"")
    with pytest.raises(cadio.CadIoError) as info:
        cadview.load(str(empty))
    assert "0 字节或没下完" in str(info.value)

    half = tmp_path / "half.dwg"
    half.write_bytes(b"AC1024" + b"\0" * 200)
    with pytest.raises(cadio.CadIoError) as info2:
        cadview.load(str(half))
    assert "BAD_READ" in str(info2.value)                    # 版本串对、内容不全

    misfiled = tmp_path / "really-dxf.dwg"                   # 扩展名写错：照样能读
    misfiled.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    assert cadview.load(str(misfiled)) is not None


def test_scan_lists_verdicts_with_reasons(cadview, tmp_path, capsys):
    """`--scan` 逐张体检：画得出 / 画不出 / 打不开，并给出原因（不需要 Qt）。"""
    shutil.copy(DRAWINGS / "plate.dxf", tmp_path / "good.dxf")
    (tmp_path / "broken.dxf").write_text("这不是图纸\n", encoding="utf-8")
    blank = DWGS / "acadsharp" / "samples__geolocation__geoloc.dwg"
    if blank.exists():
        shutil.copy(blank, tmp_path / "blank.dwg")

    assert cadview.main([str(tmp_path), "--scan"]) == 0
    out = capsys.readouterr().out
    assert "[画得出]" in out and "good.dxf" in out
    assert "[打不开]" in out and "broken.dxf" in out
    assert "汇总:" in out and "画得出" in out


def test_demo_lists_samples_reports_and_headless(cadview, monkeypatch, capsys, tmp_path):
    demo = pytest.importorskip("cadview_demo")

    assert demo.main(["--samples"]) == 0
    assert "样例图纸" in capsys.readouterr().out

    assert demo.main([str(DRAWINGS / "plate.dxf"), "--report"]) == 0
    assert "格式：dxf" in capsys.readouterr().out

    assert demo.main([str(tmp_path / "nope.dxf"), "--stats"]) == 2
    assert "读不了" in capsys.readouterr().err

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert demo.main([]) == 1                       # 无显示器：给提示而不是崩
    assert "没有显示器" in capsys.readouterr().err


def test_cli_directory_report_and_stats(cadview, qt_app, tmp_path, capsys):
    """命令行给目录：--report 逐个打印；--stats 看第一张。"""
    shutil.copy(DRAWINGS / "plate.dxf", tmp_path / "one.dxf")
    shutil.copy(DRAWINGS / "bracket.dxf", tmp_path / "two.dxf")

    assert cadview.main([str(tmp_path), "--report"]) == 0
    out = capsys.readouterr().out
    assert "one.dxf" in out and "two.dxf" in out and out.count("格式：dxf") == 2

    assert cadview.main([str(tmp_path), "--stats"]) == 0
    assert "先看：" in capsys.readouterr().out


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
