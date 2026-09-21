"""examples/Old/example015.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 原 .scad 与本文件用同一个数据文件（3rd/openscad/examples/Old/ 下），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(__file__).resolve().parents[3] / "3rd" / "openscad" / "examples" / "Old"
DXF = DATA / "example009.dxf"


def shape():
    """module shape()：模块体的多条语句是隐式 union()."""
    return moz.union(
        moz.difference(
            moz.translate([-35, -35],
                moz.intersection(
                    moz.union(
                        moz.difference(moz.square(100, True), moz.square(50, True)),
                        moz.translate([50, 50], moz.square(15, True)),
                    ),
                    moz.rotate(45, moz.translate([0, -15], moz.square([100, 30]))),
                )),
            moz.rotate(-45, moz.scale([0.7, 1.3], moz.circle(5))),
        ),
        moz.import_shape(str(DXF), layer="body", convexity=6, scale=2),
    )


def build():
    # 原文件里 linear_extrude(convexity = 10, center = true) 这一层被注释掉了。
    return shape()


if __name__ == "__main__":
    build().show(title="moz - Old/example015")