"""OpenSCAD examples/Advanced/surface_image.scad 的 Python 版本。

原文件用 surface() 读同目录的高度图表面（像素灰度 → 0..100 的高度），
再沿 Z 方向取 3 层剖面叠起来。外部文件与 .scad 引用的完全是同一个。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# .scad 里写的是相对文件名 surface_image.png（相对它自己所在目录）；
# Python 版直接指向原始示例目录里的同一个文件，不做拷贝。
REPO = Path(__file__).resolve().parents[3]
SURFACE_IMAGE = str(REPO / "3rd" / "openscad" / "examples" / "Advanced" / "surface_image.png")


def build():
    layers = []
    for a in (1, 2, 3):
        layers.append(moz.color(
            moz.linear_extrude(
                moz.projection(
                    moz.translate([0, 0, -30 * a], moz.surface(SURFACE_IMAGE, center=True)),
                    cut=True,
                ),
                height=2 * a,
            ),
            [a / 6 + 0.5, 0, 0],
        ))
    return moz.union(*layers)


if __name__ == "__main__":
    build().show(title="moz - Advanced/surface_image")