#!/usr/bin/env python3
"""对应 OpenSCAD examples/Advanced/offset.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

foot_height = 20
rounded = moz.linear_extrude(moz.offset(moz.square(50, center=True), 10), height=foot_height, scale=0.5)
outline = moz.linear_extrude(moz.offset(moz.circle(15), 2).difference(moz.offset(moz.circle(15), -2)), height=20)

shape = moz.union(rounded, moz.translate([0, 0, foot_height], outline))
shape.export("binstl", os.path.join(OUT, "basic_offset.stl"))
print("basic_offset ok:", shape.dimension)
