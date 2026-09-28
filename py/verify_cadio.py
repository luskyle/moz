#!/usr/bin/env python3
"""用 libmozcadio（LibreCAD 的 libdxfrw 抽取）扫一遍语料：读得通/读不通、有多少告警。

与 ``py/verify_dxf.py`` 是**两件不同的事**：那个验的是"图纸 → 模型"的语义（轮廓/面积/体积），
这个验的是"图元读得全不全、失败说不说得清"——即 docs/librecad-integration.md 的 N1 验收第 3 条。

    PYTHONPATH=py python3 py/verify_cadio.py            # 扫全部语料
    PYTHONPATH=py python3 py/verify_cadio.py 额外.dxf   # 再带上指定的文件
"""

import os
import sys
from collections import Counter
from glob import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py"))

import moz_cadio  # noqa: E402

CORPORA = [
    ("上游 testdata", os.path.join(ROOT, "3rd", "openscad", "testdata")),
    ("公开语料", os.path.join(ROOT, "corpus", "dxf")),
    ("公开 DWG", os.path.join(ROOT, "corpus", "dwg")),
    ("P1 样例", os.path.join(ROOT, "py", "moz_data", "drawings")),
    ("libdxfrw 自带样本", os.path.join(ROOT, "3rd", "librecad", "libraries", "libdxfrw")),
]

# 读不通但**在预期内**（不是我们的问题）。按**后缀**匹配：语料里的文件名是扁平化的。
#   - bin_dxf_r12.dxf：R12 的**二进制** DXF，上游 libdxfrw 没有这个组合的读取器
#   - nothing-decimal-comma-separated.dxf：数值写成小数逗号（`2,5`），上游直接拒绝
#     （BAD_READ_HEADER）——与引擎的 import()（空几何）和 py/moz_dxf.py（拒绝）态度一致
#   - screw2012binary.dxf：上游自带的二进制样本，**它的对象段两个版本的 libdxfrw 都读不了**
#     （0.5.11 报 BAD_READ_SECTION、2.0.0 报 BAD_READ_OBJECTS；ezdxf 读它没问题，实体段
#     也解析得动）——我们的态度是整体报错，不静默给半个图
EXPECTED_UNREADABLE = ("bin_dxf_r12.dxf", "nothing-decimal-comma-separated.dxf",
                       "screw2012binary.dxf")


def is_expected_unreadable(name):
    return any(name.endswith(suffix) for suffix in EXPECTED_UNREADABLE)


def model_entities(cad):
    return [entity for entity in cad.entities if entity.owner == ""]


def check(path):
    """返回 (判定, 说明, 告警列表)；判定是 OK / EMPTY / UNREADABLE / FAIL。"""
    name = os.path.basename(path)
    try:
        cad = moz_cadio.read(path)
    except moz_cadio.CadIoError as exc:
        verdict = "UNREADABLE" if is_expected_unreadable(name) else "FAIL"
        return verdict, str(exc)[:110], []
    model = model_entities(cad)
    counts = Counter(entity.kind for entity in model)
    detail = f"{cad.format}/{cad.version} 模型空间 {sum(counts.values())} 个 {dict(counts.most_common(4))}"
    warn = f" 告警{len(cad.warnings)}" if cad.warnings else ""
    if not model:
        return "EMPTY", detail + "（模型空间没有图元）" + warn, cad.warnings
    return "OK", detail + warn, cad.warnings


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = []
    for _label, root in CORPORA:
        for pattern in ("*.dxf", "*.DXF", "*.dwg", "*.DWG"):
            paths += sorted(glob(os.path.join(root, "**", pattern), recursive=True))
    paths = sorted(set(paths))
    paths += [os.path.abspath(p) for p in argv]

    verdicts = Counter()
    unexpected = []
    warning_kinds = Counter()
    for path in paths:
        verdict, detail, warnings = check(path)
        verdicts[verdict] += 1
        label = os.path.relpath(path, ROOT) if path.startswith(ROOT) else path
        print(f"[{verdict:10s}] {label:60s} {detail}")
        if verdict == "FAIL":
            unexpected.append((path, detail))
        for warning in warnings:
            warning_kinds[warning.split("：")[0].split("（")[0][:40]] += 1

    print()
    print("=== 告警分类（前 8）===")
    for text, count in warning_kinds.most_common(8):
        print(f"  {count:4d}  {text}")
    print()
    print(f"汇总: 共 {len(paths)} 个文件 —— " + "  ".join(
        f"{key}={verdicts[key]}" for key in ("OK", "EMPTY", "UNREADABLE", "FAIL")))
    if unexpected:
        print("意外读不通：")
        for path, detail in unexpected:
            print(f"  {path} —— {detail}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
