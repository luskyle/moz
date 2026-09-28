"""moz_cadview —— 直接画 DXF/DWG 的看图器（不经过几何内核）。

数据来自 ``py/moz_cadio.py`` 的"规范化 2D 实体模型"；libdxfrw 读不通的 **DXF** 会用 ezdxf
兜底（见 :func:`load`），两条解析路径都喂同一套渲染层——渲染层只认那个模型。

渲染是**直画**：QGraphicsScene + 每种图元自己的 item，不做 SCAD 几何。所以拿到的东西比
"丢给引擎再导出 SVG"多：图层可开关、颜色（ACI/真彩/BYLAYER）、线型（虚线/中心线）、
真曲线样条、文字（系统字体）、块展开（含阵列与嵌套）、标注（用它的匿名块）。

命令行：

    PYTHONPATH=py python3 py/moz_cadview.py 图纸.dxf                 # 打开窗口
    PYTHONPATH=py python3 py/moz_cadview.py 图纸.dwg --report         # 只打印解析报告（无窗口）
    PYTHONPATH=py python3 py/moz_cadview.py 图纸.dxf --layers         # 列出图层与每层图元数
    PYTHONPATH=py python3 py/moz_cadview.py 图纸.dxf --export-png out.png --export-svg out.svg
    PYTHONPATH=py python3 py/moz_cadview.py 图纸.dxf --stats          # 画出来的 item 数（CI 用）

装好后也可以用入口脚本：``moz-cadview 图纸.dwg``。
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import moz_cadio

__all__ = ["AciTable", "CadView", "build_scene", "describe", "export", "load",
           "linetype_pattern", "main", "resolve_colour"]

# 线型名 → 虚线样式（以线宽为单位；真实 DXF 的线型定义在 LTYPE 表里，我们没解析，
# 所以这里是**视觉近似**：能区分实线/虚线/中心线/点划线就够了）
LINETYPE_PATTERNS = {
    "CONTINUOUS": None,
    "SOLID": None,
    "DASHED": (6.0, 3.0),
    "DASHED2": (5.0, 2.0),
    "DASHEDX2": (12.0, 6.0),
    "HIDDEN": (4.0, 2.0),
    "HIDDEN2": (3.5, 1.5),
    "CENTER": (12.0, 3.0, 3.0, 3.0),
    "CENTER2": (9.0, 2.0, 2.5, 2.0),
    "DASHDOT": (9.0, 3.0, 1.0, 3.0),
    "DASHDOT2": (7.0, 2.0, 1.0, 2.0),
    "DOT": (1.0, 3.0),
    "PHANTOM": (16.0, 3.0, 3.0, 3.0, 3.0, 3.0),
}


def linetype_pattern(name):
    """线型名 → 虚线样式元组（``None`` 表示实线）。名字不认就按实线。"""
    if not name:
        return None
    return LINETYPE_PATTERNS.get(str(name).upper())


class AciTable:
    """AutoCAD 颜色索引（ACI）→ RGB。

    1–9 是固定色；10–249 是"24 色相 × 10 档"的色轮，250–255 是灰阶。这里用的是
    **色轮算法**（不是逐项抄表），肉眼够用；BYLAYER(256)/BYBLOCK(0) 由调用方解析。
    """

    FIXED = {
        1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
        5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128),
        9: (192, 192, 192),
    }

    def __init__(self, background_dark=True):
        self.background_dark = background_dark
        self._cache = {}

    def rgb(self, index):
        if index in self._cache:
            return self._cache[index]
        colour = self._compute(index)
        self._cache[index] = colour
        return colour

    def _compute(self, index):
        if index in self.FIXED:
            if index == 7:
                return (255, 255, 255) if self.background_dark else (0, 0, 0)
            return self.FIXED[index]
        if 10 <= index <= 249:
            step = index - 10
            hue = (step // 10) * 15.0
            shade = step % 10
            value = 1.0 - 0.075 * shade
            saturation = 1.0 if shade < 2 else max(0.3, 1.0 - 0.12 * (shade - 2))
            return self._hsv(hue, saturation, value)
        if 250 <= index <= 255:
            level = int(255 * (index - 249) / 7.0)
            return (level, level, level)
        return (255, 255, 255) if self.background_dark else (0, 0, 0)

    @staticmethod
    def _hsv(hue, saturation, value):
        hue = hue % 360.0
        chroma = value * saturation
        sector = hue / 60.0
        second = chroma * (1.0 - abs(sector % 2.0 - 1.0))
        table = [(chroma, second, 0.0), (second, chroma, 0.0), (0.0, chroma, second),
                 (0.0, second, chroma), (second, 0.0, chroma), (chroma, 0.0, second)]
        red, green, blue = table[int(sector) % 6]
        offset = value - chroma
        return tuple(int(round(255 * (channel + offset))) for channel in (red, green, blue))


def resolve_colour(entity, layer, aci_table):
    """实体颜色：真彩优先 → ACI（BYLAYER 跟图层、BYBLOCK 按白）→ 图层颜色。"""
    if entity.color24 is not None:
        value = entity.color24
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
    index = entity.aci
    if index == moz_cadio.BYLAYER:
        index = layer.aci if layer else moz_cadio.BYLAYER
        if index == moz_cadio.BYLAYER:                 # 图层也是 BYLAYER：按 7 号色
            index = 7
    elif index == moz_cadio.BYBLOCK:
        index = 7
    return aci_table.rgb(index)


def load(path):
    """读一张图：先 libdxfrw；**DXF** 读不通时用 ezdxf 兜底（产出同一种模型）。"""
    try:
        return moz_cadio.read(path)
    except moz_cadio.CadIoError as primary:
        if not os.path.exists(path) or os.path.splitext(path)[1].lower() != ".dxf":
            raise
        return _load_with_ezdxf(path, primary)


def _load_with_ezdxf(path, primary):
    """ezdxf 兜底读取：把 ezdxf 的文档翻成 ``moz_cadio`` 的模型（同一个渲染层吃它）。"""
    try:
        import ezdxf
    except ImportError:
        raise primary from None
    try:
        document = ezdxf.readfile(path)
    except Exception:
        try:
            from ezdxf.recover import readfile as recover_readfile
            document, _auditor = recover_readfile(path)
        except Exception as recovery:
            raise moz_cadio.CadIoError(
                f"读不了这张图——libdxfrw：{primary}；ezdxf 兜底也不行："
                f"{type(recovery).__name__}: {recovery}") from None

    cad = moz_cadio.CadFile(path=path, format="dxf", version=document.dxfversion or "")
    cad.warnings.append(f"libdxfrw 读不了这张图（{primary}），已改用 ezdxf 兜底：几何可能有偏差")
    units = document.header.get("$INSUNITS")
    cad.insunits = int(units) if isinstance(units, int) else 0
    for layer in document.layers:
        cad.layers.append(moz_cadio.Layer(
            name=layer.dxf.name, aci=abs(int(layer.dxf.color)), color24=None,
            linetype=getattr(layer.dxf, "linetype", None),
            off=int(layer.dxf.color) < 0, frozen=bool(layer.dxf.flags & 1),
            locked=bool(layer.dxf.flags & 4)))
    for block in document.blocks:
        cad.blocks.append(moz_cadio.Block(
            name=block.name, base_point=tuple(block.block.dxf.base_point)[:3],
            first_entity=0, entity_count=len(list(block))))
    for owner, container in _containers(document):
        for ez in container:
            entity = _entity_from_ezdxf(ez, owner)
            if entity is None:
                continue
            cad.entities.append(entity)
    return cad


def _containers(document):
    """(owner, 容器) 列表：模型空间 owner 是空串，块内容 owner 是块名。"""
    yield "", document.modelspace()
    for block in document.blocks:
        yield block.name, block


def _points(values, count):
    flat = []
    for item in values:
        if hasattr(item, "x"):
            flat += [float(item.x), float(item.y)]
        elif isinstance(item, tuple | list):
            flat += [float(item[0]), float(item[1])]
        else:
            flat.append(float(item))
    return tuple(flat[: count * 2])


def _attribute_getter(attributes):
    """取 DXF 属性并转 float（ezdxf 缺字段时给默认值）。"""
    def get(name, default=0.0):
        return float(getattr(attributes, name, default) or 0.0)
    return get


def _entity_from_ezdxf(ez, owner):
    """一个 ezdxf 实体 → ``moz_cadio.Entity``（认不出的返回 None，并计一条告警由调用方汇总）。"""
    kind = ez.dxftype()
    attributes = getattr(ez, "dxf", None)
    true_color = getattr(attributes, "true_color", None)
    entity = moz_cadio.Entity(
        kind=kind if kind in moz_cadio.KIND_NAMES.values() else "UNKNOWN",
        layer=getattr(attributes, "layer", "0") or "0",
        aci=int(getattr(attributes, "color", moz_cadio.BYLAYER) or moz_cadio.BYLAYER),
        color24=None if true_color is None else int(true_color),
        linetype=getattr(attributes, "linetype", None),
        owner=owner,
        visible=not bool(getattr(attributes, "invisible", 0)),
        ltscale=float(getattr(attributes, "linetype_scale", 1.0) or 1.0),
    )
    attribute = _attribute_getter(attributes)

    if kind == "LINE":
        entity.p1 = _xyz(attributes.start)
        entity.p2 = _xyz(attributes.end)
        entity.kind = "LINE"
    elif kind == "POINT":
        entity.p1 = _xyz(attributes.location)
    elif kind == "CIRCLE":
        entity.p1 = _xyz(attributes.center)
        entity.radius = attribute("radius")
    elif kind == "ARC":
        entity.p1 = _xyz(attributes.center)
        entity.radius = attribute("radius")
        entity.start_angle = math.radians(attribute("start_angle"))
        entity.end_angle = math.radians(attribute("end_angle"))
    elif kind == "ELLIPSE":
        entity.p1 = _xyz(attributes.center)
        major = attributes.major_axis
        entity.p2 = (float(major.x), float(major.y), float(major.z))
        entity.ratio = attribute("ratio", 1.0)
        entity.start_angle = attribute("start_param")
        entity.end_angle = attribute("end_param")
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        points, bulges = [], []
        for vertex in ez.get_points("xyb") if kind == "LWPOLYLINE" else ez.points():
            points += [float(vertex[0]), float(vertex[1])]
            bulges.append(float(vertex[-1]) if kind == "LWPOLYLINE" else
                          float(getattr(vertex, "bulge", 0.0) or 0.0))
        entity.kind = "LWPOLYLINE" if kind == "LWPOLYLINE" else "POLYLINE"
        entity.points = tuple(points)
        entity.bulges = tuple(bulges)
        entity.flags |= moz_cadio.FLAG_CLOSED if ez.closed else 0
    elif kind == "SPLINE":
        entity.points = _points(ez.control_points, len(ez.control_points))
        entity.knots = tuple(float(value) for value in getattr(ez, "knots", ()) or ())
        entity.weights = tuple(float(value) for value in getattr(ez, "weights", ()) or ())
        entity.degree = float(getattr(ez, "degree", 3) or 3)
        if getattr(ez, "closed", False):
            entity.flags |= moz_cadio.FLAG_CLOSED
        if entity.weights:
            entity.flags |= moz_cadio.FLAG_RATIONAL
    elif kind == "INSERT":
        entity.p1 = _xyz(attributes.insert)
        entity.name = attributes.name
        entity.rotation = math.radians(attribute("rotation"))
        entity.xscale = attribute("xscale", 1.0)
        entity.yscale = attribute("yscale", 1.0)
        entity.colcount = int(getattr(attributes, "column_count", 1) or 1)
        entity.rowcount = int(getattr(attributes, "row_count", 1) or 1)
        entity.colspace = attribute("column_spacing")
        entity.rowspace = attribute("row_spacing")
    elif kind in ("TEXT", "MTEXT"):
        entity.p1 = _xyz(attributes.insert)
        entity.text = getattr(attributes, "text", "") or ""
        entity.height = attribute("height")
        entity.rotation = math.radians(attribute("rotation"))
    elif kind == "DIMENSION":
        entity.dimtype = int(getattr(attributes, "dimtype", 0) or 0)
        entity.p1 = _xyz(attributes.defpoint)
        entity.text = getattr(attributes, "text", None) or None
        entity.name = getattr(attributes, "geometry", None)
    elif kind == "HATCH":
        loops, offsets, total = [], [], 0
        for path in ez.paths:
            points = []
            for vertex in getattr(path, "vertices", []) or []:
                points.append((float(vertex[0]), float(vertex[1])))
            loops += [value for point in points for value in point]
            total += len(points)
            offsets.append(total)
        entity.points = tuple(loops)
        entity.loop_offsets = tuple(offsets)
        entity.name = getattr(attributes, "pattern_name", None)
        if getattr(attributes, "solid_fill", 0):
            entity.flags |= moz_cadio.FLAG_SOLID
    elif kind in ("SOLID", "TRACE", "3DFACE"):
        entity.p1 = _xyz(getattr(attributes, "vtx0", None))
        entity.p2 = _xyz(getattr(attributes, "vtx1", None))
        entity.p3 = _xyz(getattr(attributes, "vtx2", None))
    else:
        return None
    return entity


def _xyz(value):
    if value is None:
        return None
    return (float(value.x), float(value.y), float(getattr(value, "z", 0.0)))


def _empty_notice(missing, notes, warnings=()):
    """一张图什么都没画出来时，在画面中央写清楚为什么（而不是给一块白板）。"""
    lines = ["这张图没有可绘制的图元"]
    if missing:
        lines.append("原因：" + "、".join(missing[:3]))
    elif warnings:
        lines.append("原因：" + str(warnings[0])[:60])
    if notes:
        lines.append("推断：" + "、".join(notes[:2]))
    lines.append("右侧「图纸」面板里点另一张试试")
    return "\n".join(lines)


def build_scene(cad, *, chord_tolerance=0.05, aci_table=None, dark=True):
    """把模型画成 ``QGraphicsScene``（返回 scene、每层 item、各类型计数、缺块原因、推断说明）。

    这里是**直画**：折线、填充、文字各用合适的 item，不做几何内核求值。
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QTransform
    from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsSimpleTextItem

    if QApplication.instance() is None:
        # 没有 QApplication 就去碰 QGraphicsScene 会**段错误**（Qt 的硬要求），所以这里明确报错：
        # 命令行入口（main）与 py/tests 的 qt_app fixture 都已经建好。
        raise RuntimeError("画图前要先建 QApplication（无显示器时设 QT_QPA_PLATFORM=offscreen）")

    aci_table = aci_table or AciTable(background_dark=dark)
    scene = QGraphicsScene()
    layers = {layer.name: layer for layer in cad.layers}
    per_layer = {}
    counts = {}

    def colour_for(entity):
        layer = layers.get(entity.layer)
        return QColor(*resolve_colour(entity, layer, aci_table))

    def pen_for(entity):
        pen = QPen(colour_for(entity))
        pen.setCosmetic(False)
        pen.setWidthF(0.0)                     # 0 = 1 像素（随视图缩放不魔改线宽）
        pattern = linetype_pattern(entity.linetype or (layers.get(entity.layer).linetype
                                                       if entity.layer in layers else None))
        if pattern:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern(list(pattern))
        return pen

    def add(item, entity, *, to_scene=True):
        if to_scene:
            scene.addItem(item)
        per_layer.setdefault(entity.layer, []).append(item)
        counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return item

    scale_box = _drawing_extent(cad)
    missing, notes = [], []
    for entity, matrix in moz_cadio.iter_draw(cad, missing=missing, notes=notes):
        if entity.kind in ("TEXT", "MTEXT"):
            text = (entity.text or "").split("\n")[0]
            if not text or not entity.p1:
                continue
            position = moz_cadio.matrix_apply(matrix, entity.p1)
            scale = math.hypot(matrix[0], matrix[3]) or 1.0
            turn = math.atan2(matrix[3], matrix[0])        # 块变换带来的旋转
            item = QGraphicsSimpleTextItem(text)
            font = QFont()
            font.setPixelSize(max(1, int(round(entity.height or 2.5))))
            item.setFont(font)
            item.setBrush(QBrush(colour_for(entity)))
            item.setPos(QPointF(position[0], position[1]))
            item.setRotation(-math.degrees(entity.rotation + turn))
            # 视图 Y 翻转，文字要翻回来（缩放也跟着块变换走）
            item.setTransform(QTransform().scale(scale, -scale), True)
            add(item, entity)
            continue
        if entity.kind == "POINT":
            if not entity.p1:
                continue
            centre = moz_cadio.matrix_apply(matrix, entity.p1)
            radius = max(0.05, scale_box * 0.0015)
            item = scene.addEllipse(centre[0] - radius, centre[1] - radius,
                                    radius * 2, radius * 2, pen_for(entity))
            add(item, entity, to_scene=False)      # addEllipse 已经把它加进场景了
            continue
        for chain in _chains_for(entity, matrix, scale_box, chord_tolerance):
            if len(chain) < 2:
                continue
            path = QPainterPath(QPointF(*chain[0]))
            for point in chain[1:]:
                path.lineTo(QPointF(*point))
            if entity.closed or entity.kind in ("SOLID", "TRACE", "3DFACE"):
                path.closeSubpath()
            if entity.kind in ("SOLID", "TRACE", "3DFACE") or (entity.kind == "HATCH"
                                                               and entity.solid):
                item = scene.addPath(path, pen_for(entity), QBrush(colour_for(entity)))
            else:
                item = scene.addPath(path, pen_for(entity))
            add(item, entity, to_scene=False)      # addPath 已经加进场景了
    if not counts and not per_layer:
        _add_empty_notice(scene, missing, notes, dark, cad.warnings)
    return scene, per_layer, counts, missing, notes


def _add_empty_notice(scene, missing, notes, dark, warnings=()):  # pragma: no cover - 需要 Qt
    """空画面时写一句原因（场景没有内容，"适应视角"也就没有意义，所以自己定一个画面范围）。"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QTransform
    from PySide6.QtWidgets import QGraphicsSimpleTextItem

    if not scene.sceneRect().isValid() or scene.itemsBoundingRect().isEmpty():
        scene.setSceneRect(QRectF(-140.0, -80.0, 280.0, 160.0))
    item = QGraphicsSimpleTextItem(_empty_notice(missing, notes, warnings))
    font = QFont()
    font.setPixelSize(12)
    item.setFont(font)
    item.setBrush(QColor(255, 220, 120) if dark else QColor(160, 90, 0))
    item.setPos(-132.0, -34.0)
    item.setTransform(QTransform().scale(1, -1), True)     # 视图 Y 翻转，文字翻回来
    scene.addItem(item)
    return item


def _drawing_extent(cad):
    """图纸的大致尺度（给 RAY/XLINE 用）。"""
    if cad.extents:
        low, high = cad.extents
        return max(1.0, abs(high[0] - low[0]), abs(high[1] - low[1]))
    span = 1.0
    for entity in cad.entities[:2000]:
        for point in (entity.p1, entity.p2, entity.p3):
            if point:
                span = max(span, abs(point[0]), abs(point[1]))
    return span * 2.0


def _chains_for(entity, matrix, extent, chord_tolerance):
    """图元 → 世界坐标下的折线列表（RAY/XLINE 按图纸尺度拉长）。"""
    if entity.kind in ("RAY", "XLINE"):
        start, direction = entity.p2d("p1"), entity.p2d("p2")
        if not start or not direction:
            return []
        dx, dy = direction[0] - start[0], direction[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return []
        reach = extent * 20.0
        forward = (start[0] + dx / length * reach, start[1] + dy / length * reach)
        backward = (start[0] - dx / length * reach, start[1] - dy / length * reach)
        chain = [backward, forward] if entity.kind == "XLINE" else [start, forward]
        return [[moz_cadio.matrix_apply(matrix, point) for point in chain]]
    chains = []
    for chain in moz_cadio.entity_polylines(entity, chord_tolerance):
        chains.append([moz_cadio.matrix_apply(matrix, point) for point in chain if point])
    return chains


def _is_within(path, root):
    """``path`` 是否在 ``root`` 目录树里（判断"还在选中的目录里"用）。"""
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    return path == root or path.startswith(root + os.sep)


DRAWING_LIMIT = 500          # 图纸列表一次最多列这么多（很多层级的大目录要有个上限）


def problems_text(cad, counts=None, missing=(), notes=()):
    """当前这张图纸的"问题 / 提示"全文——窗口下方那个面板里显示，不截断。

    状态栏只放一行摘要（会被截断），全文在这里：读到的告警、没画出来的原因、推断说明。
    """
    lines = [f"文件：{cad.path}",
             f"格式：{cad.format.upper()} {cad.version}｜单位：{cad.units_name}",
             "画出来的：" + (describe(counts) if counts else "（什么都没有）")]
    if missing:
        lines += ["", "没画出来的原因："] + [f"  · {item}" for item in missing]
    if notes:
        lines += ["", "推断出来的："] + [f"  · {item}" for item in notes]
    if cad.warnings:
        lines += ["", f"读取时的告警（{len(cad.warnings)} 条）："] + [f"  · {text}" for text in cad.warnings]
    if not (missing or notes or cad.warnings):
        lines += ["", "没有告警：这张图读得干净。"]
    return "\n".join(lines)


def failure_text(path, error):
    """打开失败时的全文说明（比状态栏那一行详细得多）。"""
    return "\n".join([
        f"文件：{path}", "", "打不开：", f"  {error}", "",
        "常见原因：",
        "  · R2.5 及更早的 DWG：上游 libdxfrw 没有对应读取器（报错里会写明）",
        "  · 文件损坏、部分加密，或用了上游没实现的 DWG 特性（DWG 支持是「尽力而为」）",
        "  · 扩展名是 .dwg/.dxf 而内容其实是别的格式（改对扩展名再试）",
        "  · DXF 连 ezdxf 兜底也失败（消息里会同时给出两种原因）",
        "",
        "想批量看目录里哪些文件有问题：moz-cadview <目录> --scan",
    ])


def first_drawable(entries, probe=5):
    """从前面几张里挑一张**画得出来**的（实测语料里真有整张画不出东西的），都不行就用第一张。

    只探前 ``probe`` 张：在几百张的目录上全都试一遍太慢。
    """
    for path in entries[:max(1, probe)]:
        try:
            cad = load(path)
        except moz_cadio.CadIoError:
            continue
        if any(True for _ in moz_cadio.iter_draw(cad)):
            return path
    return entries[0]


def list_drawings(directory, recursive=False, limit=DRAWING_LIMIT):
    """目录里的 DXF/DWG，按路径排序；``recursive=True`` 时连子目录一起找。

    看图器的"图纸列表"用它（打开目录后可以逐个点着看）：显式打开目录用递归，
    只是顺手列出当前文件所在的同级文件就不递归。到 ``limit`` 就截断（调用方应说明）。
    """
    found = []
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for name in sorted(files):
                if name.lower().endswith((".dxf", ".dwg")):
                    found.append(os.path.join(root, name))
                    if len(found) >= limit:
                        return sorted(found)
    else:
        try:
            for name in sorted(os.listdir(directory)):
                path = os.path.join(directory, name)
                if name.lower().endswith((".dxf", ".dwg")) and os.path.isfile(path):
                    found.append(path)
        except OSError:
            return []
    return sorted(found)


def _make_window(on_drop):  # pragma: no cover - 需要 Qt
    """主窗口：接受"把图纸拖进来就打开"（拖目录也行）。PySide6 延迟导入。"""
    from PySide6.QtWidgets import QMainWindow

    class CadWindow(QMainWindow):
        def dragEnterEvent(self, event):
            if _dropped_path(event) is not None:
                event.acceptProposedAction()

        def dropEvent(self, event):
            path = _dropped_path(event)
            if path is not None:
                on_drop(path)
                event.acceptProposedAction()

    return CadWindow()


def _dropped_path(event):  # pragma: no cover - 需要 Qt
    """拖进来的第一个 DXF/DWG 或目录（都不是就返回 None）。"""
    for url in event.mimeData().urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith((".dxf", ".dwg")) or os.path.isdir(path):
            return path
    return None


def _make_view():  # pragma: no cover - 需要 Qt
    """看图用的 QGraphicsView：**滚轮缩放**（以光标为锚点），左键拖动平移。"""
    from PySide6.QtWidgets import QGraphicsView

    class CadGraphicsView(QGraphicsView):
        def wheelEvent(self, event):
            factor = 1.2 if event.angleDelta().y() >= 0 else 1.0 / 1.2
            self.scale(factor, factor)
            event.accept()

    return CadGraphicsView()


class CadView:  # pragma: no cover - 需要显示器/offscreen 平台
    """看图窗口：QGraphicsView + **图纸列表**（可点着切换）+ 图层开关 + 打开/拖拽换图。"""

    def __init__(self, cad, dark=True, title=None, directory=None, recursive=False):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction, QKeySequence, QPainter
        from PySide6.QtWidgets import QGraphicsView, QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

        self.dark = dark
        self.directory = None
        self.recursive = recursive
        window = _make_window(self.open_any)
        view = _make_view()
        view.setRenderHint(QPainter.Antialiasing, False)
        view.scale(1.0, -1.0)                       # DXF 的 Y 向上，Qt 的 Y 向下
        view.setDragMode(QGraphicsView.ScrollHandDrag)
        view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        window.setCentralWidget(view)

        drawings = QListWidget()                    # 图纸列表：点一下就换图
        drawings.itemClicked.connect(self._on_drawing_clicked)
        layers = QListWidget()                      # 图层开关
        layers.itemChanged.connect(self._on_layer_toggled)

        files = window.menuBar().addMenu("文件")
        open_action = QAction("打开 DXF/DWG…", window)
        open_action.setShortcut(QKeySequence.Open)          # Ctrl+O
        open_action.triggered.connect(self.open_dialog)
        files.addAction(open_action)
        open_dir_action = QAction("打开目录…", window)
        open_dir_action.setShortcut("Ctrl+Shift+O")
        open_dir_action.triggered.connect(self.open_directory_dialog)
        files.addAction(open_dir_action)
        quit_action = QAction("退出", window)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(window.close)
        files.addAction(quit_action)

        views = window.menuBar().addMenu("视图")
        reset = QAction("重置视角", window)
        reset.setShortcut("Home")
        reset.triggered.connect(self.fit)
        views.addAction(reset)

        report = QPlainTextEdit()
        report.setReadOnly(True)
        report.setLineWrapMode(QPlainTextEdit.NoWrap)
        report.setPlaceholderText("这里显示当前图纸遇到的问题（打开失败、没画出来的原因、读取告警）")
        copy_button = QPushButton("复制这些问题")
        copy_button.clicked.connect(self.copy_report)
        report_panel = QWidget()
        report_layout = QVBoxLayout(report_panel)
        report_layout.setContentsMargins(4, 4, 4, 4)
        report_layout.addWidget(report, 1)
        report_layout.addWidget(copy_button)

        window.resize(1200, 800)
        window.addDockWidget(Qt.RightDockWidgetArea, _dock(window, "图纸", drawings, 300))
        window.addDockWidget(Qt.RightDockWidgetArea, _dock(window, "图层", layers))
        self.report_dock = _dock(window, "问题（当前图纸）", report_panel, 420)
        window.addDockWidget(Qt.BottomDockWidgetArea, self.report_dock)
        views.addAction(self.report_dock.toggleViewAction())       # 视图菜单里可开关
        self.window = window
        self.view = view
        self.drawings = drawings
        self.layers = layers
        self.report = report
        self.cad = cad
        self.scene = None
        self.per_layer = {}
        self.counts = {}
        # 打开失败时是否弹模态框（测试/脚本里可以关掉，只留状态栏消息）
        self.warn_on_error = True
        if title:
            self.window.setWindowTitle(title)
        self._build(cad)
        self.set_directory(directory or (
            os.path.dirname(os.path.abspath(cad.path)) if cad.path else os.getcwd()),
            recursive=recursive)

    # --- 换图（首次、点列表、打开对话框、拖拽都走这里） ---

    def _build(self, cad):
        """按一张图纸重建场景与图层面板（并把视角适应到内容）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        scene, per_layer, counts, missing, notes = build_scene(cad, dark=self.dark)
        self.cad, self.scene, self.per_layer, self.counts = cad, scene, per_layer, counts
        self.missing, self.notes = missing, notes
        self.view.setScene(scene)
        self.window.setWindowTitle(f"moz-cadview — {os.path.basename(cad.path)}")
        self.layers.blockSignals(True)
        self.layers.clear()
        for name in sorted(per_layer):
            item = QListWidgetItem(f"{name}（{len(per_layer[name])}）")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, name)
            self.layers.addItem(item)
        self.layers.blockSignals(False)
        summary = describe(counts) if counts else "没有可绘制的图元"
        if missing:
            summary += f"；缺块定义 {len(missing)} 个：{missing[:3]}"
        if notes:
            summary += f"；{notes[0]}"
        self.window.statusBar().showMessage(
            f"{cad.format.upper()} {cad.version}｜{summary}｜滚轮缩放、左键拖动、Ctrl+O 打开")
        self.set_report(problems_text(cad, counts, missing, notes))
        self.fit()

    def set_directory(self, directory, recursive=False, limit=DRAWING_LIMIT):
        """把"图纸列表"填成这个目录里的图纸，并选中当前这张（不在里面就不选）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        self.directory = directory
        self.recursive = recursive
        entries = list_drawings(directory, recursive=recursive, limit=limit)
        current = os.path.abspath(self.cad.path) if self.cad.path else ""
        self.drawings.blockSignals(True)
        self.drawings.clear()
        selected = -1
        for index, path in enumerate(entries):
            label = os.path.relpath(path, directory) if recursive else os.path.basename(path)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.drawings.addItem(item)
            if os.path.abspath(path) == current:
                selected = index
        self.drawings.blockSignals(False)
        if recursive and len(entries) >= limit:
            # 撞上限就要说出来（项目根这种目录里图纸上千张，不能假装只有这些）
            self.window.statusBar().showMessage(
                f"图纸太多，只列了前 {limit} 张（`list_drawings(limit=)` 可调）")
        if selected >= 0:
            self.drawings.setCurrentRow(selected)
            self.drawings.scrollToItem(self.drawings.item(selected))
        return len(entries)

    def _on_drawing_clicked(self, item):
        from PySide6.QtCore import Qt
        self.open_path(item.data(Qt.UserRole))

    def open_any(self, path):
        """打开一个路径：目录就列出来并打开第一张，文件就直接看（拖拽/命令行都走它）。"""
        if os.path.isdir(path):
            return self.open_directory(path)
        return self.open_path(path)

    def open_directory(self, directory, recursive=True):
        """打开目录：列出里面的图纸（默认连子目录），并看第一张。"""
        entries = list_drawings(directory, recursive=recursive)
        if not entries:
            self.window.statusBar().showMessage(f"这个目录里没有 DXF/DWG：{directory}")
            if self.warn_on_error:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self.window, "没有图纸", f"{directory}\n里没有 DXF/DWG")
            return False
        current = os.path.abspath(self.cad.path) if self.cad.path else ""
        if current in {os.path.abspath(p) for p in entries}:
            target = current
        else:
            target = self._first_drawable(entries)
        if not self.open_path(target):
            return False
        self.set_directory(directory, recursive=recursive)
        return True

    def _first_drawable(self, entries, probe=5):
        """挑一张画得出来的（见模块级 :func:`first_drawable`）。"""
        return first_drawable(entries, probe)

    def open_path(self, path):
        """打开另一张图；失败只在状态栏（和弹窗）里说，不动当前视图。"""
        try:
            self._build(load(path))
        except moz_cadio.CadIoError as exc:
            self.window.statusBar().showMessage(f"打不开 {path}：{exc}")
            self.set_report(failure_text(path, exc))
            if self.warn_on_error:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.window, "打不开", str(exc))
            return False
        target_dir = os.path.dirname(os.path.abspath(path))
        root = os.path.abspath(self.directory) if self.directory else ""
        inside = bool(root) and (target_dir == root or
                                 (self.recursive and _is_within(target_dir, root)))
        if inside:
            self._select_current()                  # 还在选中的目录里：列表**保持不动**，只改选中项
        else:
            self.set_directory(target_dir)          # 换目录了：列表面板跟着换（只列同级）
        return True

    def _select_current(self):
        from PySide6.QtCore import Qt
        current = os.path.abspath(self.cad.path) if self.cad.path else ""
        for index in range(self.drawings.count()):
            if os.path.abspath(self.drawings.item(index).data(Qt.UserRole)) == current:
                self.drawings.blockSignals(True)
                self.drawings.setCurrentRow(index)
                self.drawings.blockSignals(False)
                self.drawings.scrollToItem(self.drawings.item(index))
                return

    def open_dialog(self):
        """标准的"打开图纸"对话框（起始目录就是当前文件所在目录）。"""
        from PySide6.QtWidgets import QFileDialog
        start = os.path.dirname(os.path.abspath(self.cad.path)) if self.cad.path else os.getcwd()
        path, _selected = QFileDialog.getOpenFileName(
            self.window, "打开图纸", start, "图纸 (*.dxf *.DXF *.dwg *.DWG);;所有文件 (*)")
        if path:
            self.open_path(path)

    def open_directory_dialog(self):
        """"打开目录"对话框：选完就列出里面的图纸（含子目录）。"""
        from PySide6.QtWidgets import QFileDialog
        start = self.directory or os.getcwd()
        directory = QFileDialog.getExistingDirectory(self.window, "打开图纸目录", start)
        if directory:
            self.open_directory(directory)

    def set_report(self, text):
        """把"问题"全文放进下方面板（不截断；状态栏只留一行摘要）。"""
        self.report.setPlainText(text)

    def copy_report(self):
        """一键复制这些问题（好贴给别人/贴到 issue 里）。"""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.report.toPlainText())
        self.window.statusBar().showMessage("已复制问题清单到剪贴板")

    def fit(self):
        from PySide6.QtCore import Qt
        rect = self.scene.itemsBoundingRect()
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            self.view.fitInView(rect, Qt.KeepAspectRatio)

    def _on_layer_toggled(self, item):
        from PySide6.QtCore import Qt
        name = item.data(Qt.UserRole)
        visible = item.checkState() == Qt.Checked
        for graphics_item in self.per_layer.get(name, []):
            graphics_item.setVisible(visible)

    def show(self):
        self.window.show()


def _dock(window, title, widget, width=None):  # pragma: no cover - 需要 Qt
    from PySide6.QtWidgets import QDockWidget
    dock = QDockWidget(title, window)
    dock.setWidget(widget)
    if width:
        dock.setMinimumWidth(width)
    return dock


def export(cad, path, *, width=1600, height=1200, dark=True):
    """把图纸导出成 PNG 或 SVG（按扩展名）。不需要显示器（offscreen 平台即可）。"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgGenerator

    scene, _per_layer, counts, missing, _notes = build_scene(cad, dark=dark)
    rect = scene.itemsBoundingRect()
    if rect.isValid():
        rect = rect.adjusted(-rect.width() * 0.02 - 1, -rect.height() * 0.02 - 1,
                             rect.width() * 0.02 + 1, rect.height() * 0.02 + 1)
    extension = os.path.splitext(path)[1].lower()
    if extension == ".svg":
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(_size(width, height))
        generator.setViewBox(QRectF(0, 0, width, height))
        generator.setTitle(os.path.basename(cad.path))
        painter = QPainter(generator)
    else:
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(30, 30, 30) if dark else QColor(255, 255, 255))
        painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(0, height)              # DXF 的 Y 向上：整幅翻过来才是正的
    painter.scale(1, -1)
    try:
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            scene.render(painter, QRectF(0, 0, width, height), rect)
        else:
            scene.render(painter)
    finally:
        painter.end()
    if extension != ".svg":
        if not image.save(path):
            raise moz_cadio.CadIoError(f"写不出图片：{path}")
    return counts, missing


def _size(width, height):  # pragma: no cover - 需要 Qt
    from PySide6.QtCore import QSize
    return QSize(width, height)


def _layer_table(cad):
    grouped = cad.by_layer()
    lines = [f"{'图层':24s} {'图元':>6s}  {'颜色':>5s}  线型         状态"]
    for layer in sorted(cad.layers, key=lambda item: item.name):
        flags = []
        if layer.off:
            flags.append("关闭")
        if layer.frozen:
            flags.append("冻结")
        if layer.locked:
            flags.append("锁定")
        lines.append(f"{layer.name:24s} {len(grouped.get(layer.name, [])):6d}  "
                     f"{layer.aci:5d}  {str(layer.linetype or ''):12s} {'/'.join(flags)}")
    for name, entities in sorted(grouped.items()):
        if name not in {layer.name for layer in cad.layers}:
            lines.append(f"{name:24s} {len(entities):6d}  （图层表里没有它）")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="moz-cadview", description="直接画 DXF/DWG（不走几何内核）；也可以给一个目录")
    parser.add_argument("path", help="要看的 DXF/DWG，或一个装着图纸的目录")
    parser.add_argument("--report", action="store_true",
                        help="只打印解析报告，不开窗口（给目录就逐个打印）")
    parser.add_argument("--layers", action="store_true", help="只列出图层与每层图元数")
    parser.add_argument("--stats", action="store_true",
                        help="打印画了多少 item（无窗口，CI 用）")
    parser.add_argument("--scan", action="store_true",
                        help="逐张体检：读得通 / 画不出东西 / 打不开，并列出原因（无窗口，排查用）")
    parser.add_argument("--export-png", metavar="PATH", help="导出 PNG（无窗口）")
    parser.add_argument("--export-svg", metavar="PATH", help="导出 SVG（无窗口）")
    parser.add_argument("--width", type=int, default=1600, help="导出宽度（默认 1600）")
    parser.add_argument("--height", type=int, default=1200, help="导出高度（默认 1200）")
    parser.add_argument("--light", action="store_true", help="浅色背景")
    args = parser.parse_args(argv)

    directory = args.path if os.path.isdir(args.path) else None
    if directory:
        entries = list_drawings(directory, recursive=True)
        if not entries:
            print(f"这个目录里没有 DXF/DWG：{directory}", file=sys.stderr)
            return 2
        if args.scan:
            return scan(targets=entries)
        if args.report:                      # 目录 + --report：逐个打印（上限 200 张）
            for path in entries[:200]:
                try:
                    print(moz_cadio.read(path).report())
                except moz_cadio.CadIoError as exc:
                    print(f"—— {path}\n   读不了：{exc}")
                print()
            if len(entries) > 200:
                print(f"（还有 {len(entries) - 200} 张没打印）")
            return 0
        args.path = first_drawable(entries)
        print(f"目录里有 {len(entries)} 张图纸，先看：{os.path.basename(args.path)}")

    if args.scan:
        return scan([args.path])

    try:
        cad = load(args.path)
    except moz_cadio.CadIoError as exc:
        print(f"读不了这张图：{exc}", file=sys.stderr)
        return 2

    if args.report:
        print(cad.report())
        return 0
    if args.layers:
        print(_layer_table(cad))
        return 0

    if args.export_png or args.export_svg or args.stats:
        if not os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "offscreen"      # 无显示器也能导出/统计
        from PySide6.QtWidgets import QApplication
        application = QApplication.instance() or QApplication([sys.argv[0]])
        if args.export_png:
            counts, missing = export(cad, args.export_png, width=args.width,
                                     height=args.height, dark=not args.light)
            print(f"已导出 {args.export_png}（{describe(counts)}）{_missing_note(missing)}")
        if args.export_svg:
            counts, missing = export(cad, args.export_svg, width=args.width,
                                     height=args.height, dark=not args.light)
            print(f"已导出 {args.export_svg}（{describe(counts)}）{_missing_note(missing)}")
        if args.stats:
            scene, per_layer, counts, missing, notes = build_scene(cad, dark=not args.light)
            print(f"图层 {len(per_layer)} 个，item {describe(counts)}"
                  + (f"；缺块定义 {len(missing)} 个：{missing[:5]}" if missing else "")
                  + (f"；{notes[0]}" if notes else ""))
        del application
        return 0

    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([sys.argv[0]])
    view = CadView(cad, dark=not args.light, directory=directory, recursive=bool(directory))
    view.show()
    if directory:
        print(f"右侧「图纸」面板里可以点着切换（共 {view.drawings.count()} 张）。")
    else:
        print(f"{cad.report()}\n\n画到场景里的 item：{describe(view.counts)}")
    return application.exec()


def drawable_count(cad, missing=None, notes=None):
    """"画得出来"的图元数——判据与 :func:`build_scene` 一致（画不出东西的实体不算）。"""
    total = 0
    for entity, _matrix in moz_cadio.iter_draw(cad, missing=missing, notes=notes):
        if entity.kind in ("TEXT", "MTEXT"):
            total += 1 if (entity.text or "").strip() else 0
        elif entity.kind == "POINT":
            total += 1 if entity.p1 else 0
        elif any(len(chain) >= 2 for chain in moz_cadio.entity_polylines(entity)):
            total += 1
    return total


def scan(targets, limit=DRAWING_LIMIT):
    """逐张体检：画得出来 / 画不出东西 / 打不开，并列出原因。**不需要 Qt**，适合排查。"""
    readable, blank, broken = [], [], []
    for path in targets[:limit]:
        try:
            cad = load(path)
        except moz_cadio.CadIoError as exc:
            broken.append((path, str(exc)))
            print(f"[打不开] {path}\n         {str(exc)[:120]}")
            continue
        missing, notes = [], []
        items = drawable_count(cad, missing=missing, notes=notes)
        if items:
            readable.append((path, items))
            extra = f"｜缺块定义 {missing[:2]}" if missing else ""
            extra += f"｜{notes[0][:30]}" if notes else ""
            print(f"[画得出] {path}  {items} 个图元{extra}")
        else:
            blank.append((path, missing, cad.warnings))
            print(f"[画不出] {path}  原因：{missing[:2] or cad.warnings[:1] or '模型空间里就没有图元'}")
    print()
    print(f"汇总: 共 {len(targets[:limit])} 张 —— 画得出 {len(readable)}、"
          f"画不出东西 {len(blank)}、打不开 {len(broken)}")
    if len(targets) > limit:
        print(f"（只查了前 {limit} 张）")
    for path, error in broken:
        print(f"  打不开：{path}\n          {error}")
    for path, missing, warnings in blank:
        print(f"  画不出：{path}\n          原因：{missing[:3] or warnings[:1]}")
    return 0


def _missing_note(missing):
    if not missing:
        return ""
    return f"；有 {len(missing)} 个块参照找不到块定义：{missing[:5]}"


def describe(counts):
    return "、".join(f"{kind} {count}" for kind, count in
                     sorted(counts.items(), key=lambda item: -item[1])) or "（空）"


if __name__ == "__main__":
    sys.exit(main())
