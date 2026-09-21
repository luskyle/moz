"""OpenSCAD examples/Advanced/animation.scad 的 Python 版本。

原文件靠 $t 做动画（GUI 的 View->Animate）；非动画场景下 $t 默认是 0，所以
build() 默认给出第 0 帧，t 可以传参。

原文件里的 plate() 整体带 % 修饰符（背景对象），只出现在预览里、不进入最终几何，
因此不放进 build() 的返回值；对应的 position()/curve() 仍按原样保留。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 两段臂长，改动可以看到机械臂姿态变化
ARM1_LENGTH = 70
ARM2_LENGTH = 50

r = 2


def position(t):
    """机械臂末端随时间走过的 X/Y 轨迹（t 取值 [0..1]）。"""
    if t < 0.5:
        return [200 * t - 50, 30 * moz.sin_deg(5 * 360 * t) + 60]
    return [50 * moz.cos_deg(360 * (t - 0.5)), 100 * -moz.sin_deg(360 * (t - 0.5)) + 60]


def sq(x, y):
    return x * x + y * y


def ang_b(x, y, l1, l2):
    return 180 - moz.acos_deg((l2 * l2 + l1 * l1 - sq(x, y)) / (2 * l1 * l2))


def ang2(x, y, l1, l2):
    return (90 - moz.acos_deg((l2 * l2 - l1 * l1 + sq(x, y)) / (2 * l2 * math.sqrt(sq(x, y))))
            - moz.atan2_deg(x, y))


def ang1(x, y, l1, l2):
    return ang2(x, y, l1, l2) + ang_b(x, y, l1, l2)


def segment(col, length):
    return moz.color(
        moz.hull(moz.sphere(r), moz.translate([length, 0, 0], moz.sphere(r))),
        col,
    )


def arm(x, y, l1, l2):
    a1 = ang1(x, y, l1, l2)
    a2 = ang2(x, y, l1, l2)
    return moz.union(
        moz.sphere(r=2 * r),
        moz.cylinder(r=2, h=6 * r, center=True),
        moz.rotate([0, 0, a1], segment("red", l1)),
        moz.translate([l1 * moz.cos_deg(a1), l1 * moz.sin_deg(a1), 0], moz.union(
            moz.sphere(r=2 * r),
            moz.rotate([0, 0, a2], segment("green", l2)),
        )),
        moz.translate([x, y, -r / 2], moz.cylinder(r1=0, r2=r, h=4 * r, center=True)),
    )


def curve():
    """末端轨迹曲线（原文件只用于 % 背景挡板，这里按原样保留）。"""
    points = []
    a = 0.0
    while a <= 1.0:
        points.append(position(a))
        a += 0.004
    return moz.polygon(points)


def plate():
    """% 背景挡板：带 % 修饰符，只用于预览，不参与 F6 / 导出。"""
    return moz.translate([0, 0, -3 * r], moz.union(
        moz.translate([0, 25, 0], moz.cube([150, 150, 0.1], center=True)),
        moz.color(moz.linear_extrude(moz.difference(curve(), moz.offset(curve(), -1)), height=0.1), "Black"),
    ))


def build(t=0.0):
    pos = position(t)
    return moz.settings(arm(pos[0], pos[1], ARM1_LENGTH, ARM2_LENGTH), fn=30)


if __name__ == "__main__":
    build().show(title="moz - Advanced/animation")