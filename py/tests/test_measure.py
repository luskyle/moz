"""几何测量（Geometry.measure / moz_geom_measure）测试。"""

import math
import struct

import pytest


def _stl_solid(data):
    """从 binstl 反算 (面数, 体积, 表面积)，用于交叉验证 measure 的口径。"""
    count = struct.unpack_from("<I", data, 80)[0]
    volume = area = 0.0
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12f", data, offset)
        offset += 50
        p0, p1, p2 = values[3:6], values[6:9], values[9:12]
        volume += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1])
                   + p0[1] * (p1[2] * p2[0] - p1[0] * p2[2])
                   + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0])) / 6.0
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        area += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return count, abs(volume), area


def test_cube_measure(moz):
    m = moz.eval_text("cube(10, center = true);").measure
    assert m.dimension == 3
    assert m.is_empty is False
    assert m.volume == pytest.approx(1000.0, rel=1e-12)
    assert m.area == pytest.approx(600.0, rel=1e-12)
    assert m.facets == 12
    assert m.vertices == 8
    assert m.bbox_min == pytest.approx((-5.0, -5.0, -5.0))
    assert m.bbox_max == pytest.approx((5.0, 5.0, 5.0))
    assert m.centroid == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert m.bbox == (m.bbox_min, m.bbox_max)


def test_cylinder_volume_and_bbox(moz):
    m = moz.eval_text("cylinder(h = 10, r = 2, $fn = 256);").measure
    assert m.volume == pytest.approx(math.pi * 4 * 10, rel=1e-3)   # 多边形近似
    assert m.bbox_min[2] == pytest.approx(0.0)
    assert m.bbox_max[2] == pytest.approx(10.0)


def test_2d_measure(moz):
    m = moz.eval_text("circle(r = 10, $fn = 720);").measure
    assert m.dimension == 2
    assert m.area == pytest.approx(math.pi * 100, rel=1e-3)
    assert math.isnan(m.volume)                      # 2D 没有体积
    assert m.centroid[0] == pytest.approx(0.0, abs=1e-6)
    assert m.centroid[1] == pytest.approx(0.0, abs=1e-6)
    assert m.bbox_min[2] == 0.0                      # 2D 的 z 恒为 0


def test_empty_geometry_measure(moz):
    m = moz.eval_text('echo("none");').measure
    assert m.dimension == 3 and m.is_empty
    assert m.volume == 0.0 and m.area == 0.0 and m.facets == 0 and m.vertices == 0
    assert math.isnan(m.bbox_min[0]) and math.isnan(m.centroid[0])


def test_measure_agrees_with_stl(moz):
    """measure 的口径与 binstl 导出一致（体积/面积/面数）。

    用一个坐标都是整数的模型：STL 是 float32，整数坐标可精确表示，所以能要求紧容差。
    """
    g = moz.eval_text("difference() { cube(20, center = true); cube(10, center = true); }")
    m = g.measure
    count, volume, area = _stl_solid(g.export_bytes("binstl"))
    assert m.facets == count
    assert m.volume == pytest.approx(volume, rel=1e-12)
    assert m.area == pytest.approx(area, rel=1e-12)
    assert m.volume == pytest.approx(8000.0 - 1000.0, rel=1e-12)


def test_measure_repeatable(moz):
    g = moz.eval_text("sphere(5, $fn = 64);")
    assert g.measure.volume == g.measure.volume     # 确定性


def test_shape_and_part_measure(moz):
    assert moz.cube(4, center=True).measure.volume == pytest.approx(64.0)
    assert moz.Box((2, 2, 2)).measure.facets == 12