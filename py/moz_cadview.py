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


def build_scene(cad, *, chord_tolerance=0.05, aci_table=None, dark=True):
    """把模型画成 ``QGraphicsScene``（返回 scene、每层 item、各类型计数、缺定义的块名）。

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
    missing = []
    for entity, matrix in moz_cadio.iter_draw(cad, missing=missing):
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
    return scene, per_layer, counts, missing


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


class CadView:  # pragma: no cover - 需要显示器/offscreen 平台
    """看图窗口：QGraphicsView + 图层开关。"""

    def __init__(self, cad, dark=True, title=None):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction, QPainter
        from PySide6.QtWidgets import QGraphicsView, QListWidget, QListWidgetItem, QMainWindow

        self.cad = cad
        scene, per_layer, counts, missing = build_scene(cad, dark=dark)
        self.scene = scene
        self.per_layer = per_layer
        self.counts = counts

        window = QMainWindow()
        window.setWindowTitle(title or f"moz-cadview — {os.path.basename(cad.path)}")
        window.resize(1100, 800)
        view = QGraphicsView(scene)
        view.setRenderHint(QPainter.Antialiasing, False)
        view.scale(1.0, -1.0)                       # DXF 的 Y 向上，Qt 的 Y 向下
        view.setDragMode(QGraphicsView.ScrollHandDrag)
        view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        window.setCentralWidget(view)

        panel = QListWidget()
        for name in sorted(per_layer):
            item = QListWidgetItem(f"{name}（{len(per_layer[name])}）")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, name)
            panel.addItem(item)
        panel.itemChanged.connect(self._on_layer_toggled)
        window.addDockWidget(Qt.RightDockWidgetArea, _dock(window, "图层", panel))

        reset = QAction("重置视角", window)
        reset.triggered.connect(self.fit)
        window.menuBar().addMenu("视图").addAction(reset)

        self.window = window
        self.view = view
        self.fit()

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


def _dock(window, title, widget):  # pragma: no cover - 需要 Qt
    from PySide6.QtWidgets import QDockWidget
    dock = QDockWidget(title, window)
    dock.setWidget(widget)
    return dock


def export(cad, path, *, width=1600, height=1200, dark=True):
    """把图纸导出成 PNG 或 SVG（按扩展名）。不需要显示器（offscreen 平台即可）。"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgGenerator

    scene, _per_layer, counts, missing = build_scene(cad, dark=dark)
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
        prog="moz-cadview", description="直接画 DXF/DWG（不走几何内核）")
    parser.add_argument("path", help="要看的 DXF/DWG")
    parser.add_argument("--report", action="store_true", help="只打印解析报告，不开窗口")
    parser.add_argument("--layers", action="store_true", help="只列出图层与每层图元数")
    parser.add_argument("--stats", action="store_true",
                        help="打印画了多少 item（无窗口，CI 用）")
    parser.add_argument("--export-png", metavar="PATH", help="导出 PNG（无窗口）")
    parser.add_argument("--export-svg", metavar="PATH", help="导出 SVG（无窗口）")
    parser.add_argument("--width", type=int, default=1600, help="导出宽度（默认 1600）")
    parser.add_argument("--height", type=int, default=1200, help="导出高度（默认 1200）")
    parser.add_argument("--light", action="store_true", help="浅色背景")
    args = parser.parse_args(argv)

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
            scene, per_layer, counts, missing = build_scene(cad, dark=not args.light)
            print(f"图层 {len(per_layer)} 个，item {describe(counts)}"
                  + (f"；缺块定义 {len(missing)} 个：{missing[:5]}" if missing else ""))
        del application
        return 0

    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([sys.argv[0]])
    view = CadView(cad, dark=not args.light)
    view.show()
    print(f"{cad.report()}\n\n画到场景里的 item：{describe(view.counts)}")
    return application.exec()


def _missing_note(missing):
    if not missing:
        return ""
    return f"；有 {len(missing)} 个块参照找不到块定义：{missing[:5]}"


def describe(counts):
    return "、".join(f"{kind} {count}" for kind, count in
                     sorted(counts.items(), key=lambda item: -item[1])) or "（空）"


if __name__ == "__main__":
    sys.exit(main())
