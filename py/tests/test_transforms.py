"""resize() 与 `%`/`#`/`!`/`*` 修饰符助手测试。"""

import pytest


def test_resize_scales_bbox(moz):
    m = moz.resize([20, 10, 5], moz.cube(10)).measure
    assert m.bbox_min == pytest.approx((0.0, 0.0, 0.0))
    assert m.bbox_max == pytest.approx((20.0, 10.0, 5.0))
    assert m.volume == pytest.approx(1000.0, rel=1e-9)


def test_shape_resize_method(moz):
    assert moz.cube(10).resize([20, 10, 5]).measure.volume == pytest.approx(1000.0, rel=1e-9)


def test_resize_with_auto_uses_autoscale(moz):
    """auto 为 true 的分量用 autoscale：取 newsize 里最大的已指定分量与包围盒之比。

    newsize = [20, 10, 0]，auto[2] = true → maxdim 是 0（20 > 10），autoscale = 20 / 10 = 2，
    所以 z 也从 10 变成 20。
    """
    shape = moz.resize([20, 10, 0], moz.cube(10), auto=[False, False, True])
    m = shape.measure
    assert m.bbox_max[0] == pytest.approx(20.0)
    assert m.bbox_max[1] == pytest.approx(10.0)
    assert m.bbox_max[2] == pytest.approx(20.0)


def test_resize_requires_object(moz):
    with pytest.raises(ValueError):
        moz.resize([1, 1, 1])


def test_disable_modifier_removes_geometry(moz):
    assert moz.disable(moz.cube(1)).is_empty


def test_highlight_modifier_is_geometry_equivalent(moz):
    assert moz.highlight(moz.cube(2)).measure.volume == pytest.approx(8.0, rel=1e-9)


def test_only_modifier_keeps_single_node(moz):
    shape = moz.union(moz.only(moz.cube(1)), moz.translate([10, 0, 0], moz.cube(2)))
    assert shape.measure.volume == pytest.approx(1.0, rel=1e-9)


def test_background_modifier_excluded_from_f6(moz):
    # `%` 背景对象在 F6 / 导出里被排除；整个模型都是背景时几何为空
    assert moz.background(moz.cube(1)).is_empty


def test_modifier_source_text(moz):
    assert str(moz.background(moz.cube(1))).startswith("% ")
    assert str(moz.disable(moz.cube(1))).startswith("* ")
    assert str(moz.highlight(moz.cube(1))).startswith("# ")
    assert str(moz.only(moz.cube(1))).startswith("! ")