#!/usr/bin/env python3
"""逐示例比对：原生 .scad 求值 与 Python build() 是否给出**同一个实体**。

报告三个档次的相似度（逐级放宽）：

1. ``网格逐字节一致``——导出字节完全相同（最理想）；
2. ``网格作为集合一致``——三角面多重集合完全相同，只是面序不同；
3. ``实体一致``——网格三角化不同（因为 Python 侧拼出来的源码在 CSG 节点结构上
   无法与 .scad 逐一复刻，CGAL 会把同一实体切成不同三角面），但实体的体积、
   表面积、包围盒在容差内一致。**这一档也算通过。**

只有当体积/表面积/包围盒超出容差（说明实体真的不一样，例如少了 $fn、少了对象、
平移与旋转顺序错了）时才判 DIFF，并把差异数字打出来。

2D 用 svg 的多边形多重集合比较（2D 的三角化稳定，直接要求集合一致）。

用法::

    PYTHONPATH=py python3 py/verify_examples.py                     # 全部
    PYTHONPATH=py python3 py/verify_examples.py Old                 # 只跑 Old 分类
    PYTHONPATH=py python3 py/verify_examples.py Old/example007 Advanced/GEB
"""

import importlib.util
import math
import os
import re
import struct
import sys
import traceback
from pathlib import Path

# 容差：网格是 float32，坐标量级几十到几百时每个坐标有 ~1e-5 的量化误差，
# 上万三角面累加后体积/表面积的相对误差可达 ~1e-4，所以取 1e-3 留足余量。
VOLUME_RTOL = 1e-3
AREA_RTOL = 1e-3
BBOX_RTOL = 1e-3

ROOT = Path(__file__).resolve().parent.parent
SCAD_ROOT = ROOT / "3rd" / "openscad" / "examples"
PY_ROOT = ROOT / "py" / "examples"

# Old/example023 的 .scad 用 use <MCAD/fonts.scad>，上游把 OpenSCAD 的 libraries
# 目录当库搜索路径；这里的 vendored 副本走 OPENSCADPATH（必须在首次加载库之前设好）。
os.environ.setdefault("OPENSCADPATH", str(ROOT / "3rd" / "openscad" / "libraries"))

sys.path.insert(0, str(ROOT / "py"))
import moz_openscad as moz  # noqa: E402


def _stl_triangles(data):
    """binstl → 归一化的三角面多重集合（每个面内顶点排序，面之间排序）。"""
    if len(data) < 84:
        raise ValueError("invalid stl")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) < 84 + count * 50:
        raise ValueError("truncated stl")
    triangles = []
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12f", data, offset)
        triangles.append(tuple(sorted((values[3:6], values[6:9], values[9:12]))))
        offset += 50
    return sorted(triangles)


def _mesh_solid(data):
    """从 binstl 求实体的（面数, 体积, 表面积, 包围盒），用有符号四面体累加。"""
    count = struct.unpack_from("<I", data, 80)[0]
    volume = area = 0.0
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12f", data, offset)
        offset += 50
        p0, p1, p2 = values[3:6], values[6:9], values[9:12]
        for point in (p0, p1, p2):
            for i in range(3):
                lo[i] = min(lo[i], point[i])
                hi[i] = max(hi[i], point[i])
        cross = (p1[1] * p2[2] - p1[2] * p2[1],
                 p1[2] * p2[0] - p1[0] * p2[2],
                 p1[0] * p2[1] - p1[1] * p2[0])
        volume += (p0[0] * cross[0] + p0[1] * cross[1] + p0[2] * cross[2]) / 6.0
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        area += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return count, abs(volume), area, lo, hi


def _relative(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-12)


def _svg_polygons(data):
    """svg → 归一化的多边形多重集合。仅支持直线段（M/L/z），出现曲线命令时返回 None。"""
    text = data.decode("utf-8", "replace")
    polygons = []
    for path_data in re.findall(r'\bd="([^"]*)"', text):
        tokens = re.findall(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", path_data)
        if any(token.isalpha() and token not in "MLZz" for token in tokens):
            return None
        current, pending = [], None
        for token in tokens:
            if token.isalpha():
                if token in "Zz" and current:
                    polygons.append(tuple(sorted(current)))
                    current = []
                pending = None
                continue
            if pending is None:
                pending = token
            else:
                current.append((float(pending), float(token)))
                pending = None
        if current:
            polygons.append(tuple(sorted(current)))
    return sorted(polygons)


def _load_build(path):
    """按文件路径加载示例模块，返回它的 build()。"""
    spec = importlib.util.spec_from_file_location(f"moz_example_{path.parent.name}_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    build = getattr(module, "build", None)
    if build is None:
        raise RuntimeError(f"{path} does not expose build()")
    return build


def _missing_prerequisite(category, name):
    """示例依赖的外部数据/库是否齐备（缺了就没法验证，报 SKIP 而不是 FAIL）。"""
    required = {
        # Old/example023 依赖 MCAD 库（不在 OpenSCAD 源码包里，见 README 说明）
        ("Old", "example023"): [ROOT / "3rd" / "openscad" / "libraries" / "MCAD" / "fonts.scad"],
    }.get((category, name), [])
    return [path for path in required if not path.exists()]


def verify(category, name):
    scad_path = SCAD_ROOT / category / f"{name}.scad"
    py_path = PY_ROOT / category / f"{name}.py"
    label = f"{category}/{name}"
    if not scad_path.exists():
        return "SKIP", f"{label}: 原始 .scad 不存在"
    missing = _missing_prerequisite(category, name)
    if missing:
        return "SKIP", (f"{label}: 缺少依赖 {', '.join(str(p) for p in missing)}"
                        f"（原生与 Python 两侧都跑不出几何，无法比对）")
    if not py_path.exists():
        return "MISSING", f"{label}: 缺少 Python 版本"

    try:
        build = _load_build(py_path)
    except Exception as exc:
        return "FAIL", f"{label}: 加载失败: {exc}"

    try:
        native = moz.eval_file(str(scad_path))
    except Exception as exc:
        return "FAIL", f"{label}: 原生求值失败: {str(exc).strip().splitlines()[0][:120]}"

    py_geom = None
    try:
        py_geom = build()._geometry()

        if native.is_empty or py_geom.is_empty:
            if native.is_empty and py_geom.is_empty:
                return "OK", f"{label}: 两边都是空几何"
            return "DIFF", (f"{label}: 空几何不一致 "
                            f"(原生 empty={native.is_empty} / python empty={py_geom.is_empty})")
        if py_geom.dimension != native.dimension:
            return "DIFF", (f"{label}: 维度不一致 "
                            f"(原生 {native.dimension} / python {py_geom.dimension})")

        if native.dimension == 2:
            native_bytes = native.export_bytes("svg")
            py_bytes = py_geom.export_bytes("svg")
            native_polys = _svg_polygons(native_bytes)
            py_polys = _svg_polygons(py_bytes)
            if native_polys is None or py_polys is None:
                return ("OK" if native_bytes == py_bytes else "DIFF"), (
                    f"{label}: svg 含曲线命令，回落到字节比较 "
                    f"({'一致' if native_bytes == py_bytes else '不一致'})")
            if native_polys == py_polys:
                extra = "导出字节也一致" if native_bytes == py_bytes else "面序不同（几何相同）"
                return "OK", f"{label}: {len(native_polys)} 个多边形完全一致，{extra}"
            return "DIFF", (f"{label}: 几何不一致（{len(native_polys)} vs {len(py_polys)} 个多边形，"
                            f"原生独有 {len(set(native_polys) - set(py_polys))} / "
                            f"python 独有 {len(set(py_polys) - set(native_polys))}）")

        native_bytes = native.export_bytes("binstl")
        py_bytes = py_geom.export_bytes("binstl")
        native_tris = _stl_triangles(native_bytes)
        py_tris = _stl_triangles(py_bytes)
        n_count, n_vol, n_area, n_lo, n_hi = _mesh_solid(native_bytes)
        p_count, p_vol, p_area, p_lo, p_hi = _mesh_solid(py_bytes)

        if native_tris == py_tris:
            extra = "导出字节也一致" if native_bytes == py_bytes else "面序不同（几何相同）"
            return "OK", f"{label}: {n_count} 个三角面完全一致，{extra}"

        scale = max(max(abs(v) for v in n_lo + n_hi), 1.0)
        dv, da = _relative(n_vol, p_vol), _relative(n_area, p_area)
        db = max(max(abs(a - b) for a, b in zip(n_lo, p_lo)),
                 max(abs(a - b) for a, b in zip(n_hi, p_hi)))
        if dv <= VOLUME_RTOL and da <= AREA_RTOL and db <= BBOX_RTOL * scale:
            return "OK", (f"{label}: 实体一致（{n_count}/{p_count} 个三角面，三角化不同；"
                          f"体积差 {dv:.1e}，表面积差 {da:.1e}）")
        return "DIFF", (f"{label}: 实体不一致（面数 {n_count}/{p_count}，体积 {n_vol:.4f}/{p_vol:.4f} "
                        f"差 {dv:.1e}，表面积 {n_area:.4f}/{p_area:.4f} 差 {da:.1e}，"
                        f"包围盒最大差 {db:.4f}）")
    except Exception as exc:
        return "FAIL", f"{label}: 比对失败: {exc}"
    finally:
        native.close()
        if py_geom is not None:
            py_geom.close()


def main(argv):
    if argv:
        pairs = []
        for arg in argv:
            if "/" in arg:
                category, _, name = arg.partition("/")
                pairs.append((category, name))
            else:
                pairs.extend((arg, p.stem) for p in sorted((SCAD_ROOT / arg).glob("*.scad")))
    else:
        pairs = []
        for category_dir in sorted(SCAD_ROOT.iterdir()):
            if category_dir.is_dir():
                pairs.extend((category_dir.name, p.stem)
                             for p in sorted(category_dir.glob("*.scad")))

    results = []
    for category, name in pairs:
        status, message = verify(category, name)
        results.append((status, message))
        print(f"[{status:7s}] {message}", flush=True)

    if not pairs:
        print(f"没有匹配到任何示例；分类目录应在 {SCAD_ROOT} 下，或直接写 分类/示例名", file=sys.stderr)
        return 2

    counts = {}
    for status, _ in results:
        counts[status] = counts.get(status, 0) + 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"\n汇总: {summary}")
    return 0 if counts.get("DIFF", 0) == 0 and counts.get("FAIL", 0) == 0 and counts.get("MISSING", 0) == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        traceback.print_exc()
        sys.exit(130)