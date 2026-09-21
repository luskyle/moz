#!/usr/bin/env python3
"""对应 OpenSCAD examples/Functions/functions.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)


def f(x):
    return 0.5 * x + 1

objs = []
for a in range(-100, 101, 5):
    pos = [a, f(a), 0]
    objs.append(moz.translate(pos, moz.cube(2, center=True)))

combined = moz.union(*objs)
combined.export("binstl", os.path.join(OUT, "basic_functions.stl"))
print("basic_functions ok:", combined.dimension)
