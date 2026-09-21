#!/usr/bin/env python3
"""对应 OpenSCAD examples/Functions/list_comprehensions.scad 的 Python 版本。"""

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)


def ngon(num, r):
    pts = []
    for i in range(num):
        a = i * 360 / num
        pts.append([r * math.cos(math.radians(a)), r * math.sin(math.radians(a))])
    return moz.polygon(pts)

shape = moz.union(
    ngon(3, 10),
    moz.translate([20, 0], ngon(6, 8)),
    moz.translate([36, 0], ngon(10, 6)),
)
shape.export("svg", os.path.join(OUT, "function_list_comprehensions.svg"))
print("function_list_comprehensions ok:", shape.dimension)
