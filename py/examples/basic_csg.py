#!/usr/bin/env python3
"""对应 OpenSCAD examples/Basics/CSG.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

left = moz.translate([-24, 0, 0], moz.union(moz.cube(15, center=True), moz.sphere(10)))
center = moz.intersection(moz.cube(15, center=True), moz.sphere(10))
right = moz.translate([24, 0, 0], moz.difference(moz.cube(15, center=True), moz.sphere(10)))

shape = moz.union(left, center, right)
shape.export("binstl", os.path.join(OUT, "basic_csg.stl"))
print("basic_csg ok:", shape.dimension)
