#!/usr/bin/env python3
"""生成 P1 的三张验收样例图纸：``py/moz_data/drawings/{plate,bracket,messy}.dxf``。

三张图覆盖 P1 要吃的关键路径：

- ``plate.dxf``（R12，无单位信息 → 走"按 mm 处理"那条路）：
  8 条 LINE 拼的异形外轮廓（120×40 带 40×20 凸台）+ 4 个圆孔（画在 ``HOLES`` 层，测"显式孔层"路径）
  + 两个命名线性标注 ``bodywidth`` / ``plateheight``（引擎的 ``dxf_dim`` 能按名读到值）。
- ``bracket.dxf``（R2000，``$INSUNITS``=4）：80×50 带 R8 圆角的外轮廓（4 条 LINE + 4 段 ARC）
  + 腰形孔（闭合 LWPOLYLINE 带 **bulge** 半圆端）→ 测圆弧离散与 bulge 展开；
  另有 ``CENTER`` 中心线层、``HIDDEN`` 虚线层（都必须被排除），``DIM`` 层一个命名标注。
- ``messy.dxf``（R2000）：故意脏——顶边留 0.02 mm 缺口（要桥接）、底边/左边重复画（其中一条反向，
  要去重）、另有一条自交（领结）轮廓在 ``CONSTRUCTION`` 构造线层（默认按角色排除，但显式读进来时
  必须出现在诊断报告里）。

**输出可复现**：``$TDUPDATE`` 与两个 GUID 都钉死，重复执行得到逐字节相同的文件。

    python3 scripts/make_dxf_samples.py
"""

import itertools
import logging
import os
import re
import sys

import ezdxf

# R12 没有 $INSUNITS，ezdxf 每次保存都会打一行提示——这是预期行为，不必打扰
logging.getLogger("ezdxf").setLevel(logging.ERROR)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "py", "moz_data", "drawings")

# 钉死时间戳（DXF 头里 $TDUPDATE 是儒略日，不钉就每次不同）
PINNED_TDUPDATE = 2460000.5          # 儒略日（2023-02-25 前后），固定值即可
PINNED_JULIAN = "2460000.5"
TIME_VARS = ("$TDCREATE", "$TDUPDATE", "$TDINDWG", "$TDUSRTIMER")

# ezdxf 写文件时会塞进「版本 @ 当前时间」的注释和若干随机 GUID，保存后统一换成固定值
STAMP_RE = re.compile(r"@ \d{4}-\d{2}-\d{2}T[\d:.]+[+-]\d{2}:\d{2}")
GUID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                     r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
PINNED_STAMP = "@ 2023-02-25T00:00:00+00:00"


def _pin_header(doc, units=None):
    doc.header["$TDUPDATE"] = PINNED_TDUPDATE
    if units is not None:
        doc.header["$INSUNITS"] = units


def _normalize(path):
    """把时间戳与随机 GUID 换成固定值——否则每次生成都得到不同的字节。

    ezdxf 在保存时会把头里的 ``$TDCREATE``/``$TDUPDATE``（儒略日）与两个计时变量刷成
    当前时间，还会写「版本 @ 当前时间」的注释和若干随机 GUID，所以保存后统一改成固定值。
    时间变量按 DXF 的「组码 9 变量名 + 下一行的值」成对识别，避免误改其它组码 40 的值。
    """
    with open(path, encoding="utf-8", errors="surrogateescape") as handle:
        lines = handle.read().split("\n")

    last_name = None
    for index in range(len(lines) - 1):
        if lines[index].strip() == "9":
            last_name = lines[index + 1].strip()
        elif lines[index].strip() == "40" and last_name in TIME_VARS:
            lines[index + 1] = PINNED_JULIAN if last_name in ("$TDCREATE", "$TDUPDATE") else "0.0"

    counter = itertools.count(1)
    text = "\n".join(lines)
    text = STAMP_RE.sub(PINNED_STAMP, text)
    text = GUID_RE.sub(lambda _match: f"{{00000000-0000-0000-0000-{next(counter):012d}}}", text)
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(text)


def _named_linear_dim(msp, p1, p2, name, base=None, angle=0.0):
    """带名字的线性标注：名字写在 DIMENSION 的 group 1（就是引擎 dxf_dim 认的那一列）。"""
    if base is None:
        base = (min(p1[0], p2[0]), min(p1[1], p2[1]) - 12.0)
    dim = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=name,
                             dxfattribs={"layer": "DIM"})
    dim.render()
    return dim


def make_plate(path):
    """120×40 带 40×20 凸台的板 + 4 个 r5 孔，R12（老图通常没有单位信息）。"""
    doc = ezdxf.new("R12", setup=False)
    _pin_header(doc)
    msp = doc.modelspace()

    outline = [(0, 0), (120, 0), (120, 40), (80, 40), (80, 60), (40, 60), (40, 40), (0, 40)]
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("HOLES", color=1)
    doc.layers.add("DIM", color=3)
    for start, end in zip(outline, outline[1:] + outline[:1], strict=False):
        msp.add_line(start, end, dxfattribs={"layer": "OUTLINE"})
    for center in [(20, 20), (55, 20), (100, 20), (60, 50)]:
        msp.add_circle(center, radius=5.0, dxfattribs={"layer": "HOLES"})

    _named_linear_dim(msp, (0, 0), (120, 0), "bodywidth", base=(0, -14))
    _named_linear_dim(msp, (0, 0), (0, 40), "plateheight", base=(-14, 0), angle=90)
    doc.saveas(path)


def make_bracket(path):
    """80×50 圆角外轮廓 + 腰形孔（bulge 半圆端）+ 中心线层 + 虚线层，R2000，单位 mm。"""
    doc = ezdxf.new("R2000", setup=False)
    _pin_header(doc, units=4)
    msp = doc.modelspace()

    for name, color in [("OUTLINE", 7), ("CENTER", 4), ("HIDDEN", 8), ("DIM", 3)]:
        doc.layers.add(name, color=color)

    # 外轮廓：4 条直边 + 4 段 R8 圆角（逆时针，闭合）
    radius = 8.0
    lines = [((radius, 0), (80 - radius, 0)),          # 下
             ((80, radius), (80, 50 - radius)),        # 右
             ((80 - radius, 50), (radius, 50)),        # 上
             ((0, 50 - radius), (0, radius))]          # 左
    for start, end in lines:
        msp.add_line(start, end, dxfattribs={"layer": "OUTLINE"})
    arcs = [((80 - radius, radius), 270, 360),         # 右下
            ((80 - radius, 50 - radius), 0, 90),       # 右上
            ((radius, 50 - radius), 90, 180),          # 左上
            ((radius, radius), 180, 270)]              # 左下
    for center, start_angle, end_angle in arcs:
        msp.add_arc(center, radius=radius, start_angle=start_angle, end_angle=end_angle,
                    dxfattribs={"layer": "OUTLINE"})

    # 腰形孔：30×10 的槽，两端用 bulge = tan(90°/4) = 1 的 180° 半圆
    # （xyseb 格式里每个顶点的第 5 个值是「从该顶点出发那段弧」的 bulge）
    msp.add_lwpolyline([(25, 20, 0, 0, 0.0), (55, 20, 0, 0, 1.0),
                        (55, 30, 0, 0, 0.0), (25, 30, 0, 0, 1.0)],
                       format="xyseb", dxfattribs={"layer": "OUTLINE"}, close=True)

    # 中心线（点划线，必须被排除）+ 虚线（也必须排除）
    msp.add_line((40, 15), (40, 35), dxfattribs={"layer": "CENTER"})
    msp.add_line((20, 25), (60, 25), dxfattribs={"layer": "CENTER"})
    msp.add_line((10, 10), (10, 40), dxfattribs={"layer": "HIDDEN"})

    _named_linear_dim(msp, (0, 0), (80, 0), "bracketwidth", base=(0, -14))
    doc.saveas(path)


def make_messy(path):
    """60×40 的板 + r6 孔，但画得很脏：两遍轮廓（含反向）、0.005 mm 缺口、一条自交轮廓。"""
    doc = ezdxf.new("R2000", setup=False)
    _pin_header(doc, units=4)
    msp = doc.modelspace()

    for name, color in [("OUTLINE", 7), ("HOLES", 1), ("CONSTRUCTION", 5), ("DIM", 3)]:
        doc.layers.add(name, color=color)

    # 唯一一份"真"轮廓：顶边留 0.02 mm 缺口（0→30 与 30.02→60），等修复阶段桥接
    outline = [((0, 0), (60, 0)), ((60, 0), (60, 40)), ((30.02, 40), (60, 40)),
               ((0, 40), (30, 40)), ((0, 40), (0, 0))]
    for start, end in outline:
        msp.add_line(start, end, dxfattribs={"layer": "OUTLINE"})
    # 脏：底边画两遍（其中一遍反向）、左边再画一遍同向——测"反向重复段也要能去重"
    for start, end in [((0, 0), (60, 0)), ((60, 0), (0, 0)), ((0, 0), (0, 40))]:
        msp.add_line(start, end, dxfattribs={"layer": "OUTLINE"})

    msp.add_circle((30, 20), radius=6.0, dxfattribs={"layer": "HOLES"})

    # 自交（领结）轮廓：放在 CONSTRUCTION 构造线层，默认按角色排除，显式读进来时要进诊断报告
    bowtie = [(10, 5), (20, 15), (20, 5), (10, 15)]
    for start, end in zip(bowtie, bowtie[1:] + bowtie[:1], strict=False):
        msp.add_line(start, end, dxfattribs={"layer": "CONSTRUCTION"})

    _named_linear_dim(msp, (0, 0), (60, 0), "messywidth", base=(0, -14))
    doc.saveas(path)


FIXTURES = {
    "plate.dxf": make_plate,
    "bracket.dxf": make_bracket,
    "messy.dxf": make_messy,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, builder in FIXTURES.items():
        path = os.path.join(OUT_DIR, name)
        builder(path)
        _normalize(path)               # 把 ezdxf 写进去的时间戳/GUID 换成固定值
        with open(path, "rb") as handle:
            data = handle.read()
        print(f"{name:12s} {len(data):7d} 字节  -> {os.path.relpath(path, ROOT)}")
    print("\n验收用的解析值（手算，测试里独立复算）：")
    print("  plate   : 外轮廓 5600 mm²（120×40 + 40×20 凸台），孔 4×π5² = 314.16 mm²")
    print("  bracket : 外轮廓 4000-(4-π)8² = 3945.02 mm²，腰形孔 30×10+π5² = 378.54 mm²")
    print("  messy   : 板 2400 mm²（缺口 0.02 桥接后可忽略），孔 π6² = 113.10 mm²，"
          "CONSTRUCTION 层领结自交 1 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
