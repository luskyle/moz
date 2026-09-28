#!/usr/bin/env python3
"""把公开仓库里的 DWG 样例抓到 ``corpus/dwg/`` 当作回归语料（N1 的 DWG 验收用）。

为什么单独一个脚本：``scripts/fetch_dxf_corpus.py`` 抓的是 DXF，而 DWG 通路（libdxfrw）
**必须**有真实的 DWG 才能验收——仓库里原本一个 DWG 都没有（见 docs/librecad-integration.md §七）。

    python3 scripts/fetch_dwg_samples.py              # 抓取（已存在的不覆盖）
    python3 scripts/fetch_dwg_samples.py --dry-run    # 只看会抓哪些

来源与许可：

- DomCR/ACadSharp        MIT            同一张图的 **AC1014/1015/1018/1021/1024/1027 版本阶梯**
                                        （正好覆盖 libdxfrw 的 dwgReader15/18/21/24/27）+ 动态块、地理定位
- LibreCAD/libdxfrw      GPLv2-or-later 该库自己的 DWG 测试样本（按版本命名 + ANSI932 编码页）

网络：走 ``curl``（本机 curl 通、Python urllib 不稳），失败自动重试；按文件逐个抓。
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_ROOT = os.path.join(ROOT, "corpus", "dwg")

SOURCES = [
    {
        "repo": "DomCR/ACadSharp", "ref": "master", "license": "MIT", "dest": "acadsharp",
        "files": [
            "samples/sample_AC1014.dwg",     # R14
            "samples/sample_AC1015.dwg",     # 2000
            "samples/sample_AC1018.dwg",     # 2004
            "samples/sample_AC1021.dwg",     # 2007
            "samples/sample_AC1024.dwg",     # 2010
            "samples/sample_AC1027.dwg",     # 2013
            "samples/dynamic-blocks/BLOCKVISIBILITYPARAMETER.dwg",
            "samples/geolocation/geoloc.dwg",
        ],
    },
    {
        "repo": "LibreCAD/libdxfrw", "ref": "master", "license": "GPLv2-or-later", "dest": "libdxfrw",
        "files": [
            "tests/fixtures/dwg/ordinary_enc_AC1015.dwg",
            "tests/fixtures/dwg/ordinary_enc_AC1018.dwg",
            "tests/fixtures/dwg/ordinary_enc_AC1021.dwg",
            "tests/fixtures/dwg/ordinary_enc_AC1027.dwg",
            "tests/fixtures/dwg/ordinary_enc_ac1027_ansi932.dwg",
            "tests/fixtures/dwg/large_radial.dwg",
            "tests/fixtures/dwg/mpolygon_solid.dwg",
            "tests/fixtures/dwg/rtext_arctext.dwg",
        ],
    },
]


def curl(url, target=None, timeout=300, retries=3):
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


def flatten(path):
    return path.replace("/", "__").replace(" ", "_")


def expected_sizes(repo, ref):
    """走 GitHub 树 API 拿"每个文件应该多大"，用来校验下载有没有被截断。

    实测踩过：本机网络偶发在 1 MB 左右的文件上超时，curl 仍以成功退出，
    结果是半张图落盘（表现为"这张图打不开"），所以必须有校验。
    """
    ok, payload = curl(f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1", timeout=120)
    if not ok:
        print(f"  （取不到 {repo} 的文件清单，跳过体积校验）")
        return {}
    try:
        tree = json.loads(payload).get("tree", [])
    except ValueError:
        return {}
    return {item["path"]: item.get("size", 0) for item in tree}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="只列出会抓哪些文件")
    parser.add_argument("--workers", type=int, default=4, help="并发下载数（默认 4）")
    args = parser.parse_args(argv)

    total, failed = 0, []
    for source in SOURCES:
        repo, ref = source["repo"], source["ref"]
        dest_dir = os.path.join(DEST_ROOT, source["dest"])
        print(f"=== {repo}（{source['license']}，{len(source['files'])} 个）===", flush=True)
        wants = expected_sizes(repo, ref) if not args.dry_run else {}
        targets_to_redownload = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            pending = {}
            for path in source["files"]:
                target = os.path.join(dest_dir, flatten(path))
                if os.path.exists(target):
                    want = wants.get(path, 0)
                    size = os.path.getsize(target)
                    if want and size != want:                  # 半截文件：当作没有，重下
                        print(f"  已有但只 {size} B（应为 {want} B），重下 {os.path.basename(target)}")
                        targets_to_redownload.append(target)
                    else:
                        print(f"  已有 {os.path.basename(target)}")
                        continue
                if args.dry_run:
                    print(f"  会抓 {path}")
                    continue
                url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
                pending[pool.submit(curl, url, target)] = path
            for future in as_completed(pending):
                path = pending[future]
                ok, detail = future.result()
                if ok:
                    size = os.path.getsize(detail)
                    want = wants.get(path, 0)
                    if want and size != want:                 # 截断/半截文件：删掉并报失败
                        os.remove(detail)
                        print(f"  失败 {path}：只下到 {size} B（应为 {want} B），已删除，重跑一次",
                              flush=True)
                        failed.append(path)
                        continue
                    print(f"  {os.path.basename(detail):58s} {size:8d} B", flush=True)
                    total += 1
                else:
                    print(f"  失败 {path}：{detail}", flush=True)
                    failed.append(path)
    print(f"\n新抓取 {total} 个文件 -> {os.path.relpath(DEST_ROOT, ROOT)}")
    if failed:
        print("失败项：", ", ".join(failed[:8]), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
