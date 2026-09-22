"""自带字形表（3rd/openscad/libraries/MCAD/fonts.scad 的 drop-in）的契约测试。

这份文件是 ``scripts/gen_mcad_polyfont.py`` 生成的自研数据（上游 MCAD 那份是 LGPL 2.1，
这里换成 OFL）。它必须与上游同接口，否则 ``Old/example023`` 会悄悄退化：

* 表的形状：[字符格尺寸, 列名, 256 项] —— 上游靠**下标 == 字节码**取字形；
* 每一项第 1 列是可搜索的字符（``search()`` 按逐字符匹配这一列）；
* 第 6 列是 ``[points, paths]``，且字形要有内孔（'o' 是环而不是实心块）。

注意：``py/verify_examples.py`` 比对的是原生 .scad 与 Python 版，**两边都用这份表**，
所以表整体坏掉（比如一项字形都没有）在保真度上也可能「一致地坏」——这个文件就是补这个缺口。
"""

import math
from pathlib import Path

import pytest

FONTS = Path(__file__).resolve().parents[2] / "3rd" / "openscad" / "libraries" / "MCAD" / "fonts.scad"


@pytest.fixture(scope="module")
def table(moz):
    if not FONTS.exists():
        pytest.skip(f"缺少字形表 {FONTS}")
    return moz.vector("8bit_polyfont()", f"use <{FONTS}>\n")


def test_table_shape_matches_upstream(table):
    assert len(table) == 3
    assert table[0][:3] == [8, 8, 0]          # 字符格 8×8、无厚度（2D 路径）
    assert len(table[2]) == 256


def test_search_column_is_the_character(table):
    """search() 靠这一列匹配，所以下标必须等于字节码、内容是字符本身。"""
    for code in (65, 97, 48, 32):              # A a 0 空格
        assert table[2][code][1] == chr(code)
    assert table[2][111][1] == "o"


def test_search_one_and_twelve_like_the_example(moz, table):
    source = f"use <{FONTS}>\n"
    assert moz.vector('search("one", 8bit_polyfont()[2], 1, 1)', source) == [ord(c) for c in "one"]
    assert moz.vector('search("twelve", 8bit_polyfont()[2], 1, 1)', source) == [ord(c) for c in "twelve"]


def test_hour_words_have_glyphs(table):
    for word in ("one", "two", "three", "four", "five", "six",
                 "seven", "eight", "nine", "ten", "eleven", "twelve"):
        for character in word:
            points, paths = table[2][ord(character)][6]
            assert points and paths, f"字形缺失: {character!r}"


def test_letters_keep_their_counters(moz, table):
    """'o' 有内孔：面积要明显小于它的包围盒；'l' 是细条，两者不能混同。"""
    for character in "oe":
        points, paths = table[2][ord(character)][6]
        assert len(paths) == 2, f"{character!r} 应该有外轮廓 + 内孔两条路径"
        shape = moz.polygon(points, paths).measure
        box = (shape.bbox_max[0] - shape.bbox_min[0]) * (shape.bbox_max[1] - shape.bbox_min[1])
        assert shape.area < box * 0.8
    points, paths = table[2][ord("l")][6]
    shape = moz.polygon(points, paths).measure
    assert shape.area < 5 and shape.bbox_max[1] > 7      # 细长条，到字高上限
    assert math.isclose(shape.bbox_min[1], 1.8, abs_tol=0.1)   # 基线在 y≈1.79


def test_glyphs_stay_inside_the_cell(table):
    """字形纵向落在 8×8 格子里（横向允许一点外悬，真字体本来就带）；空格之类没有字形，跳过。"""
    checked = 0
    for code in range(32, 127):
        data = table[2][code][6]
        if not data:
            continue
        points = data[0]
        checked += 1
        for x, y in points:
            assert -0.5 <= x <= 8.5, (code, x, y)
            assert -0.01 <= y <= 8.01, (code, x, y)
    assert checked > 90       # 可打印 ASCII 里绝大多数都有字形
