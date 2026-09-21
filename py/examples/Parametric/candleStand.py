"""OpenSCAD examples/Parametric/candleStand.scad 的 Python 版本。

参数集来自原文件同目录的 candleStand.json（OpenSCAD customizer 的参数集），
所以 build(parameter_set="small") 之类可以直接复现界面里的预设。

原文件顶部的 ``//[..]`` 注释是 customizer 的取值声明，这里只记进文档字符串：
    length = 50;      // [70:large, 50:medium, 30:small]
    radius = 25;
    count = 7;        // [3:14]
    centerCandle = true;
    candleSize = 7; width = 4; holeSize = 3;
    CenterCandleWidth = 4; heightOfSupport = 3; widthOfSupport = 3;
    heightOfRing = 4; widthOfRing = 23;
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

PARAMETER_FILE = ROOT / "3rd" / "openscad" / "examples" / "Parametric" / "candleStand.json"

# 原文件里的默认值
DEFAULTS = {
    "length": 50,
    "radius": 25,
    "count": 7,
    "centerCandle": True,
    "candleSize": 7,
    "width": 4,
    "holeSize": 3,
    "CenterCandleWidth": 4,
    "heightOfSupport": 3,
    "widthOfSupport": 3,
    "heightOfRing": 4,
    "widthOfRing": 23,
}


def parameter_sets():
    """读取 candleStand.json 里的参数集（键 → {参数名: 字符串值}）。"""
    with open(PARAMETER_FILE, encoding="utf-8") as handle:
        return json.load(handle)["parameterSets"]


def _coerce_raw(value):
    """customizer 的参数集里数字/布尔都是字符串，按原类型还原。"""
    text = str(value)
    if text in ("true", "false"):
        return text == "true"
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number


def make_ring_of(radius, count, child):
    """把一个子对象按圆周摆 count 份（角度按度算，与原文件一致）。"""
    return moz.union(*[
        moz.translate([radius * moz.cos_deg(angle), -radius * moz.sin_deg(angle), 0], child)
        for angle in [a * 360 / count for a in range(count)]
    ])


def make(v, radius, count, candle_size, length):
    """带烛台座的环。原模块体里设了 $fa = 0.5、$fs = 0.5。"""
    spokes = moz.union(*[
        moz.rotate([0, 0, a * 360 / count], moz.translate(
            [0, -v["width"] / 2, 0],
            moz.cube([radius, v["widthOfSupport"], v["heightOfSupport"]])))
        for a in range(count)
    ])

    body = moz.union(
        make_ring_of(radius, count, moz.cylinder(candle_size, r=v["width"], fa=0.5, fs=0.5)),
        spokes,
        moz.linear_extrude(
            moz.difference(
                moz.circle(radius, fa=0.5, fs=0.5),
                moz.circle(v["widthOfRing"], fa=0.5, fs=0.5),
            ),
            height=v["heightOfRing"], convexity=2, fa=0.5, fs=0.5),
    )

    holes = make_ring_of(radius, count, moz.cylinder(candle_size + 1, r=v["holeSize"], fa=0.5, fs=0.5))
    return moz.difference(body, holes)


def build(parameter_set=None, **overrides):
    values = dict(DEFAULTS)
    if parameter_set is not None:
        values.update({k: _coerce_raw(v) for k, v in parameter_sets()[parameter_set].items()})
    values.update(overrides)

    length = values["length"]
    width = values["width"]
    radius = values["radius"]
    count = values["count"]
    candle_size = values["candleSize"]

    # 中心支柱：原文件写的是 cylinder(length, width-2)，第二个位置参数是 r1，
    # r2 不给时引擎按 1 处理（也就是一个圆台），不能写成 r=
    stand = moz.cylinder(length, r1=width - 2)

    # 中心蜡烛：原文件在 difference 块里写了 $fn = 360
    if values["centerCandle"]:
        candle = moz.difference(
            moz.cylinder(candle_size, r=values["CenterCandleWidth"], fn=360),
            moz.cylinder(candle_size + 1, r=values["CenterCandleWidth"] - 2, fn=360),
        )
    else:
        candle = moz.sphere(values["CenterCandleWidth"])

    # 环 + 烛台座的底盖
    ring = moz.union(
        make(values, radius, count, candle_size, length),
        make_ring_of(radius, count, moz.cylinder(1, r=width)),
    )

    # 底座辐条
    base = moz.union(*[
        moz.rotate([0, 0, a * 360 / count], moz.translate(
            [0, -width / 2, 0],
            moz.cube([radius, values["widthOfSupport"], values["heightOfSupport"]])))
        for a in range(count)
    ])

    return moz.union(
        stand,
        moz.translate([0, 0, length - candle_size / 2], candle),
        moz.translate([0, 0, length - candle_size / 2], ring),
        base,
    )


if __name__ == "__main__":
    build().show(title="moz - Parametric/candleStand")