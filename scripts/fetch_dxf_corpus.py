#!/usr/bin/env python3
"""把公开仓库里的 DXF 样例抓到 ``corpus/dxf/`` 当作回归语料（P1 用现成图纸验证）。

为什么要存一份：``py/verify_dxf.py`` 的语料必须**可复现、可审计**——不能依赖某个仓库的
master 分支或本机别的项目目录。这个脚本把来源、许可、预期数量写死，重复执行得到同一批文件。

    python3 scripts/fetch_dxf_corpus.py            # 抓取（已存在的不覆盖）
    python3 scripts/fetch_dxf_corpus.py --dry-run  # 只列出会抓哪些

来源与许可（详见 corpus/dxf/README.md）：

- LibreCAD/LibreCAD      GPLv2    解析器测试集（编码/R2007 特性）+ 机械零件库 + 尺寸样例
- vagran/dxf-viewer      MIT      测试样例（块/标注/圆与圆弧等）
- gdsestimating/three-dxf MIT     样例 DXF
- FreeCAD/FreeCAD-library LGPL-2.1 零件库里的 DXF（真实机械件轮廓）

网络：走 ``curl``（本机实测 curl 通、Python urllib 不稳），失败会自动重试；
``raw.githubusercontent.com`` 可直连，``codeload``/``github.com`` 走不通，所以按文件逐个抓。
"""

import argparse
import json
import os
import subprocess
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_ROOT = os.path.join(ROOT, "corpus", "dxf")

# 每个来源：仓库、分支、要抓的路径规则（前缀, 数量）、许可、目标子目录
SOURCES = [
    {
        "repo": "LibreCAD/LibreCAD", "ref": "master",
        "picks": [("librecad/src/lib/filters/tests/testdata/dxf/", 12),   # 它自己的解析器测试集
                  ("librecad/support/library/mechanical/", 8),            # 机械零件轮廓
                  ("librecad/support/library/elektro/antenna", 2),        # 电气符号
                  ("librecad/res/dxf/", 1)],                              # 尺寸样例
        "license": "GPLv2", "dest": "librecad",
    },
    {
        "repo": "vagran/dxf-viewer", "ref": "master",
        "picks": [("test/fixtures/", 12), ("samples/", 2)],
        "license": "MIT", "dest": "dxf-viewer",
    },
    {
        "repo": "gdsestimating/three-dxf", "ref": "master",
        "picks": [("sample/", 2)],
        "license": "MIT", "dest": "three-dxf",
    },
    {
        "repo": "FreeCAD/FreeCAD-library", "ref": "master",
        "picks": [("", 10)],
        "license": "LGPL-2.1", "dest": "freecad-library",
    },
]


def curl(url, target=None, timeout=90, retries=3):
    """用 curl 取 url；给了 target 就写文件。返回 (成功?, 内容或错误)。"""
    flags = ["-sSL", "--retry", "2", "--retry-delay", "2", "-m", str(timeout)]
    if target:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        flags += ["-o", target]
    for attempt in range(1, retries + 1):
        result = subprocess.run(["curl", *flags, url], capture_output=True, text=True)
        if result.returncode == 0:
            return True, target or result.stdout
        if attempt == retries:
            return False, (result.stderr or "").strip()[:120]
    return False, "重试用尽"


def list_dxf(repo, ref):
    """列出仓库里所有 .dxf 路径（走 GitHub 树的 API）。"""
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    ok, payload = curl(url)
    if not ok:
        raise SystemExit(f"{repo}: 取文件列表失败（{payload}）")
    data = json.loads(payload)
    if "tree" not in data:
        raise SystemExit(f"{repo}: 返回里没有 tree（{str(data)[:80]}）")
    return [item["path"] for item in data["tree"] if item["path"].lower().endswith(".dxf")]


def pick(paths, picks):
    """按 (前缀, 数量) 规则挑文件；去重、保持仓库内顺序。"""
    chosen, seen = [], set()
    for prefix, limit in picks:
        count = 0
        for path in paths:
            if count >= limit:
                break
            if prefix and not path.startswith(prefix):
                continue
            if path in seen:
                continue
            chosen.append(path)
            seen.add(path)
            count += 1
    return chosen


def flatten(path):
    """把仓库里的路径压成文件名（保留目录语义、去掉空格，避免 URL/文件名麻烦）。"""
    return path.replace("/", "__").replace(" ", "_")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="只列出会抓哪些文件")
    args = parser.parse_args(argv)

    total, failed = 0, []
    for source in SOURCES:
        repo, ref = source["repo"], source["ref"]
        dest_dir = os.path.join(DEST_ROOT, source["dest"])
        wanted = sum(limit for _prefix, limit in source["picks"])
        print(f"=== {repo}（{source['license']}，最多 {wanted} 个）===")
        try:
            paths = list_dxf(repo, ref)
        except SystemExit as exc:
            print(f"  跳过：{exc}")
            failed.append(f"{repo}: 列表失败")
            continue
        chosen = pick(paths, source["picks"])
        print(f"  仓库里共 {len(paths)} 个 DXF，取 {len(chosen)} 个")
        for path in chosen:
            target = os.path.join(dest_dir, flatten(path))
            if os.path.exists(target):
                print(f"  已有 {os.path.basename(target)}")
                continue
            if args.dry_run:
                print(f"  会抓 {path}")
                continue
            url = f"https://raw.githubusercontent.com/{repo}/{ref}/{quote(path)}"
            ok, detail = curl(url, target=target)
            if ok:
                size = os.path.getsize(target)
                print(f"  {os.path.basename(target):58s} {size:8d} B")
                total += 1
            else:
                print(f"  失败 {path}：{detail}")
                failed.append(path)
    print(f"\n新抓取 {total} 个文件 -> {os.path.relpath(DEST_ROOT, ROOT)}")
    if failed:
        print("失败项：", ", ".join(failed[:5]), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
