"""OpenSCAD examples/Basics/text_on_cube.scad 的 Python 版本。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

FONT = "Liberation Sans"

CUBE_SIZE = 60
LETTER_SIZE = 50
LETTER_HEIGHT = 5

offset = CUBE_SIZE / 2 - LETTER_HEIGHT / 2


def letter(l):
    # text() 本身是 2D 的，用 linear_extrude 变成 3D；原文件这里传了 $fn = 16
    return moz.linear_extrude(
        moz.text(l, size=LETTER_SIZE, font=FONT, halign="center", valign="center", fn=16),
        height=LETTER_HEIGHT,
    )


def build():
    body = moz.union(
        moz.color(moz.cube(CUBE_SIZE, center=True), "gray"),
        moz.translate([0, -offset, 0], moz.rotate([90, 0, 0], letter("C"))),
        moz.translate([offset, 0, 0], moz.rotate([90, 0, 90], letter("U"))),
        moz.translate([0, offset, 0], moz.rotate([90, 0, 180], letter("B"))),
        moz.translate([-offset, 0, 0], moz.rotate([90, 0, -90], letter("E"))),
    )
    # 上下两面用 Unicode 符号（字体缺字时原文件也一样不显示）
    return moz.difference(
        body,
        moz.translate([0, 0, offset], letter("\u263A")),
        moz.translate([0, 0, -offset - LETTER_HEIGHT], letter("\u263C")),
    )


if __name__ == "__main__":
    build().show(title="moz - Basics/text_on_cube")