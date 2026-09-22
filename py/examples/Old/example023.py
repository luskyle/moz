"""OpenSCAD examples/Old/example023.scad 的 Python 版本：用字形表排钟面。

原文件的 ``use <MCAD/fonts.scad>`` 引入 OpenSCAD 的独立库 MCAD（不在 OpenSCAD 源码包
里，需要单独取）。随包分发的 moz_data/libraries/MCAD/fonts.scad 是一份**自研的 drop-in
实现**（只提供 ``8bit_polyfont()``，由 scripts/gen_mcad_polyfont.py 从随引擎分发的 OFL
字体生成，见 docs/third-party.md），所以原文件能直接跑；上游那份是 LGPL 2.1。

Python 版不做数据拷贝：字形表由引擎自己求值 ``use <...> 8bit_polyfont()`` 拿到
（全精度），再按原文件的排版公式摆放 12 个小时单词。原文件用 SCAD 的
``search(hours[i], thisFont[2], 1, 1)`` 查字形（字符串按逐字符匹配），这里按同一判据扫描。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 引擎会自动把 <资源>/libraries 加进库搜索路径，这里仍用绝对路径 use，不依赖它
MCAD_FONTS = Path(moz.data_path("libraries", "MCAD", "fonts.scad"))

HOURS = ["one", "two", "three", "four", "five", "six",
         "seven", "eight", "nine", "ten", "eleven", "twelve"]


def font_table():
    """取出 MCAD 的 8bit_polyfont() 字形表（用绝对路径 use，不依赖库搜索路径）。"""
    if not MCAD_FONTS.exists():
        raise FileNotFoundError(
            f"缺少字形库 {MCAD_FONTS}；它随包分发在 moz_data/libraries/MCAD/ 下，"
            f"重新生成见 scripts/gen_mcad_polyfont.py"
        )
    return moz.vector("8bit_polyfont()", f"use <{MCAD_FONTS}>\n")


def glyph_indices(table, word):
    """等价于原文件的 search(word, thisFont[2], 1, 1)。

    SCAD 的 search() 对**字符串**匹配是按逐字符查表的：search("one", 表, 1, 1)
    返回 [111, 110, 101]，也就是 o/n/e 三个字形在表中的下标（每个字符取首个命中）。
    """
    indices = []
    for character in word:
        for index, entry in enumerate(table):
            if entry[1] == character:
                indices.append(index)
                break
    return indices


def clock_hour_words(word_offset=20.0, word_height=2.0):
    font = font_table()
    x_shift, y_shift = font[0][0], font[0][1]
    table = font[2]

    words = []
    for i in range(len(HOURS)):
        hour_hand_angle = (i + 1) * 360 / len(HOURS)
        glyphs = []
        for j, index in enumerate(glyph_indices(table, HOURS[i])):
            points, paths = table[index][6][0], table[index][6][1]
            glyphs.append(moz.translate([j * x_shift, -y_shift / 2], moz.linear_extrude(
                moz.polygon(points, paths), height=word_height)))
        words.append(moz.rotate([0, 0, 90 - hour_hand_angle], moz.translate(
            [word_offset, 0], moz.union(*glyphs))))
    return moz.union(*words)


def build():
    return clock_hour_words(word_offset=16.0, word_height=5.0)


if __name__ == "__main__":
    build().show(title="moz - Old/example023")