#!/usr/bin/env python3
"""对应 OpenSCAD examples/Basics/logo.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

size = 50
hole = size / 2
cylinder_height = size * 1.25

positive = moz.sphere(d=size)
negative_1 = moz.cylinder(h=cylinder_height, d=hole, center=True)
negative_2 = moz.rotate([90, 0, 0], moz.cylinder(h=cylinder_height, d=hole, center=True))
negative_3 = moz.rotate([0, 90, 0], moz.cylinder(h=cylinder_height, d=hole, center=True))
logo = moz.difference(positive, negative_1, negative_2, negative_3)
logo.export("binstl", os.path.join(OUT, "basic_logo.stl"))
print("basic_logo ok:", logo.dimension)
