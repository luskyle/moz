"""OpenSCAD examples/Parametric/sign.scad 的 Python 版本。

参数集来自原文件同目录的 sign.json（OpenSCAD customizer 的参数集），
所以 build(parameter_set="Congo Sign") 之类可以直接复现界面里的预设。

原文件顶部的 ``//[..]`` 注释是 customizer 的取值声明，这里只记进文档字符串：
    resolution = 10;  // [10, 20, 30, 50, 100]
    radius = 80;      // [60 : 200]
    height = 2;       // [1 : 10]
    Message = "Welcome to...";
    To = "Parametric Designs";
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 与 .scad 同目录的参数集文件
PARAMETER_FILE = ROOT / "3rd" / "openscad" / "examples" / "Parametric" / "sign.json"

# 原文件里的默认值
RESOLUTION = 10
RADIUS = 80
HEIGHT = 2
MESSAGE = "Welcome to..."
TO = "Parametric Designs"


def parameter_sets():
    """读取 sign.json 里的参数集（键 → {参数名: 字符串值}）。"""
    with open(PARAMETER_FILE, encoding="utf-8") as handle:
        return json.load(handle)["parameterSets"]


def _coerce_raw(value):
    """customizer 的参数集里数字也是字符串，按数字还原。"""
    text = str(value)
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number


def build(parameter_set=None, **overrides):
    values = {
        "resolution": RESOLUTION,
        "radius": RADIUS,
        "height": HEIGHT,
        "Message": MESSAGE,
        "To": TO,
    }
    if parameter_set is not None:
        values.update({k: _coerce_raw(v) for k, v in parameter_sets()[parameter_set].items()})
    values.update(overrides)

    radius, height = values["radius"], values["height"]

    # 外椭圆盘：柱体压扁成椭圆，再掏一个浅槽
    disc = moz.scale([1, 0.5], moz.difference(
        moz.cylinder(r=radius, h=2 * height, center=True),
        moz.translate([0, 0, height], moz.cylinder(r=radius - 10, h=height + 1, center=True)),
    ))

    # 文字：原文件写的是 translate([0, --4])，--4 即 4
    plates = moz.linear_extrude(moz.union(
        moz.translate([0, 4], moz.text(values["Message"], halign="center")),
        moz.translate([0, -16], moz.text(values["To"], halign="center")),
    ), height=height)

    # 原文件在文件级写了 $fn = resolution
    return moz.settings(moz.union(disc, plates), fn=values["resolution"])


if __name__ == "__main__":
    build().show(title="moz - Parametric/sign")