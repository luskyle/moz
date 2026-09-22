#!/usr/bin/env python3
"""生成 ``py/moz_data/libraries/MCAD/fonts.scad``（自带版权的字形表）。

**为什么要自己生成**：上游 MCAD 的 ``fonts.scad``（Andrew Plumb）是 LGPL 2.1，而项目里
只用到它的 ``8bit_polyfont()``（唯一使用者是 ``Old/example023``）。这里用随引擎一起分发、
SIL OFL 1.1 的 Liberation Sans 重新生成一份**同接口**的字形表：``8bit_polyfont()`` 的
返回值结构、256 项索引、``search()`` 需要的那一列都与上游一致，所以
``use <MCAD/fonts.scad>`` 照常可用，而许可换成 OFL（可商用、无 copyleft）。

输出放在随包分发的数据目录里；引擎会把 ``<资源路径>/libraries`` 加进 SCAD 库搜索路径
（资源路径 = ``py/moz_data``，见 ``py/moz_openscad.py``），因此 ``use <MCAD/fonts.scad>``
不需要额外设 ``OPENSCADPATH``。

只提供 ``8bit_polyfont()``；上游那个文件里的 ``polytext()`` / ``outline_2d()`` /
``braille_*`` 不在这里实现（仓库里没有任何地方用到，需要时请装完整 MCAD 库）。

    python3 scripts/gen_mcad_polyfont.py            # 重新生成（输出可复现）
    python3 scripts/gen_mcad_polyfont.py --check     # 只检查已生成的文件是否与当前脚本一致
"""

import argparse
import os
import sys

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_FONT = os.path.join(
    ROOT, "3rd", "openscad", "fonts", "Liberation-2.00.1", "ttf", "LiberationSans-Regular.ttf"
)
OUT = os.path.join(ROOT, "py", "moz_data", "libraries", "MCAD", "fonts.scad")

CELL = 8.0             # MCAD 的字符格：8×8
CURVE_SAMPLES = 6      # 每段二次贝塞尔采样点数
QUANTUM = 0.02         # 坐标量化步长（太小文件大，太大字形粗糙）
MIN_CONTOUR_AREA = 0.02  # 过滤展开后残留的碎屑轮廓

# 生成后要保证下面这些字符（example023 的钟面用词）字形非空
REQUIRED = "onetwthrfsixvelg"


def _quad(p0, p1, p2):
    out = []
    for i in range(1, CURVE_SAMPLES + 1):
        t = i / CURVE_SAMPLES
        u = 1.0 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def _cubic(p0, p1, p2, p3):
    out = []
    for i in range(1, CURVE_SAMPLES + 1):
        t = i / CURVE_SAMPLES
        u = 1.0 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _quad_segment(prev, args, start):
    """展开 TrueType 的 qCurveTo：连续 off-curve 点之间隐含 on-curve 中点。"""
    points = list(args)
    end = points.pop()
    if end is None:                     # 隐含闭合回轮廓起点
        end = start
    sequence = []
    for index, control in enumerate(points):
        sequence.append((False, control))
        if index + 1 < len(points):
            nxt = points[index + 1]
            sequence.append((True, ((control[0] + nxt[0]) / 2, (control[1] + nxt[1]) / 2)))
    sequence.append((True, end))

    flat = []
    current, pending = prev, None
    for on_curve, point in sequence:
        if not on_curve:
            pending = point
        elif pending is None:
            flat.append(point)
            current = point
        else:
            flat.extend(_quad(current, pending, point))
            current, pending = point, None
    return flat


def contours(pen_ops):
    """把 RecordingPen 的操作展平成轮廓点表（每条闭合轮廓一个点表）。"""
    out = []
    current = []
    start = None
    for op, args in pen_ops:
        if op == "moveTo":
            if len(current) >= 3:
                out.append(current)
            start = args[0]
            current = [start]
        elif op == "lineTo":
            current.append(args[0])
        elif op == "qCurveTo":
            current.extend(_quad_segment(current[-1], args, start))
        elif op == "curveTo":
            current.extend(_cubic(current[-1], args[0], args[-1]))
        elif op == "closePath":
            if len(current) >= 3:
                out.append(current)
            current = []
    if len(current) >= 3:
        out.append(current)
    return out


def _shoelace(points):
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def caret(code):
    """MCAD 那一列（search() 靠它按字符找字形）的写法。"""
    if 32 <= code < 127:
        return chr(code)
    if code < 32:
        return "^" + chr(64 + code)
    if code == 127:
        return "^?"
    if code >= 160:
        return chr(code)
    return ""


def scad_string(text):
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def format_points(points):
    if not points:
        return "[]"
    chunks = []
    for index in range(0, len(points), 10):
        group = ",".join(f"[{x:g},{y:g}]" for x, y in points[index:index + 10])
        chunks.append(group)
    return "[\n\t" + "\n\t,".join(chunks) + "\n\t]"


def format_entry(code, points, paths, first=False):
    prefix = "  " if first else "  ,"       # 表体第一项不带前导逗号（同上游写法）
    head = f'{prefix}[{code:3d},{scad_string(caret(code))},{scad_string(caret(code))},"","",[[0,0],[8,8]]'
    if not points:
        return head + ",[]]"
    path_text = ",".join("[" + ",".join(str(i) for i in path) + "]" for path in paths)
    return head + ",[\n\t" + format_points(points) + "\n\t,[" + path_text + "]\n\t]]"


def build_table():
    font = TTFont(SOURCE_FONT)
    glyph_set = font.getGlyphSet()
    mapping = font.getBestCmap()

    def glyph_name_of(code):
        char = caret(code)
        # 控制字符的写法是 "^A" 这类两字符记号，不是内容字符，没有字形可取
        return char if len(char) == 1 else None

    # 先量出所有字形轮廓的实际纵向范围：按 typo ascender 映射会让带重音的字形探出格子
    raw = {}
    low, high = 0.0, 0.0
    for code in range(256):
        char = glyph_name_of(code)
        name = mapping.get(ord(char)) if char else None
        if not name:
            raw[code] = []
            continue
        pen = RecordingPen()
        glyph_set[name].draw(pen)
        flat = contours(pen.value)
        raw[code] = flat
        for contour in flat:
            for _, y in contour:
                low, high = min(low, y), max(high, y)

    unit = CELL / (high - low)

    def to_cell(x, y):
        return (round(round(x * unit / QUANTUM) * QUANTUM, 4),
                round(round((y - low) * unit / QUANTUM) * QUANTUM, 4))

    entries = []
    for code in range(256):
        points, paths = [], []
        for contour in raw[code]:
            mapped = []
            for x, y in contour:
                cell = to_cell(x, y)
                if not mapped or mapped[-1] != cell:
                    mapped.append(cell)
            if len(mapped) > 1 and mapped[0] == mapped[-1]:
                mapped.pop()                  # path 本来就闭合，去掉重复的收尾点
            if len(mapped) < 3 or _shoelace(mapped) < MIN_CONTOUR_AREA:
                continue
            start = len(points)
            points.extend(mapped)
            paths.append(list(range(start, start + len(mapped))))
        entries.append((code, points, paths))
    return entries, (low, high, unit)


def render(entries):
    lines = [
        "// 8bit_polyfont()：moz 自带的字形表（生成文件，别手改）",
        "//",
        "// 上游 MCAD 的 fonts.scad 是 LGPL 2.1，本项目只用得到它的 8bit_polyfont()，",
        "// 于是用随引擎一起分发、SIL OFL 1.1 的 Liberation Sans 重新生成了这份同接口实现：",
        "// 返回结构、256 项索引、search() 用的那一列都与上游一致，所以 use <MCAD/fonts.scad>",
        "// 照常可用，许可换成 OFL（可商用、无 copyleft）。字形轮廓数据本身按 OFL 1.1 授权。",
        "//",
        "// 只提供 8bit_polyfont()；上游那个文件里的 polytext()/outline_2d()/braille_* 没有实现",
        "// （仓库里没有任何地方用到）。",
        "//",
        "// 重新生成：python3 scripts/gen_mcad_polyfont.py",
        "",
        "function 8bit_polyfont(dx=0.1,dy=0.1) = [",
        '  [8,8,0,"fixed"]',
        '  ,["Decimal Byte","Caret Notation","Character Escape Code","Abbreviation","Name",'
        '"Bound Box","[points,paths]"]',
        "  ,[",
    ]
    for index, (code, points, paths) in enumerate(entries):
        lines.append(format_entry(code, points, paths, first=(index == 0)))
    lines.append("  ]")
    lines.append("];")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只检查已生成的文件是否现行")
    args = parser.parse_args(argv)

    entries, (low, high, unit) = build_table()
    text = render(entries)

    # 纵向必须落在格子里（决定行距）；横向允许一点点出格——真字体本来就带外悬
    # （'_' 在基线下沿伸出、'j' 左端外悬），上限按 0.5 单位留够。
    spilled = [(code, x, y) for code, points, _ in entries for x, y in points
               if not (-0.5 <= x <= CELL + 0.5 and -0.01 <= y <= CELL + 0.01)]
    if spilled:
        raise SystemExit(f"字形超出 {CELL:g}×{CELL:g} 格子：{spilled[:3]}")

    empty_required = [c for c in REQUIRED if not entries[ord(c)][1]]
    if empty_required:
        raise SystemExit(f"这些字符没生成出字形：{''.join(empty_required)}")

    if args.check:
        with open(OUT, encoding="utf-8") as handle:
            current = handle.read()
        if current != text:
            raise SystemExit(f"{os.path.relpath(OUT, ROOT)} 与当前脚本不一致，请重新生成")
        print(f"{os.path.relpath(OUT, ROOT)} 与脚本一致")
        return 0

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    filled = sum(1 for _, points, _ in entries if points)
    print(f"源字体  : {os.path.relpath(SOURCE_FONT, ROOT)}（OFL 1.1）")
    print(f"度量    : 基线 y={(-low) * unit:.2f}，字高上限 y={(high - low) * unit:.2f}（= 格子高）")
    print(f"字形    : {filled}/256 项有点表；输出 {os.path.relpath(OUT, ROOT)}  {len(text.encode())} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
