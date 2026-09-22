"""moz_drawing —— 2D 工程图：把截面/轮廓投影排成一张图并加标注。

这一层是**纯 Python 组合 SCAD 的 2D 几何**，不碰 C++：

* 视图来自 ``moz.section()``（剖视）或 ``moz.outline()``（视图轮廓），本身就是 2D 形状，
  直接 ``translate`` 到图面上的位置即可；
* 标注（尺寸线、箭头、引线、剖面线、中心线、图框、标题栏）都是 2D 图形的组合；
* 整张图是一块 2D 几何，所以能直接导出 **SVG / DXF / PDF**，也能用预览器的 2D 视图看。

坐标约定：图面坐标就是 SCAD 的 XY 平面，单位 mm，+Y 向上（导出 SVG 时 y 轴翻转由引擎处理）。
线宽用极扁的矩形近似（2D 几何只有填充多边形，没有描边概念），默认 0.25 mm ≈ ISO 细线。

文字默认用随包分发的 ``Moz Sans SC``（``TEXT_FONT``，见 docs/drawing.md）：引擎自带的
默认字体只有拉丁字形，中文会静默变成空心方框；换字体传 ``font="<fontconfig 家族名>"``，
``font=""`` 退回引擎默认字体。

用法见 ``py/drawing_demo.py`` 与 docs/drawing.md。
"""

import math
from dataclasses import dataclass, field

import moz_openscad as moz

# ISO A 系列图纸尺寸（mm，竖放）
PAGE_SIZES = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}

LINE_WIDTH = 0.25          # 细实线
THICK_WIDTH = 0.5          # 粗实线（视图轮廓周围一般用粗线，这里留作参数）
TEXT_SIZE = 3.5            # 正文文字（ISO 3.5 mm）
DIM_TEXT_SIZE = 3.0        # 尺寸文字
HATCH_SPACING = 3.0        # 剖面线间距
HATCH_ANGLE = 45.0         # 剖面线角度

# 文字用的字体（fontconfig 家族名）。默认用随包分发的 Moz Sans SC：引擎自带的默认字体
# 只有拉丁字形，中文会**静默**变成空心方框，而系统有没有中文字体不可控。想换成系统里
# 覆盖更全的字体，传 font="Noto Sans CJK SC" 之类即可；传 font="" 退回引擎默认字体。
TEXT_FONT = "Moz Sans SC"


# --- 基础图元 ---


def line(p1, p2, width=LINE_WIDTH):
    """两点之间的线段（用扁矩形近似）。"""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("line() 的两个端点不能重合")
    angle = math.degrees(math.atan2(dy, dx))
    return moz.rotate([0, 0, angle], moz.translate([length / 2, 0],
                      moz.square([length, width], center=True))).translate(p1)


def polyline(points, width=LINE_WIDTH):
    """折线。"""
    return moz.union(*[line(points[i], points[i + 1], width) for i in range(len(points) - 1)])


def arrow(tip, direction, length=3.0, width=1.0):
    """箭头：尖端在 tip，指向 direction（单位为向量的方向，箭头在 tip 一侧向回展开）。"""
    length_of_direction = math.hypot(*direction)
    ux, uy = direction[0] / length_of_direction, direction[1] / length_of_direction
    px, py = -uy, ux           # 垂直方向
    base = (tip[0] - ux * length, tip[1] - uy * length)
    shape = moz.polygon([
        [tip[0], tip[1]],
        [base[0] + px * width / 2, base[1] + py * width / 2],
        [base[0] - px * width / 2, base[1] - py * width / 2],
    ])
    return shape


def text_at(anchor, content, size=TEXT_SIZE, halign="left", valign="bottom", rotation=0.0, font=None):
    """在指定锚点放一段文字（默认左下角对齐）。

    ``font`` 是 fontconfig 的家族名：默认 ``None`` = 用模块常量 ``TEXT_FONT``（自带中文
    字库），``""`` = 退回引擎默认字体（只有拉丁字形，中文会变成空心方框）。
    """
    if font is None:
        font = TEXT_FONT
    shape = moz.text(content, size=size, halign=halign, valign=valign, font=font or None)
    if rotation:
        shape = moz.rotate([0, 0, rotation], shape)
    return shape.translate(anchor)


def centerline(p1, p2, extension=2.0, dash=4.0, gap=1.5, width=LINE_WIDTH):
    """中心线：长划-短划交替（点划线），两端各伸出 extension。"""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("centerline() 的两个端点不能重合")
    ux, uy = dx / length, dy / length
    start = (p1[0] - ux * extension, p1[1] - uy * extension)
    total = length + 2 * extension
    pieces, position = [], 0.0
    long_dash = True
    while position < total:
        segment = dash if long_dash else gap
        segment = min(segment, total - position)
        # 只画长划，不画间隙——否则相邻片首尾相接，union 会合并成一条实线
        if long_dash and segment > 0.05:
            a = (start[0] + ux * position, start[1] + uy * position)
            b = (start[0] + ux * (position + segment), start[1] + uy * (position + segment))
            pieces.append(line(a, b, width))
        position += segment
        long_dash = not long_dash
    # 制图习惯：中心线两端以长划收尾，别让最后一段落在间隙上
    if pieces:
        tail = (start[0] + ux * (total - dash), start[1] + uy * (total - dash))
        pieces.append(line(tail, (start[0] + ux * total, start[1] + uy * total), width))
    return moz.union(*pieces)


def hatch(shape, spacing=HATCH_SPACING, angle=HATCH_ANGLE, width=LINE_WIDTH):
    """剖面线：一组平行细线与被剖实体求交，只保留实体内部的部分。

    需要先知道形状的包围盒，所以这里会真正求值一次（``shape.measure``）。
    空形状（例如平面没切到实体的截面）直接原样返回。
    """
    if shape.is_empty:
        return shape
    bbox_min, bbox_max = shape.measure.bbox
    span = math.hypot(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1])
    reach = span / 2 + spacing
    offsets = []
    step = 0
    while step * spacing <= reach:
        offsets.append(step * spacing)
        if step:
            offsets.append(-step * spacing)
        step += 1
    lines = moz.union(*[
        moz.rotate([0, 0, angle], moz.translate([0, offset],
                   moz.square([2 * span + 2 * spacing, width], center=True)))
        for offset in offsets
    ])
    return moz.intersection(shape, lines)


# --- 尺寸标注 ---


def _format_value(value):
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


@dataclass
class View:
    """图面上的一个视图：2D 形状 + 位置 + 比例（供标注换算用）。"""

    name: str
    shape: object
    at: tuple = (0.0, 0.0)
    scale: float = 1.0
    label: str | None = None
    hatched: bool = False
    _placed: object = field(default=None, repr=False)

    def placed(self):
        """把视图摆到图面上（含比例）。"""
        if self._placed is None:
            shape = self.shape
            if self.scale != 1.0:
                shape = moz.scale([self.scale, self.scale], shape)
            self._placed = shape.translate(self.at)
        return self._placed

    def to_sheet(self, point):
        """视图（模型/视图）坐标 → 图面坐标。"""
        return (self.at[0] + point[0] * self.scale, self.at[1] + point[1] * self.scale)


def dim_linear(p1, p2, offset=10.0, *, text=None, size=DIM_TEXT_SIZE, extension=2.0,
               gap=1.0, arrow_size=3.0, width=LINE_WIDTH, font=None):
    """线性尺寸：p1→p2 是量取的两个点（图面坐标），offset 是尺寸线到它们的垂直距离。

    offset 为正时尺寸线落在 p1→p2 方向的**左侧**（即逆时针 90° 一侧）。
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("dim_linear() 的两个量取点不能重合")
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux                      # 左法向
    a = (p1[0] + nx * offset, p1[1] + ny * offset)
    b = (p2[0] + nx * offset, p2[1] + ny * offset)

    pieces = [
        # 尺寸界线：从量取点留 gap 后画到超出尺寸线 extension
        line((p1[0] + nx * gap, p1[1] + ny * gap),
             (p1[0] + nx * (offset + extension), p1[1] + ny * (offset + extension)), width),
        line((p2[0] + nx * gap, p2[1] + ny * gap),
             (p2[0] + nx * (offset + extension), p2[1] + ny * (offset + extension)), width),
        # 尺寸线
        line(a, b, width),
        # 箭头：尖端落在尺寸界线上，箭身朝尺寸线内侧展开
        arrow(a, (-ux, -uy), arrow_size, arrow_size / 3),
        arrow(b, (ux, uy), arrow_size, arrow_size / 3),
    ]
    label = text if text is not None else _format_value(length)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    # 文字平行于尺寸线（制图惯例），并保证不会倒过来读
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    if angle > 90:
        angle -= 180
    elif angle <= -90:
        angle += 180
    anchor = (mid[0] + nx * (1.0 + size / 2), mid[1] + ny * (1.0 + size / 2))
    pieces.append(text_at(anchor, label, size=size, halign="center", valign="center", rotation=angle, font=font))
    return moz.union(*pieces)


def dim_diameter(center, radius, angle=45.0, *, text=None, size=DIM_TEXT_SIZE,
                 leader=6.0, arrow_size=3.0, width=LINE_WIDTH, font=None):
    """直径标注：从圆外引一条引线到圆周，文字形如 ⌀20。"""
    radians = math.radians(angle)
    ux, uy = math.cos(radians), math.sin(radians)
    edge = (center[0] + ux * radius, center[1] + uy * radius)
    outer = (center[0] + ux * (radius + leader), center[1] + uy * (radius + leader))
    label = text if text is not None else f"⌀{_format_value(radius * 2)}"
    return moz.union(
        line(outer, edge, width),
        arrow(edge, (ux, uy), arrow_size, arrow_size / 3),
        text_at((outer[0] + ux * 1.0, outer[1] + uy * 1.0), label, size=size, halign="left", font=font),
    )


def dim_radius(center, radius, angle=45.0, *, text=None, size=DIM_TEXT_SIZE,
               leader=6.0, arrow_size=3.0, width=LINE_WIDTH, font=None):
    """半径标注：文字形如 R5。箭头尖端落在圆弧上，箭身朝圆心一侧。"""
    radians = math.radians(angle)
    ux, uy = math.cos(radians), math.sin(radians)
    edge = (center[0] + ux * radius, center[1] + uy * radius)
    outer = (center[0] + ux * (radius + leader), center[1] + uy * (radius + leader))
    label = text if text is not None else f"R{_format_value(radius)}"
    return moz.union(
        line(center, outer, width),
        arrow(edge, (ux, uy), arrow_size, arrow_size / 3),
        text_at((outer[0] + ux * 1.0, outer[1] + uy * 1.0), label, size=size, halign="left", font=font),
    )


# --- 图面 ---


class Drawing:
    """一张图：图纸、图框、标题栏、若干视图与标注。"""

    def __init__(self, size="A4", landscape=False, margin=10.0, title="", number="",
                 author="", date="", material="", scale_note="", border_width=THICK_WIDTH, font=None):
        if isinstance(size, str):
            width, height = PAGE_SIZES[size]
        else:
            width, height = size
        self.page = (width, height) if not landscape else (height, width)
        self.margin = margin
        self.border_width = border_width
        # 整张图的文字字体：图名/图号等栏位名是中文，所以默认就用自带中文字库
        self.font = TEXT_FONT if font is None else font
        self.fields = {
            "图名": title, "图号": number, "材料": material,
            "设计": author, "日期": date, "比例": scale_note,
        }
        self.views = []
        self.annotations = []

    # 图面范围
    @property
    def inner(self):
        """图框内区域 (x0, y0, x1, y1)。"""
        return (self.margin, self.margin, self.page[0] - self.margin, self.page[1] - self.margin)

    def add_view(self, name, shape, at=(0.0, 0.0), *, scale=1.0, label=None,
                 hatched=False, label_at=None):
        """加一个视图：shape 一般是 moz.section() / moz.outline() 的结果。

        hatched=True 时给视图加剖面线（只对剖视有意义）。
        """
        view = View(name=name, shape=shape, at=at, scale=scale, label=label, hatched=hatched)
        self.views.append(view)
        if label:
            anchor = label_at if label_at is not None else (at[0], at[1] - 4.0)
            self.annotations.append(text_at(anchor, label, size=TEXT_SIZE, halign="left", font=self.font))
        return view

    def add(self, *shapes):
        """直接往图面上加几何（自定义标注、说明文字等）。"""
        self.annotations.extend(shapes)
        return self

    def add_note(self, position, content, size=TEXT_SIZE, font=None):
        """加一条说明文字（字体默认跟随图面 ``self.font``）。"""
        self.annotations.append(
            text_at(position, content, size=size, halign="left", font=self.font if font is None else font)
        )
        return self

    def dim(self, view, kind, *args, **kwargs):
        """在视图上标注：坐标用**视图坐标**给，内部换算到图面坐标。

        kind 取 "linear" / "diameter" / "radius"；文字字体默认跟随图面 ``self.font``。
        """
        kwargs.setdefault("font", self.font)
        if kind == "linear":
            p1, p2 = args[0], args[1]
            shape = dim_linear(view.to_sheet(p1), view.to_sheet(p2), **kwargs)
        elif kind in ("diameter", "radius"):
            center, radius = args[0], args[1]
            handler = dim_diameter if kind == "diameter" else dim_radius
            shape = handler(view.to_sheet(center), radius * view.scale, **kwargs)
        else:
            raise ValueError(f"未知的标注类型 {kind!r}（linear/diameter/radius）")
        self.annotations.append(shape)
        return self

    def add_centerline(self, p1, p2, **kwargs):
        self.annotations.append(centerline(p1, p2, **kwargs))
        return self

    # 组装
    def border(self):
        """图框：内外两条矩形线。"""
        x0, y0, x1, y1 = self.inner
        inner_box = moz.translate([x0, y0], moz.square([x1 - x0, y1 - y0], center=False))
        return moz.difference(inner_box, moz.offset(inner_box, r=-self.border_width))

    def title_block(self, width=110.0, height=32.0):
        """标题栏：放在图框右下角，含分隔线与字段文字。"""
        x0, y0, x1, _ = self.inner
        block_x, block_y = x1 - width, y0
        outline = moz.translate([block_x, block_y], moz.square([width, height], center=False))
        rows = [(key, value) for key, value in self.fields.items() if value]
        row_height = height / max(len(rows), 1)

        pieces = [outline]
        labels = []
        for index, (key, value) in enumerate(rows):
            y = block_y + row_height * (len(rows) - index - 1)
            if index:
                pieces.append(line((block_x, y), (block_x + width, y)))       # 行分隔线
            labels.append(text_at((block_x + 2, y + 1.5), f"{key}：{value}", size=TEXT_SIZE, font=self.font))
        # 左侧竖线把字段名与内容分开
        pieces.append(line((block_x + 18, block_y), (block_x + 18, block_y + height)))
        return moz.union(*pieces, *labels)

    def build(self):
        """组装整张图（2D Shape）。"""
        pieces = [self.border(), self.title_block()]
        for view in self.views:
            placed = view.placed()
            pieces.append(placed)
            if view.hatched:
                pieces.append(hatch(placed))
        pieces.extend(self.annotations)
        return moz.union(*pieces)

    def content_bbox(self):
        """图面内容的包围盒 (x0, y0, x1, y1)（含标注，需要求值一次）。"""
        low, high = self.build().measure.bbox
        return (low[0], low[1], high[0], high[1])

    def fits(self, tolerance=0.0):
        """内容是否都在图框内（版式自查：视图/标注出框时返回 False）。"""
        x0, y0, x1, y1 = self.inner
        cx0, cy0, cx1, cy1 = self.content_bbox()
        return (cx0 >= x0 - tolerance and cy0 >= y0 - tolerance
                and cx1 <= x1 + tolerance and cy1 <= y1 + tolerance)

    def export(self, fmt, path):
        return self.build().export(fmt, path)

    def export_bytes(self, fmt):
        return self.build().export_bytes(fmt)

    def show(self, title=None, width=1100, height=800):
        self.build().show(title=title or "moz drawing", width=width, height=height)
