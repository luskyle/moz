"""examples/Old/example024.scad 的忠实 Python 移植（Menger Sponge）。"""

import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 海绵体的边长
D = 100
# 分形迭代层数
n = 3


def menger():
    return moz.difference(
        moz.cube(D, center=True),
        # for (v=[[0,0,0], [0,0,90], [0,90,0]]) rotate(v) menger_negative(side=D, maxside=D, level=n);
        # for 循环是一个 group，作为 difference 的单个子对象参与运算。
        moz.union(*[moz.rotate(v, menger_negative(side=D, maxside=D, level=n))
                    for v in ([0, 0, 0], [0, 0, 90], [0, 90, 0])]),
    )


def menger_negative(side=1, maxside=1, level=1):
    l = side / 3

    parts = [moz.cube([maxside * 1.1, l, l], center=True)]
    if level > 1:
        # for (i=[-1:1], j=[-1:1]) if (i || j) translate(...) ...
        # 这里的 if / for 在原文件里都是 group，整体作为模块体的第二个子对象。
        parts.append(moz.union(*[
            moz.translate([0, i * l, j * l],
                          menger_negative(side=l, maxside=maxside, level=level - 1))
            for i in (-1, 0, 1)
            for j in (-1, 0, 1)
            if i or j
        ]))

    return moz.union(*parts)


def build():
    return moz.difference(
        moz.rotate([45, moz.atan_deg(1 / math.sqrt(2)), 0], menger()),
        moz.translate([0, 0, -D], moz.cube(2 * D, center=True)),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example024")