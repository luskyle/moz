"""examples/Old/example019.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

PAIRS = [
    [-200, 5],
    [-50, 20],
    [-20, 18],
    [+80, 25],
    [+150, 2],
]


def get_cylinder_h(p):
    """function get_cylinder_h(p) = lookup(p, [...]);"""
    return moz.lookup(p, PAIRS)


def build():
    # for (i = [-100:5:+100])：SCAD 的区间是按 i += step 累加的，用 while 复刻。
    cylinders = []
    i = -100.0
    while i <= 100:
        cylinders.append(moz.translate([i, 0, -30],
                                       moz.cylinder(r1=6, r2=2, h=get_cylinder_h(i) * 3)))
        i += 5

    return moz.union(*cylinders)


if __name__ == "__main__":
    build().show(title="moz - Old/example019")