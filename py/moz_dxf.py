"""DXF 图纸 → 参数化模型（P1：单视图零件）。

设计、验收判据与后续阶段见 [docs/2d-to-3d.md](../docs/2d-to-3d.md)。链路：

```
解析(ezdxf) → 图层语义 → 轮廓修复 → 标注取值 → 挤出成型 →（可选）反向出图
```

要点：

- **只处理单视图零件**：外轮廓与孔都在一张图里、尺寸图纸上写死了，不需要猜。
- **轮廓修复只报告、不静默修补**：重复段、缺口、共线点、自交、分叉都会记进 ``repairs``。
- 内外环用**奇偶规则**判定（与 SCAD ``polygon(points, paths)`` 的填充规则一致），
  所以同一份点表直接交给引擎就行，不需要自己减孔。
- **标注 → 参数**：名字取 DIMENSION 的 group 1（文字覆盖），值用 ezdxf 的测量值——
  与引擎 ``dxf_dim(file, name)`` 认的是同一列，两边能对上。
- 需要 ``ezdxf``（MIT，纯 Python）：``pip install ezdxf``（或 ``pip install 'moz-openscad[dxf]'``）。

用法：

    import moz_dxf

    drawing = moz_dxf.read_dxf("plate.dxf")
    print(drawing.report())
    part = drawing.extrude(height=5.0)
    print(part.measure.volume, drawing.parameters())
"""

import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import moz_openscad as moz

try:                      # 只有解析 DXF 才需要它，所以做成可选依赖
    import ezdxf
    from ezdxf import path as _ezpath
except ImportError:       # pragma: no cover - 环境缺依赖时走这里
    ezdxf = None
    _ezpath = None

__all__ = [
    "Contour", "Dimension", "Drawing", "read_dxf", "extrude", "parameters", "report",
    "DEFAULT_LAYER_ROLES",
]

# 图层名 → 语义角色 的默认匹配（各厂命名不同，可用 layers=/hole_layers=/exclude_layers= 覆盖）
# 注意：**没匹配上的图层（other）也当几何处理**——真实图纸大多把轮廓画在 0 层或随便什么名字的
# 图层上，只有明确认出是中心线/虚线/标注/构造线的才排除。
DEFAULT_LAYER_ROLES = {
    "outline": r"outline|outer|profile|轮廓|外形|切|cut|part|板|件",
    "hole": r"hole|孔|cutout",
    "center": r"center|centre|中心|轴线|axis|sym",
    "hidden": r"hidden|虚线|dash|phantom",
    "dim": r"dim|标注|尺寸|text|注释|note",
    "construction": r"construct|辅助|构造|参考|ref",
}

# 这些角色的图层不参与几何（其余角色——含 other——都当轮廓候选）
NON_GEOMETRY_ROLES = frozenset({"center", "hidden", "dim", "construction", "excluded"})

ROLE_LABELS = {
    "outline": "轮廓",
    "hole": "孔",
    "center": "中心线（排除）",
    "hidden": "虚线（排除）",
    "dim": "标注（排除）",
    "construction": "构造线（排除）",
    "excluded": "排除",
    "other": "未命名（按轮廓处理）",
}

# $INSUNITS → 毫米的换算（0 表示"无单位"，老图常见）
UNIT_SCALES = {
    0: None,          # 无单位：按 mm 处理并给一条警告
    1: 25.4,          # 英寸
    2: 304.8,         # 英尺
    4: 1.0,           # 毫米
    5: 10.0,          # 厘米
    6: 1000.0,        # 米
    10: 914.4,        # 码
    13: 0.001,        # 微米
}

# DIMENSION 的 dimtype 低 3 位（取法与引擎 dxf_dim 一致）
DIM_KINDS = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius",
             5: "angular3p", 6: "ordinate"}

REPAIR_LABELS = {
    "duplicate": "重复线段去重",
    "zero_length": "零长线段丢弃",
    "bridge": "缺口桥接",
    "collinear": "共线点合并",
    "branch": "分叉（按最小转角继续）",
    "open_chain": "开口链（未闭合）",
    "self_intersection": "自交（仅诊断）",
}

# 自交检查是 O(n²)，点数超过这个上限就跳过并记一条诊断（避免真实大图卡死）
SELF_INTERSECTION_LIMIT = 4000

_PARSE_OPTIONS = ("layers", "exclude_layers", "hole_layers", "role_patterns", "snap_tolerance",
                  "bridge_tolerance", "arc_chord_tolerance", "collinear_tolerance", "unit_scale")


def _require_ezdxf():
    if ezdxf is None:
        raise moz.OpenSCADError(
            "需要 ezdxf 才能解析 DXF：pip install ezdxf（或 pip install 'moz-openscad[dxf]'）"
        )


@dataclass
class Contour:
    """一条修复后的轮廓。``points`` 首尾不重复，``area`` 是有符号面积（正 = 逆时针）。"""

    points: list
    closed: bool
    area: float
    role: str                 # outline / hole / open
    layer: str
    depth: int = 0            # 被多少条其它闭合轮廓包含（奇偶规则的依据）

    @property
    def is_material(self):
        """参与材料的轮廓（外轮廓与孔都算，孔靠奇偶规则挖掉）。"""
        return self.closed and self.role in ("outline", "hole")


@dataclass
class Dimension:
    """一条标注。``name`` 取 group 1（文字覆盖），没有就是 None。"""

    name: str | None
    value: float | None
    kind: str
    layer: str
    handle: str = ""


@dataclass
class Drawing:
    """一张解析好的图纸：轮廓 + 标注 + 修复报告。"""

    path: str
    version: str = ""
    units: str = "unknown"
    unit_scale: float = 1.0
    contours: list = field(default_factory=list)
    dimensions: list = field(default_factory=list)
    repairs: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    entity_counts: Counter = field(default_factory=Counter)
    layer_counts: Counter = field(default_factory=Counter)
    unsupported: Counter = field(default_factory=Counter)

    # --- 轮廓与成型 ---

    @property
    def outlines(self):
        return [c for c in self.contours if c.role == "outline" and c.closed]

    @property
    def holes(self):
        return [c for c in self.contours if c.role == "hole" and c.closed]

    @property
    def open_contours(self):
        return [c for c in self.contours if not c.closed]

    def scad_polygon(self):
        """把参与材料的轮廓交成一个 ``polygon(points, paths)``（内孔交给奇偶规则）。"""
        points, paths = [], []
        for contour in self.contours:
            if not contour.is_material:
                continue
            start = len(points)
            points.extend([[round(x, 6), round(y, 6)] for x, y in contour.points])
            paths.append(list(range(start, start + len(contour.points))))
        return points, paths

    def extrude(self, height, *, convexity=None, fn=None, fa=None, fs=None):
        """外轮廓 - 孔 挤出成型（走现有 CSG 通道，不依赖新几何内核）。"""
        points, paths = self.scad_polygon()
        if not points:
            raise moz.OpenSCADError(f"{os.path.basename(self.path)}: 没有可用的闭合轮廓（见 report()）")
        profile = moz.polygon(points, paths)
        return moz.linear_extrude(profile, height=height, convexity=convexity, fn=fn, fa=fa, fs=fs)

    def profile_area(self):
        """截面面积：按奇偶规则把孔减掉（深度为奇数算孔）。"""
        total = 0.0
        for contour in self.contours:
            if contour.is_material:
                total += abs(contour.area) if contour.depth % 2 == 0 else -abs(contour.area)
        return total

    # --- 参数 ---

    def parameters(self):
        """命名标注 → {名字: 值}（与引擎 ``dxf_dim(file, name)`` 同一列数据）。"""
        return {d.name: d.value for d in self.dimensions if d.name and d.value is not None}

    def write_parameters(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.parameters(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    # --- 报告 ---

    def report(self):
        """解析 + 修复报告（人要能照着核对；不静默）。"""
        lines = [
            f"图纸    : {self.path}",
            f"版本    : {self.version or '未知'}；单位：{self.units}（换算到 mm ×{self.unit_scale:g}）",
        ]
        layers = "、".join(
            f"{name}[{count}/{ROLE_LABELS.get(self.roles.get(name) or 'other', 'other')}]"
            for name, count in sorted(self.layer_counts.items())
        )
        lines.append(f"图层    : {layers or '（空）'}")
        entities = "、".join(f"{kind}×{count}" for kind, count in sorted(self.entity_counts.items()))
        lines.append(f"实体    : {entities or '（空）'}")
        if self.unsupported:
            skipped = "、".join(f"{kind}×{count}" for kind, count in sorted(self.unsupported.items()))
            lines.append(f"忽略    : {skipped}（P1 不处理这些实体的几何）")

        outlines, holes, opens = self.outlines, self.holes, self.open_contours
        lines.append(f"轮廓    : 闭合 {len(outlines) + len(holes)}"
                     f"（外轮廓 {len(outlines)} + 孔 {len(holes)}），开口 {len(opens)}")
        lines.append(f"截面    : {self.profile_area():.3f} mm²")

        if self.repairs:
            fixes = "、".join(
                f"{REPAIR_LABELS.get(kind, kind)} {count}" for kind, count in sorted(self.repairs.items())
            )
            lines.append(f"修复    : {fixes}")
        else:
            lines.append("修复    : （无需修复）")

        if self.dimensions:
            for dim in self.dimensions:
                name = dim.name or "（未命名）"
                value = "undef" if dim.value is None else f"{dim.value:g}"
                lines.append(f"标注    : {name} = {value}（{dim.kind}，层 {dim.layer}）")
        else:
            lines.append("标注    : （无）")

        for warning in self.warnings:
            lines.append(f"警告    : {warning}")
        return "\n".join(lines)


# --- 解析 ---


def _iter_entities(container):
    """展开 INSERT（块引用，含嵌套），产出实际实体。"""
    for entity in container:
        if entity.dxftype() == "INSERT":
            for sub in entity.virtual_entities():
                yield from _iter_entities([sub])
        else:
            yield entity


def _layer_role(layer, patterns):
    for role, pattern in patterns.items():
        if pattern and re.search(pattern, layer, re.IGNORECASE):
            return role
    return "other"


def _snap(point, tolerance):
    return (round(point[0] / tolerance) * tolerance, round(point[1] / tolerance) * tolerance)


def _entities_to_segments(drawing, entities, keep_roles, arc_chord_tolerance):
    """把实体转成线段（圆弧按弦高离散），同时统计图层/实体/忽略项。"""
    segments = []
    for entity in entities:
        kind = entity.dxftype()
        layer = entity.dxf.layer
        drawing.layer_counts[layer] += 1
        drawing.entity_counts[kind] += 1

        if kind == "DIMENSION":
            drawing.dimensions.append(_read_dimension(entity))
            continue
        role = drawing.roles.get(layer) or "other"
        if role in NON_GEOMETRY_ROLES:
            continue
        if keep_roles is not None and role not in keep_roles:
            continue

        try:
            flattened = _ezpath.make_path(entity).flattening(distance=arc_chord_tolerance)
            vertices = [(point.x, point.y) for point in flattened]
        except Exception:                      # 引擎不认识的实体 / 退化几何
            drawing.unsupported[kind] += 1
            continue
        if len(vertices) < 2:
            drawing.unsupported[kind] += 1
            continue
        segments.extend((start, end, layer) for start, end in zip(vertices, vertices[1:], strict=False))
    return segments


def _read_dimension(entity):
    text = str(entity.dxf.get("text", "") or "").strip()
    name = text if text and not text.startswith("<") and not _is_number(text) else None
    try:
        value = float(entity.get_measurement())
    except Exception:
        value = None
    dimtype = int(entity.dxf.get("dimtype", 0) or 0)
    return Dimension(name=name, value=value, kind=DIM_KINDS.get(dimtype & 7, "unknown"),
                     layer=entity.dxf.layer, handle=str(entity.dxf.get("handle", "")))


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


# --- 修复 ---


def _chain(segments, snap_tolerance, bridge_tolerance, repairs, warnings):
    """散段 → 闭合轮廓；去重、零长丢弃、缺口桥接、分叉都记进 repairs/warnings。

    ``snap_tolerance`` 只用于**判断两个端点是不是同一个节点**（浮点噪声级别）；
    输出的几何坐标一律用图纸原始值，绝不用吸附后的坐标——否则会把轮廓量化坏。
    """
    unique = []                       # (a_key, b_key, a_point, b_point, layer)
    seen = set()
    for start, end, layer in segments:
        a_key, b_key = _snap(start, snap_tolerance), _snap(end, snap_tolerance)
        if a_key == b_key:
            repairs["zero_length"] += 1
            continue
        key = (a_key, b_key) if a_key <= b_key else (b_key, a_key)
        if key in seen:
            repairs["duplicate"] += 1
            continue
        seen.add(key)
        unique.append((a_key, b_key, start, end, layer))

    on_node = defaultdict(list)
    for index, (a_key, b_key, _a, _b, _layer) in enumerate(unique):
        on_node[a_key].append(index)
        on_node[b_key].append(index)

    visited = [False] * len(unique)
    chains = []
    for start_index in range(len(unique)):
        if visited[start_index]:
            continue
        visited[start_index] = True
        start_key, end_key, start_point, end_point, layer = unique[start_index]

        def walk(closure_key, from_key, from_point, previous_index):
            """从 from_point 往回走，走到 closure_key 就是闭合。返回 (点列, 是否闭合)。"""
            points = [from_point]
            current_key, previous = from_key, previous_index
            while True:
                candidates = [i for i in on_node[current_key] if i != previous and not visited[i]]
                if not candidates:
                    return points, False
                if len(candidates) > 1:
                    repairs["branch"] += 1
                    warnings.append(
                        f"轮廓分叉：节点 {current_key} 有 {len(candidates)} 条分支，按最小转角继续"
                    )
                    candidates.sort(key=lambda i: _turn_penalty(unique, current_key, previous, i))
                index = candidates[0]
                visited[index] = True
                seg_a_key, seg_b_key, seg_a, seg_b, _layer = unique[index]
                if seg_a_key == current_key:
                    nxt_key, nxt_point = seg_b_key, seg_b
                else:
                    nxt_key, nxt_point = seg_a_key, seg_a
                points.append(nxt_point)
                previous, current_key = index, nxt_key
                if current_key == closure_key:
                    return points, True

        forward, closed = walk(start_key, end_key, end_point, start_index)      # 从 b 走到 a
        backward, _ = walk(end_key, start_key, start_point, start_index)        # 从 a 走到 b
        points = list(reversed(backward)) + forward

        if not closed:
            first, last = points[0], points[-1]
            if math.hypot(first[0] - last[0], first[1] - last[1]) <= bridge_tolerance:
                repairs["bridge"] += 1
                closed = True
            else:
                repairs["open_chain"] += 1
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        chains.append((points, closed, layer))
    return chains


def _turn_penalty(unique, node_key, previous_index, candidate_index):
    """分叉处挑"最像直着走下去"的那条（转角越小越优先）。"""

    def direction(index, key):
        a_key, b_key, a_point, b_point, _layer = unique[index]
        if a_key == key:
            return (b_point[0] - a_point[0], b_point[1] - a_point[1])
        return (a_point[0] - b_point[0], a_point[1] - b_point[1])

    incoming = direction(previous_index, node_key) if previous_index is not None else (1.0, 0.0)
    outgoing = direction(candidate_index, node_key)
    norm_in = math.hypot(*incoming) or 1.0
    norm_out = math.hypot(*outgoing) or 1.0
    cos_angle = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (norm_in * norm_out)
    return -cos_angle            # cos 越大（转角越小）越优先


def _drop_collinear(points, tolerance, repairs):
    """去掉位于相邻两点连线上的中间点（只减点数，不改面积）。"""
    if len(points) < 4:
        return points
    kept = []
    for index, point in enumerate(points):
        previous = points[index - 1]
        nxt = points[(index + 1) % len(points)]
        if _point_line_distance(point, previous, nxt) <= tolerance:
            repairs["collinear"] += 1
            continue
        kept.append(point)
    return kept if len(kept) >= 3 else points


def _point_line_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    return abs(dy * (point[0] - start[0]) - dx * (point[1] - start[1])) / length


def _signed_area(points):
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _point_in_polygon(point, polygon):
    """射线法（奇偶规则），与 SCAD polygon 的填充规则一致。"""
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if (y1 > y) != (y2 > y):
            if x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
                inside = not inside
    return inside


def _count_self_intersections(points, limit=SELF_INTERSECTION_LIMIT):
    """自交诊断：统计不相邻线段之间的真交叉数（点数超过上限返回 None）。"""
    total = len(points)
    if total > limit:
        return None
    count = 0
    for i in range(total):
        a1, a2 = points[i], points[(i + 1) % total]
        for j in range(i + 1, total):
            if j == i + 1 or (i == 0 and j == total - 1):
                continue                                   # 相邻段共端点，不算自交
            b1, b2 = points[j], points[(j + 1) % total]
            if _segments_cross(a1, a2, b1, b2):
                count += 1
    return count


def _segments_cross(a1, a2, b1, b2):
    def cross(origin, first, second):
        return ((first[0] - origin[0]) * (second[1] - origin[1])
                - (first[1] - origin[1]) * (second[0] - origin[0]))

    d1, d2 = cross(b1, b2, a1), cross(b1, b2, a2)
    d3, d4 = cross(a1, a2, b1), cross(a1, a2, b2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


# --- 对外 API ---


def read_dxf(path, *, layers=None, exclude_layers=None, hole_layers=None, role_patterns=None,
             snap_tolerance=0.001, bridge_tolerance=0.05, arc_chord_tolerance=0.01,
             collinear_tolerance=1e-6, unit_scale=None):
    """读一张 DXF，返回 ``Drawing``（轮廓已修复、标注已提取）。

    - ``layers``：只处理这些图层（给名字列表）；否则按 ``role_patterns`` 判断角色，
      只保留 outline/hole 两类参与几何；
    - ``exclude_layers``：直接排除的图层（例如 DIM/SCRAP）；
    - ``hole_layers``：强制当作孔的图层（比奇偶规则优先）；
    - ``snap_tolerance``：端点是否同一节点的判定容差（mm，只影响拓扑判断，不动坐标）；
    - ``bridge_tolerance``：缺口桥接容差（mm，真实图纸画断一点点很常见）；
    - ``arc_chord_tolerance``：圆弧离散的弦高容差（mm），越小越圆、点越多；
    - ``unit_scale``：覆盖图纸单位（图纸没写单位时默认按 mm）。
    """
    _require_ezdxf()
    if not os.path.exists(path):
        raise moz.OpenSCADError(f"找不到 DXF 文件：{path}")

    try:
        document = ezdxf.readfile(path)
    except Exception as exc:                       # 格式坏（例如小数点是逗号）也要给能读懂的错
        raise moz.OpenSCADError(f"解析 DXF 失败：{path}（{type(exc).__name__}: {exc}）") from exc
    patterns = dict(DEFAULT_LAYER_ROLES)
    if role_patterns:
        patterns.update(role_patterns)
    if layers is not None:
        patterns = dict.fromkeys(patterns)
        patterns["outline"] = "^(" + "|".join(re.escape(name) for name in layers) + ")$"

    drawing = Drawing(path=path, version=document.dxfversion or "")
    drawing.roles = {layer.dxf.name: _layer_role(layer.dxf.name, patterns) for layer in document.layers}
    drawing.roles.setdefault("0", "other")
    for name in exclude_layers or ():
        drawing.roles[name] = "excluded"
    for name in hole_layers or ():
        drawing.roles[name] = "hole"

    units = document.header.get("$INSUNITS")
    units = int(units) if isinstance(units, int | float) else None
    if unit_scale is not None:
        drawing.unit_scale = float(unit_scale)
        drawing.units = f"手动指定（×{unit_scale:g}）"
    elif units in UNIT_SCALES and UNIT_SCALES[units] is not None:
        drawing.unit_scale = UNIT_SCALES[units]
        drawing.units = f"$INSUNITS={units}"
    else:
        drawing.unit_scale = 1.0
        drawing.units = "无单位信息" if units in (None, 0) else f"$INSUNITS={units}（未支持，按 mm）"
        drawing.warnings.append("图纸没有（或用了不支持的）单位信息，按 mm 处理；需要时用 unit_scale= 覆盖")

    keep_roles = None if layers is None else {"outline"}      # None = 收所有非「非几何」角色
    entities = list(_iter_entities(document.modelspace()))
    segments = _entities_to_segments(drawing, entities, keep_roles, arc_chord_tolerance)

    repairs = defaultdict(int)
    chains = _chain(segments, snap_tolerance, bridge_tolerance, repairs, drawing.warnings)

    contours = []
    for points, closed, layer in chains:
        points = [(x * drawing.unit_scale, y * drawing.unit_scale) for x, y in points]
        if closed:
            points = _drop_collinear(points, collinear_tolerance * max(drawing.unit_scale, 1.0), repairs)
        contours.append(Contour(points=points, closed=closed, role="open" if not closed else "outline",
                                area=_signed_area(points) if len(points) >= 3 else 0.0, layer=layer))

    # 奇偶规则定内外环：被奇数条**更大**的闭合轮廓包含 → 孔
    # （包含判定用轮廓顶点做探针，不用质心：外轮廓的质心可能正好落在某个孔里面）
    closed_contours = [contour for contour in contours if contour.closed]
    for contour in closed_contours:
        probe = contour.points[0]
        contour.depth = sum(
            1 for other in closed_contours
            if other is not contour
            and abs(other.area) > abs(contour.area) * (1 + 1e-9)
            and _point_in_polygon(probe, other.points)
        )
        contour.role = "hole" if contour.depth % 2 else "outline"
        if drawing.roles.get(contour.layer) == "hole":
            contour.role = "hole"

    for contour in closed_contours:
        crossings = _count_self_intersections(contour.points)
        if crossings:
            repairs["self_intersection"] += crossings
        elif crossings is None:
            drawing.warnings.append(
                f"轮廓点数 {len(contour.points)} 超过自交检查上限（{SELF_INTERSECTION_LIMIT}），未做自交诊断"
            )

    drawing.contours = sorted(contours, key=lambda contour: (contour.role, -abs(contour.area)))
    drawing.repairs = dict(sorted(repairs.items()))
    return drawing


def extrude(source, height, **options):
    """便捷入口：``extrude("plate.dxf", 5.0)`` 或 ``extrude(drawing, 5.0)``。"""
    if isinstance(source, Drawing):
        return source.extrude(height, **options)
    parse_options = {key: options.pop(key) for key in list(options) if key in _PARSE_OPTIONS}
    return read_dxf(source, **parse_options).extrude(height, **options)


def parameters(path, **options):
    """便捷入口：命名标注 → {名字: 值}。"""
    return read_dxf(path, **options).parameters()


def report(path, **options):
    """便捷入口：解析 + 修复报告文本。"""
    return read_dxf(path, **options).report()
