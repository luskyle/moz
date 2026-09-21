"""OpenSCAD examples/Advanced/GEB.scad 的 Python 版本。

三个字母各自沿一个轴挤出后取交集，再给三块侧板分别切出对应方向的轮廓投影。
注意原文件里 translate([0, 0, -20]) 是在 rotate 之内、linear_extrude 之外的，
两者的先后顺序不能交换。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

FONT = "Liberation Sans"
# 更好看但不一定装了：FONT = "Bank Gothic"


def g():
    return moz.offset(moz.text("G", size=10, halign="center", valign="center", font=FONT), 0.3)


def e():
    return moz.offset(moz.text("E", size=10, halign="center", valign="center", font=FONT), 0.3)


def b():
    return moz.offset(moz.text("B", size=10, halign="center", valign="center", font=FONT), 0.5)


def geb(fn=64):
    """三个字母各沿一个轴挤出后取交集。原文件在文件级设了 $fn=64，作用到字形曲线细分。"""
    return moz.intersection(
        moz.linear_extrude(b(), height=20, convexity=3, center=True, fn=fn),
        moz.rotate([90, 0, 0], moz.linear_extrude(e(), height=20, convexity=3, center=True, fn=fn)),
        moz.rotate([90, 0, 90], moz.linear_extrude(g(), height=20, convexity=3, center=True, fn=fn)),
    )


def build():
    core = geb()

    bottom = moz.translate([0, 0, -20], moz.linear_extrude(
        moz.difference(moz.square(40, center=True), moz.projection(core)),
        height=1))

    side_a = moz.rotate([90, 0, 0], moz.translate([0, 0, -20], moz.linear_extrude(
        moz.difference(
            moz.translate([0, 0.5], moz.square([40, 39], center=True)),
            moz.projection(moz.rotate([-90, 0, 0], core)),
        ),
        height=1)))

    side_b = moz.rotate([90, 0, 90], moz.translate([0, 0, -20], moz.linear_extrude(
        moz.difference(
            moz.translate([-0.5, 0.5], moz.square([39, 39], center=True)),
            moz.projection(moz.rotate([0, -90, -90], core)),
        ),
        height=1)))

    # 原文件在文件级写了 $fn=64（作用于全部对象，含字形曲线细分）
    return moz.union(
        moz.color(core, "Ivory"),
        moz.color(bottom, "MediumOrchid"),
        moz.color(side_a, "DarkMagenta"),
        moz.color(side_b, "MediumSlateBlue"),
    )


if __name__ == "__main__":
    build().show(title="moz - Advanced/GEB")