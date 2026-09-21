"""Shape 惰性求值缓存测试。"""

import pytest


def test_shape_reuses_geometry(moz):
    shape = moz.cube(3)
    first = shape._geometry()
    second = shape._geometry()
    assert first is second          # 同一个句柄，没有重新求值
    assert first.dimension == 3


def test_shape_cache_invalidates_on_variable_change(moz):
    shape = moz.Shape("cube(n, center = true);", n=2)
    assert shape.measure.volume == pytest.approx(8.0)
    first = shape._geometry()
    shape.variables["n"] = 3         # 改变量后缓存应失效
    assert shape.measure.volume == pytest.approx(27.0)
    assert shape._geometry() is not first


def test_shape_measure_and_colors_share_one_eval(moz):
    """measure 与 triangles 应命中同一个缓存（否则会各自求值）。"""
    shape = moz.Shape("sphere(4, $fn = 32);")
    volume = shape.measure.volume
    geometry = shape._geometry()
    assert geometry.measure.volume == volume
    assert len(shape.triangles()) // 9 == geometry.measure.facets


def test_mutating_source_does_not_reuse_cache(moz):
    """换一个 Shape 对象就是新的缓存（source 变了）。"""
    a = moz.cube(2)
    b = moz.cube(2)
    assert a._geometry() is not b._geometry()