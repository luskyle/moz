#!/usr/bin/env python3
"""OpenSCAD examples/Basics/rotate_extrude.scad 的 Python 对应实现。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

# 2D 轮廓绕中心轴旋转形成 3D 立体
# OpenSCAD 要求该 2D 轮廓必须位于 X 轴的同一侧，避免跨 X 轴导致底层崩溃。
profile = moz.polygon(points=[[0, 0], [8, 4], [4, 8], [4, 12], [12, 16], [0, 20]])
shape = moz.rotate_extrude(profile, angle=270)
shape.export("binstl", os.path.join(OUT, "basic_rotate_extrude.stl"))
print("basic_rotate_extrude ok:", shape.dimension)
