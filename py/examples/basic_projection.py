#!/usr/bin/env python3
"""对应 OpenSCAD examples/Basics/projection.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

# 生成一个简单的 3D 物体
base = moz.cube([30, 30, 10], center=True)
# 这里用一个 2D 轮廓做投影示意
shape = moz.projection(base, cut=False)
print("basic_projection dim:", shape.dimension)
shape.export("svg", os.path.join(OUT, "basic_projection.svg"))
