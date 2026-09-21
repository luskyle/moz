#!/usr/bin/env python3
"""OpenSCAD examples/Basics/LetterBlock.scad 的 Python 对应实现。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import moz_openscad as moz

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "out")
os.makedirs(OUT, exist_ok=True)

base = moz.Box((50, 10, 10), center=True)
center_block = moz.Box((12, 30, 12), center=True)
shape = moz.union(base, moz.translate([0, 0, 12], center_block))
shape.export("binstl", os.path.join(OUT, "basic_letter_block.stl"))
print("basic_letter_block ok:", shape.dimension)
