#!/usr/bin/env python3
"""把公开仓库里的 DXF 样例抓到 ``corpus/dxf/`` 当作回归语料（P1 用现成图纸验证）。

为什么要存一份：``py/verify_dxf.py`` 的语料必须**可复现、可审计**——不能依赖某个仓库的
master 分支或本机别的项目目录。这个脚本把来源、许可、预期数量写死，重复执行得到同一批文件。

    python3 scripts/fetch_dxf_corpus.py            # 抓取（已存在的不覆盖）
    python3 scripts/fetch_dxf_corpus.py --dry-run  # 只列出会抓哪些

来源与许可（详见 corpus/dxf/README.md）：

- LibreCAD/LibreCAD      GPLv2    解析器测试集（编码/R2007 特性）+ 零件库（机械/电气/建筑）+ 尺寸样例
- vagran/dxf-viewer      MIT      测试样例（块/标注/圆与圆弧等）
- mozman/ezdxf           MIT      该库自己的 feature 示例与集成测试图（就是我们依赖的解析库）
- gdsestimating/dxf-parser MIT    该解析器的测试图
- qcad/qcad              GPLv3    图层/剖面线/标注样式/文字等专项测试图
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_ROOT = os.path.join(ROOT, "corpus", "dxf")

# 每个来源：仓库、分支、要抓的路径规则（前缀, 数量）、许可、目标子目录、单文件体积上限
SOURCES = [
    {
        "repo": "LibreCAD/LibreCAD", "ref": "master",
        "picks": [("librecad/src/lib/filters/tests/testdata/dxf/", 12),   # 它自己的解析器测试集
                  ("librecad/support/library/kinetics/", 6),              # 运动机构图块
                  ("librecad/support/library/power_station/", 5),         # 电站设备图块
                  ("librecad/support/library/elektro/dev/", 5),           # 电气元件图块
                  ("librecad/support/library/plan/air_water/", 5),        # 管路平面图块
                  ("librecad/support/library/algoritm/", 4),
                  ("librecad/support/library/misc/", 4),
                  ("librecad/res/dxf/", 1)],                              # 尺寸样例
        "license": "GPLv2", "dest": "librecad",
    },
    {
        "repo": "vagran/dxf-viewer", "ref": "master",
        "picks": [("test/fixtures/", 30), ("samples/", 4)],
        "license": "MIT", "dest": "dxf-viewer",
    },
    {
        "repo": "mozman/ezdxf", "ref": "master",
        "picks": [("examples_dxf/", 22), ("integration_tests/data/", 15)],
        "license": "MIT", "dest": "ezdxf",
        "max_size": 400_000,
        # `examples_dxf/image/images.dxf` 引用的 4 张图：必须跟 DXF 放同一个目录
        # （实体里写的是 ".\image1.jpg" 这种**相对名**），所以不压平、直接进 dest 根。
        "extras": ["examples_dxf/image/image1.jpg", "examples_dxf/image/image2.png",
                   "examples_dxf/image/image3.jpg", "examples_dxf/image/image4.jpg"],
    },
    {
        "repo": "gdsestimating/dxf-parser", "ref": "master",
        "picks": [("test/data/", 10), ("samples/data/", 4)],
        "license": "MIT", "dest": "dxf-parser",
    },
    {
        "repo": "qcad/qcad", "ref": "master",
        "picks": [("support/data/tests/layer/", 10), ("support/data/tests/hatch/", 8),
                  ("support/data/tests/dimstyle/", 8), ("support/data/tests/text/", 6),
                  ("libraries/templates/metric/", 5)],
        "license": "GPLv3", "dest": "qcad",
        "max_size": 400_000,
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
    """列出仓库里所有 .dxf 的 (路径, 体积)（走 GitHub 树的 API）。"""
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    ok, payload = curl(url)
    if not ok:
        raise SystemExit(f"{repo}: 取文件列表失败（{payload}）")
    data = json.loads(payload)
    if "tree" not in data:
        raise SystemExit(f"{repo}: 返回里没有 tree（{str(data)[:80]}）")
    return [(item["path"], item.get("size", 0))
            for item in data["tree"] if item["path"].lower().endswith(".dxf")]


def tree_sizes(repo, ref):
    """仓库树的 路径 → 体积 全表（给 `extras`（图片等非 DXF 文件）做截断校验）。"""
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    ok, payload = curl(url)
    if not ok:
        return {}
    try:
        return {item["path"]: item.get("size", 0)
                for item in json.loads(payload).get("tree", [])}
    except ValueError:
        return {}


def pick(items, picks, max_size=0):
    """按 (前缀, 数量) 规则挑文件；去重、保持仓库内顺序、按体积上限过滤。"""
    chosen, seen = [], set()
    for prefix, limit in picks:
        count = 0
        for path, size in items:
            if count >= limit:
                break
            if prefix and not path.startswith(prefix):
                continue
            if max_size and size > max_size:
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
    parser.add_argument("--workers", type=int, default=4, help="并发下载数（默认 4；本机网络单连接很慢）")
    args = parser.parse_args(argv)

    total, failed = 0, []
    for source in SOURCES:
        repo, ref = source["repo"], source["ref"]
        dest_dir = os.path.join(DEST_ROOT, source["dest"])
        wanted = sum(limit for _prefix, limit in source["picks"])
        print(f"=== {repo}（{source['license']}，最多 {wanted} 个）===", flush=True)
        try:
            paths = list_dxf(repo, ref)
        except SystemExit as exc:
            print(f"  跳过：{exc}")
            failed.append(f"{repo}: 列表失败")
            continue
        chosen = pick(paths, source["picks"], source.get("max_size", 0))
        print(f"  仓库里共 {len(paths)} 个 DXF，取 {len(chosen)} 个", flush=True)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            pending = {}
            for path in chosen:
                target = os.path.join(dest_dir, flatten(path))
                if os.path.exists(target):
                    continue                              # 已有就别重复抓（也省得每次都重下一遍）
                if args.dry_run:
                    print(f"  会抓 {path}")
                    continue
                url = f"https://raw.githubusercontent.com/{repo}/{ref}/{quote(path)}"
                pending[pool.submit(curl, url, target)] = (path, target)
            for future in as_completed(pending):
                path, target = pending[future]
                keep, detail = future.result()
                if keep:
                    size = os.path.getsize(target)
                    print(f"  {os.path.basename(target):58s} {size:8d} B", flush=True)
                    total += 1
                else:
                    print(f"  失败 {path}：{detail}", flush=True)
                    failed.append(path)

        # extras（图片等非 DXF）：按相对名进 dest 根；有体积表就校验，半截文件重下
        extras = source.get("extras", [])
        if extras:
            sizes = tree_sizes(repo, ref)
            for path in extras:
                target = os.path.join(dest_dir, os.path.basename(path))
                want = sizes.get(path, 0)
                if not want:
                    # 树里没有这个文件：上游根本不存在（实测 image4.jpg 就引用了但不存在，
                    # 抓到的只能是 "404: Not Found" 文本）——别把它当成真图片
                    if os.path.exists(target):
                        print(f"  上游没有 {path}，删掉误存的 {os.path.basename(target)}",
                              file=sys.stderr)
                        os.remove(target)
                    continue
                if os.path.exists(target) and os.path.getsize(target) == want:
                    continue
                if args.dry_run:
                    print(f"  会抓 {path}")
                    continue
                url = f"https://raw.githubusercontent.com/{repo}/{ref}/{quote(path)}"
                keep, detail = curl(url, target)
                if keep and os.path.getsize(target) == want:
                    print(f"  {os.path.basename(target):58s} {os.path.getsize(target):8d} B",
                          flush=True)
                    total += 1
                else:
                    size = os.path.getsize(target) if os.path.exists(target) else 0
                    print(f"  失败 {path}：{detail}（体积 {size}，应为 {want}）",
                          file=sys.stderr)
                    failed.append(path)
    print(f"\n新抓取 {total} 个文件 -> {os.path.relpath(DEST_ROOT, ROOT)}")
    if failed:
        print("失败项：", ", ".join(failed[:5]), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
