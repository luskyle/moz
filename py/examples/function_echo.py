#!/usr/bin/env python3
"""对应 OpenSCAD examples/Functions/echo.scad 的 Python 版本。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz


def f1(x, y):
    print(f"f1: x={x}, y={y}")
    return 0.5 * x * x + 4 * y + 1


def f2(x):
    y = x ** 3
    print(f"f2: y={y}")
    return y


def f3(x):
    y = x * x - 5
    print(f"f3: {y}")
    return y

r1 = f1(3, 5)
r2 = f2(4)
r3 = f3(5)
print("echo example values:", r1, r2, r3)

shape = moz.cube(2, center=True)
shape.export("binstl", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out", "function_echo.stl"))
