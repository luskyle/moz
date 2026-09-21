"""OpenSCAD examples/Basics/logo.scad 的 Python 版本（module、顶层变量、$fn 用法）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def logo(size=50, fn=100):
    # 模块参数 $fn 会影响模块内所有对象，也可以在实例化时覆盖
    hole = size / 2
    cylinder_height = size * 1.25

    # 一个正形体（球）+ 三个负形体（圆柱）；原文件里其中一个圆柱带 # 高亮，仅影响预览
    return moz.difference(
        moz.sphere(d=size, fn=fn),
        moz.cylinder(d=hole, h=cylinder_height, center=True, fn=fn),
        moz.rotate([90, 0, 0], moz.cylinder(d=hole, h=cylinder_height, center=True, fn=fn)),
        moz.rotate([0, 90, 0], moz.cylinder(d=hole, h=cylinder_height, center=True, fn=fn)),
    )


def build():
    return logo(50)


if __name__ == "__main__":
    build().show(title="moz - Basics/logo")