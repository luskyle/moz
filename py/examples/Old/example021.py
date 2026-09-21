"""examples/Old/example021.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def thing():
    """module thing()：模块体开头的 $fa = 30; 用块作用域复现。"""
    return moz.settings(moz.difference(
        moz.sphere(r=25),
        moz.cylinder(h=62.5, r1=12.5, r2=6.25, center=True),
        moz.rotate(90, [1, 0, 0], moz.cylinder(h=62.5, r1=12.5, r2=6.25, center=True)),
        moz.rotate(90, [0, 1, 0], moz.cylinder(h=62.5, r1=12.5, r2=6.25, center=True)),
    ), fa=30)


def demo_proj():
    # 原文件里还有一个 % thing(); 背景对象，不参与 F6 导出，故不放进 build() 的返回值。
    return moz.linear_extrude(moz.projection(thing(), cut=False), center=True, height=0.5)


def demo_cut():
    # for (i = [-20:5:+20]) { ... } 是一个 group，在模块体里是 union 的单个子对象。
    cuts = []
    i = -20
    while i <= 20:
        cuts.append(moz.rotate(-30, [1, 1, 0],
            moz.translate([0, 0, -i],
                moz.linear_extrude(
                    moz.projection(
                        moz.translate([0, 0, i], moz.rotate(+30, [1, 1, 0], thing())),
                        cut=True),
                    center=True, height=0.5))))
        i += 5
    # 原文件里还有一个 % thing(); 背景对象，不参与 F6 导出。
    return moz.union(*cuts)


def build():
    return moz.union(
        moz.translate([-30, 0, 0], demo_proj()),
        moz.translate([+30, 0, 0], demo_cut()),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example021")