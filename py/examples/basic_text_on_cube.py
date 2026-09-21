#!/usr/bin/env python3
"""OpenSCAD examples/Basics/text_on_cube.scad 的 Python 对应实现。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

label = moz.linear_extrude(moz.square(20, center=True), height=2, center=True)
base = moz.Box((40, 40, 8), center=True)
shape = moz.union(base, moz.translate([0, 0, 6], label))
shape.export("binstl", os.path.join(OUT, "basic_text_on_cube.stl"))
print("basic_text_on_cube ok:", shape.dimension)
