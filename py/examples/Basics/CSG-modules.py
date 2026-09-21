"""OpenSCAD examples/Basics/CSG-modules.scad 的 Python 版本。

原文件用 debug 开关附带一组辅助几何（用于看清 CSG 的中间过程）；debug = true 时
这些辅助体也是最终几何的一部分，所以 Python 版同样默认包含。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 改成 False 就去掉辅助几何
DEBUG = True

# 全局分辨率
FS = 0.1  # 不要生成小于 0.1mm 的片段
FA = 5    # 不要生成大于 5 度的片段


def body():
    return moz.color(moz.sphere(10), "Blue")


def intersector():
    return moz.color(moz.cube(15, center=True), "Red")


def hole_object():
    return moz.color(moz.cylinder(h=20, r=5, center=True), "Lime")


def intersected():
    return moz.intersection(body(), intersector())


def hole_a():
    return moz.rotate([0, 90, 0], hole_object())


def hole_b():
    return moz.rotate([90, 0, 0], hole_object())


def hole_c():
    return hole_object()


def holes():
    return moz.union(hole_a(), hole_b(), hole_c())


def line():
    return moz.color(moz.cylinder(r=1, h=10, center=True), "Black")


def helpers():
    def at(vector, *children):
        return moz.translate(vector, moz.union(*children))

    return moz.scale([0.5, 0.5, 0.5], moz.union(
        at([-30, 0, -40],
           intersected(),
           at([-15, 0, -35], body()),
           at([15, 0, -35], intersector()),
           at([-7.5, 0, -17.5], moz.rotate([0, 30, 0], line())),
           at([7.5, 0, -17.5], moz.rotate([0, -30, 0], line()))),
        at([30, 0, -40],
           holes(),
           at([-10, 0, -35], hole_a()),
           at([10, 0, -35], hole_b()),
           at([30, 0, -35], hole_c()),
           at([5, 0, -17.5], moz.rotate([0, -20, 0], line())),
           at([-5, 0, -17.5], moz.rotate([0, 30, 0], line())),
           at([15, 0, -17.5], moz.rotate([0, -45, 0], line()))),
        at([-20, 0, -22.5], moz.rotate([0, 45, 0], line())),
        at([20, 0, -22.5], moz.rotate([0, -45, 0], line())),
    ))


def build():
    parts = [moz.difference(moz.intersection(body(), intersector()), holes())]
    if DEBUG:
        parts.append(helpers())
    return moz.settings(moz.union(*parts), fs=FS, fa=FA)


if __name__ == "__main__":
    build().show(title="moz - Basics/CSG-modules")