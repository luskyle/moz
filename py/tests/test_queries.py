"""几何查询（contains_point / distance_to_surface / inertia）与三角化缓存测试。"""

import pytest


def test_contains_point(moz):
    g = moz.eval_text("cube(10, center = true);")
    assert g.contains_point(0, 0, 0) is True
    assert g.contains_point(4.9, -4.9, 0) is True    # 内部
    assert g.contains_point(6, 0, 0) is False
    assert g.contains_point(0, 0, 100) is False
    # 恰好落在表面/顶点上的点，射线奇偶法不保证（故不测边界）


def test_contains_point_after_difference(moz):
    g = moz.eval_text("difference() { cube(20, center = true); sphere(8, $fn = 32); }")
    assert g.contains_point(0, 0, 0) is False         # 挖空了
    assert g.contains_point(9, 0, 0) is True          # 壳里


def test_distance_to_surface(moz):
    g = moz.eval_text("cube(10, center = true);")
    assert g.distance_to_surface(6, 0, 0) == pytest.approx(1.0)
    assert g.distance_to_surface(0, 0, 0) == pytest.approx(5.0)
    assert g.distance_to_surface(0, 0, -7) == pytest.approx(2.0)


def test_inertia_of_cube(moz):
    """单位密度立方体边长 10：m·s²/6 = 16666.67，非对角为 0。"""
    inertia = moz.eval_text("cube(10, center = true);").inertia()
    assert len(inertia) == 3 and all(len(row) == 3 for row in inertia)
    assert inertia[0][0] == pytest.approx(1000 * 100 / 6, rel=1e-9)
    assert inertia[1][1] == pytest.approx(1000 * 100 / 6, rel=1e-9)
    assert inertia[2][2] == pytest.approx(1000 * 100 / 6, rel=1e-9)
    assert inertia[0][1] == pytest.approx(0.0, abs=1e-9)


def test_inertia_is_translation_invariant(moz):
    """关于**质心**的惯性张量与位置无关（平行轴定理搬到质心）。"""
    at_origin = moz.eval_text("cube(10, center = true);").inertia()
    moved = moz.eval_text("translate([100, -30, 7]) cube(10, center = true);").inertia()
    for row in range(3):
        for col in range(3):
            # 非对角元在平移后可能只是数值噪声（~1e-13），所以用绝对容差
            assert moved[row][col] == pytest.approx(at_origin[row][col], rel=1e-9, abs=1e-6)


def test_inertia_of_thin_rod(moz):
    """沿 X 的细长条：Ixx 远小于 Iyy/Izz。"""
    inertia = moz.eval_text("cube([40, 2, 2], center = true);").inertia()
    assert inertia[0][0] < inertia[1][1]
    assert inertia[1][1] == pytest.approx(inertia[2][2], rel=1e-9)


def test_queries_reject_2d_and_empty(moz):
    circle = moz.eval_text("circle(5);")
    assert circle.contains_point(0, 0, 0) is False
    with pytest.raises(moz.OpenSCADError):
        circle.distance_to_surface(0, 0, 0)
    with pytest.raises(moz.OpenSCADError):
        circle.inertia()
    with pytest.raises(moz.OpenSCADError):
        moz.eval_text('echo("x");').distance_to_surface(0, 0, 0)


def test_triangulation_cache_is_consistent(moz):
    """measure / triangles / face_colors 共用一次三角化，多次调用结果一致。"""
    g = moz.eval_text("difference() { cube(20, center = true); sphere(12, $fn = 32); }")
    first = g.measure
    triangle_count = len(g.triangles()) // 9
    second = g.measure
    colors = g.face_colors()
    assert first.facets == second.facets == triangle_count
    assert first.volume == second.volume
    assert len(colors) == triangle_count * 4


def test_shape_and_part_queries(moz):
    assert moz.cube(10, center=True).contains_point(0, 0, 0) is True
    assert moz.Box((10, 10, 10)).inertia()[0][0] == pytest.approx(1000 * 100 / 6, rel=1e-9)
