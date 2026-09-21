#!/usr/bin/env python3
"""OpenSCAD examples/Basics/CSG-modules.scad 的 Python 对应实现。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

# 以 Python 的对象组合替代 OpenSCAD 模块式组合
left = moz.translate([-20, 0, 0], moz.union(moz.cube(12, center=True), moz.sphere(8)))
right = moz.translate([20, 0, 0], moz.difference(moz.cube(12, center=True), moz.sphere(8)))
shape = moz.union(left, right)
shape.export("binstl", os.path.join(OUT, "basic_csg_modules.stl"))
print("basic_csg_modules ok:", shape.dimension)
