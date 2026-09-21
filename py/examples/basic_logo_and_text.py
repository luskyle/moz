#!/usr/bin/env python3
"""对应 OpenSCAD examples/Basics/logo_and_text.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

logo = moz.sphere(d=60)
# 3 个穿孔
body = moz.difference(
    logo,
    moz.rotate([90, 0, 0], moz.cylinder(h=100, d=20, center=True)),
    moz.rotate([0, 90, 0], moz.cylinder(h=100, d=20, center=True)),
    moz.rotate([0, 0, 90], moz.cylinder(h=100, d=20, center=True)),
)

text_plate = moz.linear_extrude(moz.square(30, center=True), height=2, center=True)

shape = moz.union(
    moz.translate([0, 0, 0], body),
    moz.translate([60, 0, 20], text_plate),
)
shape.export("binstl", os.path.join(OUT, "basic_logo_and_text.stl"))
print("basic_logo_and_text ok:", shape.dimension)
