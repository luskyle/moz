"""OpenSCAD examples/Basics/logo_and_text.scad 的 Python 版本。

原文件用 use <logo.scad> 引入 Logo() 模块；Python 版直接复用 logo.py 里的 logo()
（同一个模块定义），并把原文件设置的 $vpr/$vpt/$vpd 一并带上，让渲染视角与原文件一致。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import moz_openscad as moz
from logo import logo

# 原文件的视口设置（只影响相机，不影响几何）
VIEWPORT = {"$vpr": [90, 0, 0], "$vpt": [300, 0, 80], "$vpd": 1600}

LOGOSIZE = 120


def t(text, s=18, style=":style=Bold", spacing=1):
    """带正确字体与朝向的 3D 文字助手。"""
    return moz.rotate([90, 0, 0], moz.linear_extrude(
        moz.text(text, size=s, spacing=spacing, font="Liberation Sans" + style, fn=16),
        height=1,
    ))


def build():
    return moz.settings(
        moz.translate([110, 0, 80], moz.union(
            moz.translate([0, 0, 30], moz.rotate([25, 25, -40], logo(LOGOSIZE))),
            moz.translate([100, 0, 40], moz.color(t("Open", 42, spacing=1.05), [157 / 255, 203 / 255, 81 / 255])),
            moz.translate([247, 0, 40], moz.color(t("SCAD", 42, spacing=0.9), [249 / 255, 210 / 255, 44 / 255])),
            moz.translate([100, 0, 0], moz.color(t("The Programmers"), [0, 0, 0])),
            moz.translate([160, 0, -30], moz.color(t("Solid 3D CAD Modeller"), [0, 0, 0])),
        )),
        **VIEWPORT,
    )


if __name__ == "__main__":
    build().show(title="moz - Basics/logo_and_text")