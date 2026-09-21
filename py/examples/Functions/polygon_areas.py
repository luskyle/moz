"""OpenSCAD examples/Functions/polygon_areas.scad 的 Python 版本。

演示「列表推导 + 递归函数 + 用 text() 标注结果」。面积用 Shoelace 公式算，
再按 SCAD 的 round()（四舍五入、.5 远离零）取整后标在图形下方；
顶点与标签里的取整都必须与引擎逐比特一致，所以用 moz.cos_deg / sin_deg 和
scad_round。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def ngon(num, radius):
    return [[radius * moz.cos_deg(i * 360 / num), radius * moz.sin_deg(i * 360 / num)]
            for i in range(num)]


def triarea(v0, v1):
    """以原点为第三个顶点的三角形面积。"""
    return (v0[0] * v1[1] - v0[1] * v1[0]) / 2


def sum_values(values, s=0):
    """原文件里的递归求和：从前往后右结合累加（浮点结果与从左往右不同）。"""
    if s == len(values) - 1:
        return values[s]
    return values[s] + sum_values(values, s + 1)


def area(vertices):
    """Shoelace 公式。"""
    num = len(vertices)
    return sum_values([triarea(vertices[i], vertices[(i + 1) % num]) for i in range(num)])


def scad_round(x):
    """SCAD 的 round()：.5 远离零（Python 内置 round 是银行家舍入）。"""
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def shape_with_area(num, radius):
    return moz.union(
        moz.polygon(ngon(num, radius)),
        moz.translate([0, -20], moz.color(
            moz.text(str(int(scad_round(area(ngon(num, radius))))), halign="center", size=8),
            "Cyan",
        )),
    )


def build():
    labels = moz.translate([0, 20], moz.color(moz.text("Areas:", size=8, halign="center"), "Red"))
    shapes = [moz.translate([x, 0], shape_with_area(num, 10))
              for x, num in zip([-44, -22, 0, 22, 44], [3, 4, 6, 10, 360])]
    return moz.union(labels, *shapes)


if __name__ == "__main__":
    build().show(title="moz - Functions/polygon_areas")