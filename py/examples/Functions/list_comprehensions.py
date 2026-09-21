"""OpenSCAD examples/Functions/list_comprehensions.scad 的 Python 版本。

原文件用列表推导生成多边形顶点；SCAD 的 cos/sin 以度为单位且精度处理特殊，
所以顶点计算统一用 moz.cos_deg / moz.sin_deg（与引擎逐一比特一致）。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def ngon(num, radius):
    return moz.polygon([
        [radius * moz.cos_deg(i * 360 / num), radius * moz.sin_deg(i * 360 / num)]
        for i in range(num)
    ])


def rounded_ngon(num, radius, rounding=0):
    step = 360 / num

    def vertex(a):
        v = math.floor((a + step / 2) / step) * step
        return [(radius - rounding) * moz.cos_deg(v), (radius - rounding) * moz.sin_deg(v)]

    points = []
    for a in range(360):
        base = vertex(a)
        points.append([base[0] + rounding * moz.cos_deg(a), base[1] + rounding * moz.sin_deg(a)])
    return moz.polygon(points)


def star(num, radii):
    return moz.polygon([
        [radii[i % len(radii)] * moz.cos_deg(i * 360 / num),
         radii[i % len(radii)] * moz.sin_deg(i * 360 / num)]
        for i in range(num)
    ])


def build():
    return moz.union(
        ngon(3, 10),
        moz.translate([20, 0], ngon(6, 8)),
        moz.translate([36, 0], ngon(10, 6)),
        moz.translate([0, 22], rounded_ngon(3, 10, 5)),
        moz.translate([20, 22], rounded_ngon(6, 8, 4)),
        moz.translate([36, 22], rounded_ngon(10, 6, 3)),
        moz.translate([0, 44], star(20, [6, 10])),
        moz.translate([20, 44], star(40, [6, 8, 8, 6])),
        moz.translate([36, 44], star(30, [3, 4, 5, 6, 5, 4])),
    )


if __name__ == "__main__":
    build().show(title="moz - Functions/list_comprehensions")