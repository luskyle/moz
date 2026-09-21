"""OpenSCAD examples/Basics/rotate_extrude.scad 的 Python 版本。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def build():
    # 注意：rotate_extrude 必须在 X 轴正侧或负侧，不能跨轴
    first = moz.color(moz.rotate_extrude(moz.translate([10, 0], moz.square(5))), "red")

    # rotate_extrude 默认用全局 $fn/$fa/$fs，原文件在这里单独传了 $fn = 80
    second = moz.color(
        moz.translate([40, 0, 0], moz.rotate_extrude(moz.text("  J"), fn=80)),
        "cyan",
    )

    # 贴住 X 轴的多边形会得到没有中心孔的实体
    third = moz.color(
        moz.translate([0, 30, 0], moz.rotate_extrude(
            moz.polygon([[0, 0], [8, 4], [4, 8], [4, 12], [12, 16], [0, 20]]),
            fn=80,
        )),
        "green",
    )

    # angle 参数可以做部分旋转：正角度从 X 轴逆时针起，负角度顺时针
    partial = moz.union(
        moz.rotate_extrude(moz.translate([12.5, 0], moz.square(5)), angle=180),
        moz.translate([7.5, 0], moz.rotate_extrude(moz.translate([5, 0], moz.square(5)), angle=180)),
        moz.translate([-7.5, 0], moz.rotate_extrude(moz.translate([5, 0], moz.square(5)), angle=-180)),
    )
    fourth = moz.color(moz.translate([40, 40], partial), "magenta")

    return moz.union(first, second, third, fourth)


if __name__ == "__main__":
    build().show(title="moz - Basics/rotate_extrude")