#!/usr/bin/env python3
"""OpenSCAD examples/Basics/linear_extrude.scad 的 Python 对应实现。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

# 2D 轮廓 -> 3D 拉伸
outline = moz.polygon(points=[[-20, 0], [0, 30], [20, 0], [0, -20]])
shape = moz.linear_extrude(outline, height=12, center=True)
shape.export("binstl", os.path.join(OUT, "basic_linear_extrude.stl"))
print("basic_linear_extrude ok:", shape.dimension)
