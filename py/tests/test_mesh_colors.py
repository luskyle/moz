"""三角化网格直取（triangles）与逐面颜色（face_colors）测试。"""

import array
import struct

import pytest


def test_triangles_layout(moz):
    tris = moz.eval_text("cube(10);").triangles()
    assert isinstance(tris, array.array)
    assert tris.typecode == "f"
    assert len(tris) == 12 * 9          # 12 个三角面 × 3 顶点 × 3 分量


def test_triangles_match_binstl(moz):
    """triangles() 与 binstl 导出的三角面一致（同精度 float32）。"""
    g = moz.eval_text("difference() { cube(20, center = true); sphere(12, $fn = 48); }")
    tris = g.triangles()
    data = g.export_bytes("binstl")
    count = struct.unpack_from("<I", data, 80)[0]
    assert count == len(tris) // 9
    offset = 84
    for i in range(count):
        stl_vertices = struct.unpack_from("<12f", data, offset)[3:12]
        offset += 50
        assert tuple(tris[i * 9:i * 9 + 9]) == pytest.approx(stl_vertices)


def test_triangles_empty_for_2d(moz):
    assert len(moz.eval_text("circle(2);").triangles()) == 0


def test_face_colors_aligned_with_triangles(moz):
    g = moz.eval_text('color("red") cube(5);')
    colors = g.face_colors()
    assert len(colors) == (len(g.triangles()) // 9) * 4
    assert bytes(colors[0:3]) == b"\xff\x00\x00"     # 红色


def test_face_colors_colorscheme_changes_material_color(moz):
    """配色会影响未着色对象的材质色。"""
    g = moz.eval_text("cube(5);")
    default = g.face_colors()
    try:
        tomorrow = g.face_colors("Tomorrow")
    finally:
        g.face_colors("Cornfield")     # 还原默认配色，避免影响后面的测试
    assert len(default) == len(tomorrow)
    assert default != tomorrow


def test_face_colors_unknown_scheme_warns_and_falls_back(moz):
    g = moz.eval_text("cube(2);")
    colors = g.face_colors("NoSuchScheme")
    assert len(colors) > 0
    assert "Unknown color scheme" in g.log


def test_face_colors_empty_geometry(moz):
    assert moz.eval_text('echo(1);').face_colors() == b""
