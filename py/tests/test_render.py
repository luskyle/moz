"""渲染选项（相机覆盖 / 投影 / 配色 / 标志位）测试。"""

import pytest


def test_render_png_header(moz):
    assert moz.eval_text("cube(2, $fn = 8);").render_png_bytes(48, 48)[:8] == b"\x89PNG\r\n\x1a\n"


def test_camera_override_changes_image(moz):
    g = moz.eval_text("cube(10, center = true);")
    base = g.render_png_bytes(64, 64)
    override = g.render_png_bytes(64, 64, vpr=[0, 0, 0], vpt=[0, 0, 0], vpd=40)
    assert base != override


def test_camera_distance_matters(moz):
    g = moz.eval_text("cube(10, center = true);")
    near = g.render_png_bytes(64, 64, vpr=[0, 0, 0], vpt=[0, 0, 0], vpd=15)
    far = g.render_png_bytes(64, 64, vpr=[0, 0, 0], vpt=[0, 0, 0], vpd=45)
    assert near != far


def test_orthographic_projection(moz):
    g = moz.eval_text("cube(10, center = true);")
    assert g.render_png_bytes(64, 64, projection="ortho") != g.render_png_bytes(64, 64)


def test_camera_override_applies_to_cgal_path(moz):
    g = moz.eval_text("cube(10, center = true);")
    near = g.render_png_bytes(64, 64, renderer="cgal", vpr=[0, 0, 0], vpt=[0, 0, 0], vpd=15)
    far = g.render_png_bytes(64, 64, renderer="cgal", vpr=[0, 0, 0], vpt=[0, 0, 0], vpd=45)
    assert near != far


def test_colorscheme_changes_image(moz):
    """注意：colorscheme 是**全局**配色（上游 set_render_color_scheme 语义），
    所以要先取默认再取指定，最后还原，否则后面的调用也会用被切过去的配色。"""
    g = moz.eval_text("cube(10, center = true);")
    default = g.render_png_bytes(64, 64)
    try:
        tomorrow = g.render_png_bytes(64, 64, colorscheme="Tomorrow")
    finally:
        g.render_png_bytes(8, 8, colorscheme="Cornfield")   # 还原默认配色
    assert default != tomorrow


def test_render_is_deterministic(moz):
    g = moz.eval_text("cube(3);")
    assert g.render_png_bytes(48, 48) == g.render_png_bytes(48, 48)


def test_camera_option_validation(moz):
    g = moz.eval_text("cube(1);")
    with pytest.raises(ValueError):
        g.render_png_bytes(32, 32, vpr=[1, 2, 3])              # 缺 vpd
    with pytest.raises(ValueError):
        g.render_png_bytes(32, 32, projection="nope")
    with pytest.raises(ValueError):
        g.render_png_bytes(32, 32, vpr=[1, 2], vpd=10)         # 向量长度不对
