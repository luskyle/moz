"""截面与视图（moz.section / moz.outline / moz.view_basis）测试。

截面在 kernel 侧是「用刚体变换把切平面搬到 z = 0，再 projection(cut = true)」实现的
（见 docs/drawing.md），所以这里用**解析法**做独立校验：立方体被平面切的截面是凸多边形，
顶点就是平面与立方体棱的交点，面积可以精确算出来对照。

容差说明：解析法是有理数精确值；引擎侧要经过 CGAL 求交与投影，实测相对误差 —
轴对齐/方体情形为 0；斜平面截面 ~5e-7；圆柱这类曲线体截面 ~8e-8；轮廓投影 ~2e-6。
所以下面用 SECTION_REL / OUTLINE_REL 两档，足以抓住方向/平面/参数搞错这类数量级错误
（见 test_section_is_sensitive_to_plane）。
"""

import itertools
import math

import pytest

SECTION_REL = 1e-6      # 截面（projection(cut = true) 路径）
OUTLINE_REL = 1e-5      # 轮廓投影（projection(cut = false) 路径，误差略大）


# --- 独立解析法：平面与 [-half, half]^3 的棱求交，返回截面面积 ---


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def analytic_cube_section_area(half, normal, through):
    """解析求立方体截面面积：平面与 12 条棱的交点按极角排序后算凸多边形面积。"""
    n = [c / math.sqrt(_dot(normal, normal)) for c in normal]
    d = _dot(n, through)
    corners = list(itertools.product((-half, half), repeat=3))
    edges = [(a, b) for a, b in itertools.combinations(corners, 2)
             if sum(1 for i in range(3) if a[i] != b[i]) == 1]
    hits = []
    for a, b in edges:
        da, db = _dot(n, a) - d, _dot(n, b) - d
        if abs(da) < 1e-12:
            hits.append(a)
        elif abs(db) < 1e-12:
            hits.append(b)
        elif da * db < 0:
            t = da / (da - db)
            hits.append(tuple(a[i] + t * (b[i] - a[i]) for i in range(3)))
    unique = []
    for point in hits:
        if not any(all(abs(point[i] - other[i]) < 1e-9 for i in range(3)) for other in unique):
            unique.append(point)
    x = _cross([0.0, 0.0, 1.0], n)
    length = math.sqrt(_dot(x, x))
    x = [c / length for c in x]
    y = _cross(n, x)
    flat = [(_dot(x, p), _dot(y, p)) for p in unique]
    cx = sum(p[0] for p in flat) / len(flat)
    cy = sum(p[1] for p in flat) / len(flat)
    flat.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    area = 0.0
    for i in range(len(flat)):
        x1, y1 = flat[i]
        x2, y2 = flat[(i + 1) % len(flat)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


# --- view_basis ---


def test_view_basis_standard_views(moz):
    assert moz.view_basis(moz.UP) == ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
    assert moz.view_basis(moz.FRONT)[0] == pytest.approx([1.0, 0.0, 0.0])
    assert moz.view_basis(moz.FRONT)[1] == pytest.approx([0.0, 0.0, 1.0])
    assert moz.view_basis(moz.FRONT)[2] == pytest.approx([0.0, -1.0, 0.0])
    assert moz.view_basis(moz.RIGHT)[:2] == pytest.approx(([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]))


def test_view_basis_is_right_handed_and_normalized(moz):
    for normal in ([0, 0, 1], [1, 1, 0], [1, 2, 3], [-0.3, 0.7, -0.5], [0, -1, 0], [0, 0, -1]):
        x, y, z = moz.view_basis(normal)
        assert _dot(x, x) == pytest.approx(1.0)
        assert _dot(y, y) == pytest.approx(1.0)
        assert _dot(z, z) == pytest.approx(1.0)
        assert _dot(x, y) == pytest.approx(0.0)
        assert _dot(x, z) == pytest.approx(0.0)
        assert _cross(x, y) == pytest.approx(z)      # 右手系：x × y = z


def test_view_basis_parallel_up_falls_back(moz):
    """视线与 up 平行时自动换参考方向：法线趋近 ±Z 用 +Y，趋近 ±Y 用 +X。"""
    assert moz.view_basis(moz.UP, up=moz.UP) == moz.view_basis(moz.UP, up=(0.0, 1.0, 0.0))
    assert moz.view_basis((0.0, 1.0, 0.0), up=(0.0, 1.0, 0.0)) == (
        [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    assert moz.view_basis((0.0, -1.0, 0.0), up=(0.0, 1.0, 0.0)) == (
        [0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.0])


def test_view_basis_rejects_zero_vector(moz):
    with pytest.raises(ValueError):
        moz.view_basis((0.0, 0.0, 0.0))


# --- section ---


@pytest.mark.parametrize("normal,through,expected", [
    ([0, 0, 1], (0, 0, 0), 400.0),                          # 过中心
    ([0, 0, 1], (0, 0, 5), 400.0),                          # 平移后仍同面积
    ([1, 0, 0], (0, 0, 0), 400.0),
    ([0, 1, 0], (0, -7, 0), 400.0),
    ([1, 1, 0], (0, 0, 0), 20 * 20 * math.sqrt(2)),         # 对角面：20√2 × 20
])
def test_section_matches_analytic_for_exact_planes(moz, normal, through, expected):
    area = moz.section(moz.cube(20, center=True), normal, through=through).measure.area
    assert area == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("normal,through", [
    ([1, 2, 3], (2, -3, 1)),
    ([0.3, -0.7, 0.5], (-4, 2, 6)),
])
def test_section_arbitrary_plane_matches_analytic(moz, normal, through):
    expected = analytic_cube_section_area(10.0, normal, through)
    area = moz.section(moz.cube(20, center=True), normal, through=through).measure.area
    assert area == pytest.approx(expected, rel=1e-6)


def test_section_is_sensitive_to_plane(moz):
    """反向法线取到的是另一侧的截面（阶梯体：两侧面积差别明显），证明不是恒等通过。"""
    step = moz.union(moz.cube([20, 20, 10]), moz.translate([0, 0, 10], moz.cube([6, 20, 10])))
    low = moz.section(step, moz.UP, through=(0, 0, 0)).measure.area
    high = moz.section(step, moz.UP, through=(0, 0, 12)).measure.area
    assert low == pytest.approx(400.0)
    assert high == pytest.approx(120.0)
    assert abs(low - high) > 200


def test_section_normal_length_does_not_matter(moz):
    cube = moz.cube(20, center=True)
    assert (moz.section(cube, [0, 0, 1], through=(0, 0, 5)).measure.area
            == pytest.approx(moz.section(cube, [0, 0, 7], through=(0, 0, 5)).measure.area))


def ngon_area(radius, segments):
    """正 n 边形面积（用来精确校验圆柱类截面）。"""
    return segments / 2 * radius ** 2 * math.sin(2 * math.pi / segments)


def test_cylinder_section_is_exact_ngon(moz):
    """圆柱的横截面就是它的正 n 边形，面积可以精确计算。"""
    cyl = moz.cylinder(r=10, h=20, fn=64, center=True)
    assert moz.section(cyl, moz.UP).measure.area == pytest.approx(ngon_area(10, 64), rel=SECTION_REL)
    # 轴向截面：过轴线的平面切出 20(直径) × 20(高) 的矩形
    assert moz.section(cyl, moz.RIGHT).measure.area == pytest.approx(400.0, rel=SECTION_REL)


def test_section_of_sphere_shrinks_with_height(moz):
    """球的截面随高度收缩（用区间校验，避免依赖引擎的球面细分方式）。"""
    sphere = moz.sphere(10, fn=64)
    center = moz.section(sphere, moz.UP).measure.area
    higher = moz.section(sphere, moz.UP, through=(0, 0, 6)).measure.area
    assert center < math.pi * 100                 # 球面细分下中心截面略小于真圆
    assert 0.60 <= higher / center <= 0.68        # √(10²−6²)/10 = 0.8 → 面积比 0.64


def test_section_exposes_internal_structure(moz):
    """带中心孔的实体：截面 = 外框 - 内孔（内环被如实切出来）。"""
    tube = moz.difference(moz.cube(20, center=True), moz.cylinder(r=5, h=40, center=True, fn=64))
    section = moz.section(tube, moz.UP)
    assert section.measure.area == pytest.approx(400 - ngon_area(5, 64), rel=SECTION_REL)
    assert section.measure.facets >= 2            # 至少内外两个环

    hollow = moz.difference(moz.cube(20, center=True), moz.sphere(12, fn=32))
    assert moz.section(hollow, moz.UP).measure.area < 400


def test_section_missing_plane_is_empty(moz):
    """平面没穿过实体 → 空几何。

    注意上下文：空截面是「空 Nef」，所以 dimension 是上游语义的 3（不是 2），
    判断有没有东西要用 is_empty。
    """
    empty = moz.section(moz.cube(20, center=True), moz.UP, through=(0, 0, 50))
    assert empty.is_empty
    assert empty.dimension == 3


def test_section_is_two_dimensional_and_has_method_form(moz):
    cube = moz.cube(20, center=True)
    assert moz.section(cube, moz.UP).dimension == 2
    assert cube.section(moz.UP).measure.area == pytest.approx(400.0)
    assert cube.outline(moz.UP).measure.area == pytest.approx(400.0)


def test_section_requires_object(moz):
    with pytest.raises(ValueError):
        moz.section(None)


# --- outline ---


def test_outline_follows_silhouette(moz):
    """阶梯体（xz 平面里是 L 形）：俯视 400，前视 260 = 200 + 60，右视 400。"""
    step = moz.union(moz.cube([20, 20, 10]), moz.translate([0, 0, 10], moz.cube([6, 20, 10])))
    assert moz.outline(step, moz.UP).measure.area == pytest.approx(400.0)
    assert moz.outline(step, moz.FRONT).measure.area == pytest.approx(260.0)
    assert moz.outline(step, moz.RIGHT).measure.area == pytest.approx(400.0)


def test_outline_uses_view_direction(moz):
    plate = moz.cube([40, 10, 4], center=True)
    assert moz.outline(plate, moz.UP).measure.area == pytest.approx(400.0)      # 40 × 10
    assert moz.outline(plate, moz.FRONT).measure.area == pytest.approx(160.0)   # 40 × 4
    assert moz.outline(plate, moz.RIGHT).measure.area == pytest.approx(40.0)    # 10 × 4


def test_outline_of_through_hole_is_annulus(moz):
    """通孔圆柱：顶视投影 = 上下端面的投影并集 = 圆环（与截面面积相同）。"""
    hollow = moz.difference(
        moz.cylinder(r=10, h=10, fn=64, center=True),
        moz.cylinder(r=6, h=12, fn=64, center=True),
    )
    assert moz.outline(hollow, moz.UP).measure.area == pytest.approx(
        ngon_area(10, 64) - ngon_area(6, 64), rel=OUTLINE_REL)
    assert moz.section(hollow, moz.UP).measure.area == pytest.approx(
        ngon_area(10, 64) - ngon_area(6, 64), rel=SECTION_REL)


def test_outline_differs_from_section(moz):
    """盲孔板：顶视轮廓是整个矩形（底面把孔盖住），孔深范围内的截面是矩形减圆。"""
    plate = moz.cube([40, 20, 4], center=True)
    pocket = moz.translate([0, 0, 1], moz.cylinder(r=5, h=2, center=True, fn=32))  # 从 z=2 挖到 z=0
    part = moz.difference(plate, pocket)
    assert moz.outline(part, moz.UP).measure.area == pytest.approx(800.0, rel=OUTLINE_REL)
    assert moz.section(part, moz.UP, through=(0, 0, 1)).measure.area == pytest.approx(
        800 - ngon_area(5, 32), rel=SECTION_REL)
    # 盲孔底以下的截面没有孔
    assert moz.section(part, moz.UP, through=(0, 0, -1)).measure.area == pytest.approx(
        800.0, rel=SECTION_REL)


def test_outline_requires_object(moz):
    with pytest.raises(ValueError):
        moz.outline(None)
