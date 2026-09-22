#!/usr/bin/env python3
"""生成 moz 自带的中文字库子集：``py/moz_data/fonts/MozSansSC-Regular.ttf``。

**为什么要自带**：引擎通过 fontconfig 按「家族名」找字体，机器上没有中文字体时
``text()`` **不报错**，而是静默画出空心方框（引擎内置的默认字体 ``Liberation Sans``
只有拉丁字形）。把一份子集字体随包分发，并在 import 时用 ``OPENSCAD_FONT_PATH``
注册（见 ``py/moz_openscad.py``），任何机器上都能出中文。

- 来源：Noto Sans CJK SC（SIL OFL 1.1，可商用、可再分发），只保留常用字符；
- 改名为 ``Moz Sans SC``：与系统里的完整 Noto 并存、不会互相抢名字；要用系统那份把
  ``font=`` 指过去即可（``moz_drawing.TEXT_FONT`` 默认用本文件，保证任何机器上渲染一致）；
- 字符集：ASCII + Latin-1 + 常用标点/符号 + GB2312 一级+二级汉字（6763 字）；
- **输出可复现**：同一份输入字体 + 固定字符集，重复执行得到逐字节相同的文件。

依赖 ``fonttools``（``pip install fonttools``）。默认从 Debian/Ubuntu 的
``fonts-noto-cjk`` 包取源字体：

    python3 scripts/make_cjk_subset_font.py
    python3 scripts/make_cjk_subset_font.py --source /path/to/NotoSansCJK-Regular.ttc
"""

import argparse
import hashlib
import os
import re
import sys
import tempfile

from fontTools import subset
from fontTools.ttLib import TTCollection, TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
DEBIAN_COPYRIGHT = "/usr/share/doc/fonts-noto-cjk/copyright"
SOURCE_FAMILY = "Noto Sans CJK SC"

OUT_FONT = os.path.join(ROOT, "py", "moz_data", "fonts", "MozSansSC-Regular.ttf")
OUT_LICENSE = os.path.join(ROOT, "py", "moz_data", "fonts", "MozSansSC-LICENSE.txt")

# 子集里改用的名字（不是 Noto 的保留字体名，也不会盖住系统的完整 Noto）
FAMILY = "Moz Sans SC"
SUBFAMILY = "Regular"
FULL_NAME = f"{FAMILY} {SUBFAMILY}"
PS_NAME = "MozSansSC-Regular"

# 绘图/标注里常用的符号：⌀ ° ± × → ′ ″ ≈ ≤ ≥
EXTRA_CHARS = "\u2300\u00b0\u00b1\u00d7\u2192\u2032\u2033\u2248\u2264\u2265\u2205"

# head.modified / head.created 固定下来，重复生成才逐字节一致（2023-11-14 UTC）
PINNED_TIMESTAMP = 1700000000


def gb2312_chars(level=2):
    """GB2312 汉字（level=1 只取一级 3755 常用字，level=2 加二级共 6763 字）。"""
    chars = []
    high = range(0xB0, 0xD8) if level == 1 else range(0xB0, 0xF8)
    for hi in high:
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return "".join(chars)


def charset():
    parts = [
        "".join(chr(c) for c in range(0x20, 0x7F)),        # ASCII
        "".join(chr(c) for c in range(0xA0, 0x100)),       # Latin-1 补充
        "".join(chr(c) for c in range(0x2000, 0x2070)),    # 常用标点
        "".join(chr(c) for c in range(0x3000, 0x3040)),    # CJK 标点
        "".join(chr(c) for c in range(0xFF00, 0xFFF0)),    # 全角/半角
        gb2312_chars(2),
        EXTRA_CHARS,
    ]
    return "".join(dict.fromkeys("".join(parts)))          # 去重且保持顺序


def find_face(path, family):
    """在 ttc 里按家族名找 face 下标（``--font-number`` 用）。"""
    collection = TTCollection(path, lazy=True)
    for index, font in enumerate(collection.fonts):
        if font["name"].getDebugName(1) == family:
            return index
    raise SystemExit(f"{path} 里没有家族 {family!r}；可用的有："
                     + ", ".join(repr(f["name"].getDebugName(1)) for f in collection.fonts))


def rename(path, source_family):
    """把子集字体的名字换成 moz 自己的，并保留（并补充）版权声明。"""
    font = TTFont(path, recalcTimestamp=False)
    font["head"].created = PINNED_TIMESTAMP
    font["head"].modified = PINNED_TIMESTAMP
    name = font["name"]
    for record in name.names:
        text = {
            1: FAMILY,
            2: SUBFAMILY,
            3: f"{FULL_NAME};subset;{source_family}",
            4: FULL_NAME,
            6: PS_NAME,
            16: FAMILY,
            17: SUBFAMILY,
            18: FULL_NAME,
            20: PS_NAME,
            21: FAMILY,
            22: SUBFAMILY,
        }.get(record.nameID)
        if text is not None:
            record.string = text
        elif record.nameID == 0:
            record.string = (
                f"{record.toUnicode()} "
                f"Subset of {source_family} made for the moz project: characters limited to "
                "ASCII, Latin-1, common symbols and GB2312 hanzi, glyph outlines unmodified. "
                "Licensed under the SIL Open Font License 1.1, see MozSansSC-LICENSE.txt."
            )
    font.save(path)


def write_license(source_family):
    """OFL 1.1 全文（从 Debian 版权文件里抽取）；已存在则不覆盖。"""
    if os.path.exists(OUT_LICENSE):
        return "保留已有"
    text = ofl_text_from_debian()
    if text is None:
        raise SystemExit(
            f"找不到 OFL 全文（{DEBIAN_COPYRIGHT}）；请自己放一份到 {OUT_LICENSE} 再重跑"
        )
    with open(OUT_LICENSE, "w", encoding="utf-8") as handle:
        handle.write(
            f"{os.path.relpath(OUT_LICENSE, ROOT)} —— {FAMILY}\n"
            f"\n"
            f"本字体是 {source_family} 的子集（字符集裁剪、名字改写，字形轮廓未改动），\n"
            f"由 scripts/make_cjk_subset_font.py 生成，随 moz 一起分发。\n"
            f"{source_family} 与 Noto 系列字体按 SIL Open Font License 1.1 授权：\n"
            f"可自由使用、修改、再分发（含商用），需保留本许可与版权声明。\n"
            f"\n"
            f"------------------------------------------------------------------------\n"
            f"\n"
            + text
        )
    return "新写入"


def ofl_text_from_debian():
    """从 Debian copyright 文件里抽 SIL-1.1 许可正文。

    文件里 ``License: SIL-1.1`` 会出现两次：第一次是 "Files: *" 段落的许可**指针**，
    正文在最后那次出现处，所以取最后一个匹配。
    """
    if not os.path.exists(DEBIAN_COPYRIGHT):
        return None
    with open(DEBIAN_COPYRIGHT, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^License: SIL-1\.1\s*$", line):
            start = index
    if start is None:
        return None
    body = []
    for line in lines[start + 1:]:
        if re.match(r"^(License|Files|Copyright):", line):
            break
        body.append(line[1:] if line.startswith(" ") else line)
    return "\n".join(body).strip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="Noto Sans CJK 的 ttc/otf 路径")
    parser.add_argument("--family", default=SOURCE_FAMILY, help="源字体家族名（在 ttc 里挑 face）")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        raise SystemExit(f"源字体不存在：{args.source}（apt install fonts-noto-cjk）")
    chars = charset()
    face = find_face(args.source, args.family)
    os.makedirs(os.path.dirname(OUT_FONT), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        charset_file = os.path.join(tmp, "charset.txt")
        with open(charset_file, "w", encoding="utf-8") as handle:
            handle.write(chars)
        subset.main([
            args.source,
            f"--font-number={face}",
            f"--text-file={charset_file}",
            f"--output-file={OUT_FONT}",
            "--no-hinting",
            "--desubroutinize",
            "--drop-tables+=DSIG",
        ])
    rename(OUT_FONT, args.family)
    license_state = write_license(args.family)

    with open(OUT_FONT, "rb") as handle:
        data = handle.read()
    digest = hashlib.sha256(data).hexdigest()[:16]
    print(f"源字体      : {args.source}（face {face} = {args.family}）")
    print(f"字符数      : {len(chars)}（含 GB2312 一级+二级 {len(gb2312_chars(2))} 字）")
    print(f"输出        : {os.path.relpath(OUT_FONT, ROOT)}  {len(data)} 字节  sha256={digest}")
    print(f"许可文件    : {os.path.relpath(OUT_LICENSE, ROOT)}（{license_state}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
