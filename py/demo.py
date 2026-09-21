#!/usr/bin/env python3
"""moz_openscad 演示：直接用 Python 建模并显示 3D 参数化支架。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "out")


def main():
    os.makedirs(OUT, exist_ok=True)

    width, height, thickness, hole_radius = 50, 60, 6, 3
    base = moz.cube([width, thickness, height])
    side = moz.cube([thickness, width, height])
    hole = moz.translate(
        [width / 2, thickness / 2, height - 8],
        moz.rotate([90, 0, 0], moz.cylinder(r=hole_radius, h=thickness + 2, center=True)),
    )
    brace = moz.difference(moz.union(base, side), hole)

    print("brace dimension:", brace.dimension)
    brace.export("binstl", os.path.join(OUT, "brace.stl"))
    brace.export("3mf", os.path.join(OUT, "brace.3mf"))

    print("close the preview window to finish the demo")
    brace.show(title="moz demo - brace")

    print("--- csg dump ---")
    print(moz.dump("translate([1, 2, 3]) cube(2);", "csg"))
    print("all done ->", OUT)


if __name__ == "__main__":
    main()
