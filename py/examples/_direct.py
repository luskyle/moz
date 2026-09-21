"""Direct Python geometry builders shared by the categorized examples."""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "py") not in sys.path:
    sys.path.insert(0, str(ROOT / "py"))

import moz_openscad as moz


def _ring(radius, count, child):
    items = []
    for index in range(count):
        angle = index * 360 / count
        radians = math.radians(angle)
        items.append(moz.translate([radius * math.sin(radians), -radius * math.cos(radians), 0], moz.rotate([0, 0, angle], child)))
    return moz.union(*items)


def _gear(teeth=12, inner=12, outer=18, height=6):
    items = []
    for index in range(teeth):
        angle = index * 360 / teeth
        items.append(moz.rotate([0, 0, angle], moz.translate([outer - 3, 0, 0], moz.cube([6, 5, height], center=True))))
    return moz.union(moz.cylinder(h=height, r=inner, center=True), *items)


def build_example(name):
    """Build a direct-Python approximation for a categorized OpenSCAD example."""
    if name in {"Basics/CSG", "Basics/CSG-modules"}:
        joined = moz.union(moz.cube(15, center=True), moz.sphere(10))
        clipped = moz.intersection(moz.cube(15, center=True), moz.sphere(10))
        hollow = moz.difference(moz.cube(15, center=True), moz.sphere(10))
        return moz.union(moz.translate([-24, 0, 0], joined), clipped, moz.translate([24, 0, 0], hollow))

    if name in {"Basics/linear_extrude", "Advanced/GEB", "Parametric/sign"}:
        outline = moz.polygon([[-20, -12], [0, 20], [20, -12], [0, -4]])
        return moz.linear_extrude(outline, height=8, center=True)

    if name in {"Basics/rotate_extrude", "Old/example007", "Old/example009", "Old/example017"}:
        profile = moz.translate([10, 0], moz.square(5))
        return moz.rotate_extrude(profile, angle=270)

    if name in {"Basics/projection", "Old/example021"}:
        solid = moz.difference(moz.cube([30, 30, 12], center=True), moz.cylinder(h=20, r=5, center=True))
        return moz.projection(solid)

    if name in {"Advanced/children", "Advanced/children_indexed"}:
        child = moz.difference(moz.sphere(5), moz.cylinder(h=14, r=2, center=True))
        return _ring(28, 8, child)

    if name in {"Advanced/animation", "Advanced/module_recursion", "Functions/recursion"}:
        return _gear(16, 10, 19, 5)

    if name in {"Advanced/offset", "Basics/basic_offset"}:
        outline = moz.offset(moz.square(40, center=True), 5)
        return moz.linear_extrude(outline, height=12, center=True, scale=0.7)

    if name in {"Advanced/surface_image", "Old/example023"}:
        return moz.cube([24, 24, 4], center=True)

    if name.startswith("Functions/"):
        return moz.linear_extrude(moz.circle(12), height=5, center=True)

    if name.startswith("Parametric/"):
        base = moz.cylinder(h=8, r=30, center=True)
        rim = moz.difference(moz.cylinder(h=12, r=24, center=True), moz.cylinder(h=14, r=18, center=True))
        return moz.union(base, moz.translate([0, 0, 8], rim))

    if name.startswith("Old/"):
        index = int(name.removeprefix("Old/example"))
        if index % 4 == 0:
            return moz.rotate_extrude(moz.translate([8, 0], moz.square(4)), angle=180)
        if index % 4 == 1:
            return moz.linear_extrude(moz.polygon([[0, 0], [20, 0], [12, 14]]), height=10, center=True)
        if index % 4 == 2:
            return moz.difference(moz.cube([28, 28, 12], center=True), moz.cylinder(h=20, r=8, center=True))
        return _gear(10 + index % 8, 10, 18, 6)

    return moz.union(moz.cube(20, center=True), moz.sphere(12))


def show_example(name, title=None):
    shape = build_example(name)
    shape.show(title=title or f"moz - {name}")
    return shape
