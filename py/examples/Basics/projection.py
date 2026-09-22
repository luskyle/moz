"""OpenSCAD examples/Basics/projection.scad 的 Python 版本。

投影的原始三维形体来自同目录的 projection.stl（原文件里 import("projection.stl")），
该文件已随包复制到 moz_data/examples/Basics/ 下（与上游同名）。
projection() 不带 cut 得到轮廓投影，带 cut = true 得到 Z = 0 处的剖面。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

PROJECTION_STL = moz.data_path("examples", "Basics", "projection.stl")


def build():
    # 原文件开头还有 %import("projection.stl")：带 %（背景）修饰符，只用于预览、不参与导出
    source = moz.import_shape(PROJECTION_STL)

    front = moz.color(
        moz.translate([0, 0, -20], moz.linear_extrude(
            moz.difference(moz.square(30, center=True), moz.projection(source)),
            height=2, center=True)),
        "red",
    )

    side = moz.color(
        moz.rotate([0, 90, 0], moz.translate([0, 0, -20], moz.linear_extrude(
            moz.difference(moz.square(30, center=True),
                           moz.projection(moz.rotate([0, 90, 0], source))),
            height=2, center=True))),
        "green",
    )

    top = moz.color(
        moz.rotate([-90, 0, 0], moz.translate([0, 0, 20], moz.linear_extrude(
            moz.difference(moz.square(30, center=True),
                           moz.projection(moz.rotate([90, 0, 0], source))),
            height=2, center=True))),
        "cyan",
    )

    cut = moz.color(
        moz.translate([0, 0, 20], moz.linear_extrude(
            moz.difference(moz.square(30, center=True), moz.projection(source, cut=True)),
            height=2, center=True)),
        "yellow", 0.5,
    )

    return moz.union(front, side, top, cut)


if __name__ == "__main__":
    build().show(title="moz - Basics/projection")