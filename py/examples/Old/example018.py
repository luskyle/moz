"""examples/Old/example018.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def step(len_, mod, children):
    """module step(len, mod)：children() → 把子对象当作列表参数传进来。

    原来的参数名是 len，这里写成 len_ 以免遮住 Python 内建 len()。
    """
    count = len(children)
    return moz.union(*[
        moz.translate([len_ * (i - (count - 1) / 2), 0, 0], children[(i + mod) % count])
        for i in range(count)
    ])


def build():
    children = [
        moz.sphere(30),
        moz.cube(60, True),
        moz.cylinder(r=30, h=50, center=True),
        moz.union(
            moz.cube(45, True),
            moz.rotate([45, 0, 0], moz.cube(50, True)),
            moz.rotate([0, 45, 0], moz.cube(50, True)),
            moz.rotate([0, 0, 45], moz.cube(50, True)),
        ),
    ]

    # for (i = [1:4]) ...
    return moz.union(*[
        moz.translate([0, -250 + i * 100, 0], step(100, i, children))
        for i in range(1, 5)
    ])


if __name__ == "__main__":
    build().show(title="moz - Old/example018")