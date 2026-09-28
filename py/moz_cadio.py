"""moz_cadio —— 用 LibreCAD 的解析核心（libdxfrw）把 DXF/DWG 读成"规范化 2D 实体模型"。

分工（见 docs/librecad-integration.md）：

- ``py/moz_dxf.py``（ezdxf，MIT）是 **DXF 的建模主路径**：轮廓修复、成环、参数提取、成型；
- 本模块是 **DXF/DWG 的读出路径**：拿到全部图元 + 图层/线型/颜色语义，供渲染器查阅，
  也是将来 DWG 进"图纸 → 模型"的入口。DWG 只有这条路（ezdxf 读不了 DWG），
  覆盖面 **R1.40–2018+**（上游 libdxfrw 2.0.0，见 docs/third-party.md）。

C ABI 见 ``3rd/libdxfrw/moz/moz_cadio.h``，``.so`` 由 ``scripts/build_moz_cadio.sh`` 构建，
随平台 wheel 分发在 ``moz_data/lib/``（搜索顺序：``MOZ_CADIO_LIB`` 环境变量 → 模块同目录 →
``../build/lib/`` → ``moz_data/lib/``）。**不需要** ezdxf、也不需要几何内核。

```python
import moz_cadio

cad = moz_cadio.read("板框.dwg")
print(cad.format, cad.version, len(cad.entities))   # 'dwg' 'AC1027' 1234
for layer in cad.layers:
    print(layer.name, layer.aci, "off" if layer.off else "")
print(cad.report())
```

约定：坐标已按 ``read(iface, true)`` 处理过（带 extrusion 的实体换算到平面，与 LibreCAD 一致）；
**角度一律是弧度**；``aci`` 用 DXF 约定（0 = BYBLOCK，256 = BYLAYER）。
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field

__all__ = [
    "CadIoError",
    "Block",
    "CadFile",
    "Entity",
    "Layer",
    "KIND_NAMES",
    "FLAG_CLOSED",
    "FLAG_REVERSED",
    "FLAG_SOLID",
    "FLAG_RATIONAL",
    "FLAG_PERIODIC",
    "FLAG_MESH",
    "FLAG_HAS_TEXT",
    "FLAG_TITLE",
    "lib_path",
    "read",
    "report",
]

# --- 与 moz_cadio.h 的 enum 对齐 ---
KIND_NAMES = {
    0: "UNKNOWN",
    1: "POINT",
    2: "LINE",
    3: "RAY",
    4: "XLINE",
    5: "CIRCLE",
    6: "ARC",
    7: "ELLIPSE",
    8: "LWPOLYLINE",
    9: "POLYLINE",
    10: "SPLINE",
    11: "INSERT",
    12: "TEXT",
    13: "MTEXT",
    14: "DIMENSION",
    15: "HATCH",
    16: "SOLID",
    17: "TRACE",
    18: "3DFACE",
    19: "LEADER",
    20: "IMAGE",
    21: "VIEWPORT",
}

FLAG_CLOSED = 1 << 0
FLAG_REVERSED = 1 << 1
FLAG_SOLID = 1 << 2
FLAG_RATIONAL = 1 << 3
FLAG_PERIODIC = 1 << 4
FLAG_MESH = 1 << 5
FLAG_HAS_TEXT = 1 << 6
FLAG_TITLE = 1 << 7

BYLAYER = 256
BYBLOCK = 0
NO_COLOR = -1

# 标注子类（dimtype & 7），与 DXF group 70 一致
DIM_KINDS = {
    0: "linear",
    1: "aligned",
    2: "angular",
    3: "diameter",
    4: "radius",
    5: "angular3p",
    6: "ordinate",
}

# $INSUNITS（DRW_Header::Units 原值）→ 名称
INSUNITS = {
    0: "unitless",
    1: "inch",
    2: "foot",
    3: "mile",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinch",
    9: "mil",
    10: "yard",
    11: "angstrom",
    12: "nanometer",
    13: "micron",
    14: "decimeter",
    15: "decameter",
    16: "hectometer",
    17: "gigameter",
}

# 线宽（DXF group 370 原值）
LINEWEIGHT_SPECIAL = {-3: "bydefault", -2: "byblock", -1: "bylayer"}


class CadIoError(RuntimeError):
    """读不了这张图（文件不存在、结构坏了、DWG 版本不支持…），消息里带原因。"""


# --- C ABI（字段顺序必须与 moz_cadio.h 完全一致） ---


class _CEntity(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_int),
        ("aci", ctypes.c_int),
        ("color24", ctypes.c_int),
        ("space", ctypes.c_int),
        ("visible", ctypes.c_int),
        ("flags", ctypes.c_uint),
        ("dimtype", ctypes.c_int),
        ("colcount", ctypes.c_int),
        ("rowcount", ctypes.c_int),
        ("align_h", ctypes.c_int),
        ("align_v", ctypes.c_int),
        ("layer", ctypes.c_char_p),
        ("linetype", ctypes.c_char_p),
        ("name", ctypes.c_char_p),
        ("text", ctypes.c_char_p),
        ("owner", ctypes.c_char_p),
        ("ltscale", ctypes.c_double),
        ("radius", ctypes.c_double),
        ("start_angle", ctypes.c_double),
        ("end_angle", ctypes.c_double),
        ("ratio", ctypes.c_double),
        ("elevation", ctypes.c_double),
        ("height", ctypes.c_double),
        ("rotation", ctypes.c_double),
        ("xscale", ctypes.c_double),
        ("yscale", ctypes.c_double),
        ("zscale", ctypes.c_double),
        ("widthscale", ctypes.c_double),
        ("oblique", ctypes.c_double),
        ("degree", ctypes.c_double),
        ("colspace", ctypes.c_double),
        ("rowspace", ctypes.c_double),
        ("p1", ctypes.c_double * 3),
        ("p2", ctypes.c_double * 3),
        ("p3", ctypes.c_double * 3),
        ("points", ctypes.POINTER(ctypes.c_double)),
        ("npoints", ctypes.c_int),
        ("bulges", ctypes.POINTER(ctypes.c_double)),
        ("knots", ctypes.POINTER(ctypes.c_double)),
        ("nknots", ctypes.c_int),
        ("weights", ctypes.POINTER(ctypes.c_double)),
        ("nweights", ctypes.c_int),
        ("loop_offsets", ctypes.POINTER(ctypes.c_int)),
        ("nloops", ctypes.c_int),
    ]


class _CLayer(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("aci", ctypes.c_int),
        ("color24", ctypes.c_int),
        ("linetype", ctypes.c_char_p),
        ("flags", ctypes.c_uint),
        ("lineweight", ctypes.c_int),
    ]


class _CBlock(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("base_point", ctypes.c_double * 3),
        ("first_entity", ctypes.c_int),
        ("entity_count", ctypes.c_int),
    ]


_lib = None


def _candidate_libs():
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.environ.get("MOZ_CADIO_LIB") or "",
        os.path.join(here, "libmozcadio.so"),
        os.path.join(here, os.pardir, "build", "lib", "libmozcadio.so"),
        os.path.join(here, "moz_data", "lib", "libmozcadio.so"),
    ]


def lib_path() -> str:
    """返回实际会加载的 ``libmozcadio.so`` 路径（找不到就抛 CadIoError）。"""
    for candidate in _candidate_libs():
        if candidate and os.path.exists(candidate):
            return os.path.abspath(candidate)
    raise CadIoError(
        "找不到 libmozcadio.so：先跑 bash scripts/build_moz_cadio.sh，"
        "或用 MOZ_CADIO_LIB 指定路径"
    )


def _load():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(lib_path())
        lib.moz_cad_read.restype = ctypes.c_void_p
        lib.moz_cad_read.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)]
        lib.moz_cad_free.argtypes = [ctypes.c_void_p]
        lib.moz_cad_format.restype = ctypes.c_char_p
        lib.moz_cad_format.argtypes = [ctypes.c_void_p]
        lib.moz_cad_version.restype = ctypes.c_char_p
        lib.moz_cad_version.argtypes = [ctypes.c_void_p]
        lib.moz_cad_insunits.restype = ctypes.c_int
        lib.moz_cad_insunits.argtypes = [ctypes.c_void_p]
        lib.moz_cad_extents.restype = ctypes.c_int
        lib.moz_cad_extents.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
                                        ctypes.POINTER(ctypes.c_double)]
        lib.moz_cad_entity_count.restype = ctypes.c_int
        lib.moz_cad_entity_count.argtypes = [ctypes.c_void_p]
        lib.moz_cad_entity_at.restype = ctypes.POINTER(_CEntity)
        lib.moz_cad_entity_at.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.moz_cad_layer_count.restype = ctypes.c_int
        lib.moz_cad_layer_count.argtypes = [ctypes.c_void_p]
        lib.moz_cad_layer_at.restype = ctypes.POINTER(_CLayer)
        lib.moz_cad_layer_at.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.moz_cad_block_count.restype = ctypes.c_int
        lib.moz_cad_block_count.argtypes = [ctypes.c_void_p]
        lib.moz_cad_block_at.restype = ctypes.POINTER(_CBlock)
        lib.moz_cad_block_at.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.moz_cad_warning_count.restype = ctypes.c_int
        lib.moz_cad_warning_count.argtypes = [ctypes.c_void_p]
        lib.moz_cad_warning_at.restype = ctypes.c_char_p
        lib.moz_cad_warning_at.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.moz_str_free.argtypes = [ctypes.c_char_p]
        _lib = lib
    return _lib


def _text(value) -> str | None:
    if not value:
        return None
    return value.decode("utf-8", errors="replace")


def _array(pointer, count: int):
    if not pointer or count <= 0:
        return ()
    return tuple(pointer[i] for i in range(count))


# --- 规范化模型 ---


@dataclass(frozen=True)
class Layer:
    """图层：颜色/线型/开关状态。``lineweight`` 是 DXF group 370 原值。"""

    name: str
    aci: int = 7
    color24: int | None = None
    linetype: str | None = None
    off: bool = False
    frozen: bool = False
    locked: bool = False
    lineweight: int = -3

    @property
    def rgb(self):
        """(r, g, b) 0-255：真彩优先，否则留给调用方按 ACI 表查（这里只给真彩）。"""
        if self.color24 is None or self.color24 < 0:
            return None
        value = self.color24
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)

    @property
    def lineweight_name(self) -> str:
        return LINEWEIGHT_SPECIAL.get(self.lineweight, f"{self.lineweight / 100.0:.2f}mm")


@dataclass(frozen=True)
class Block:
    """块定义；块内实体在 ``CadFile.entities`` 里用 ``owner`` 归组。"""

    name: str
    base_point: tuple
    first_entity: int
    entity_count: int


@dataclass
class Entity:
    """一个图元。字段按 ``kind`` 解释，取值见 docs/librecad-integration.md 的字段表。"""

    kind: str
    layer: str = "0"
    aci: int = BYLAYER
    color24: int | None = None
    linetype: str | None = None
    owner: str = ""
    space: int = 0
    visible: bool = True
    ltscale: float = 1.0
    flags: int = 0
    dimtype: int = 0
    colcount: int = 0
    rowcount: int = 0
    align_h: int = 0
    align_v: int = 0
    name: str | None = None
    text: str | None = None
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    ratio: float = 1.0
    elevation: float = 0.0
    height: float = 0.0
    rotation: float = 0.0
    xscale: float = 1.0
    yscale: float = 1.0
    zscale: float = 1.0
    widthscale: float = 1.0
    oblique: float = 0.0
    degree: float = 0.0
    colspace: float = 0.0
    rowspace: float = 0.0
    p1: tuple | None = None
    p2: tuple | None = None
    p3: tuple | None = None
    points: tuple = ()
    bulges: tuple = ()
    knots: tuple = ()
    weights: tuple = ()
    loop_offsets: tuple = ()

    # --- 便捷属性 ---
    @property
    def closed(self) -> bool:
        return bool(self.flags & FLAG_CLOSED)

    @property
    def reversed(self) -> bool:
        return bool(self.flags & FLAG_REVERSED)

    @property
    def solid(self) -> bool:
        return bool(self.flags & FLAG_SOLID)

    @property
    def is_mesh(self) -> bool:
        return bool(self.flags & FLAG_MESH)

    @property
    def dim_kind(self) -> str | None:
        if self.kind != "DIMENSION":
            return None
        return DIM_KINDS.get(self.dimtype & 7)

    def xy(self, index: int = 0):
        """第 ``index`` 个顶点的 (x, y)（``points`` 里 x,y 交错）。"""
        return (self.points[2 * index], self.points[2 * index + 1])

    def point2d(self, which: str = "p1"):
        value = getattr(self, which)
        if value is None:
            return None
        return (value[0], value[1])

    def loop_points(self):
        """HATCH：各边界环的顶点列表（``points`` 摊平 + ``loop_offsets`` 前缀和）。"""
        loops, start = [], 0
        for stop in self.loop_offsets:
            loops.append([self.xy(i) for i in range(start, stop)])
            start = stop
        return loops


@dataclass
class CadFile:
    """一张读进来的图纸。"""

    path: str
    format: str = "dxf"
    version: str = ""
    insunits: int = 0
    extents: tuple | None = None
    layers: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    # --- 视图 ---
    def by_kind(self, *kinds: str):
        wanted = {k.upper() for k in kinds}
        return [e for e in self.entities if e.kind in wanted]

    def by_layer(self):
        grouped = {}
        for entity in self.entities:
            grouped.setdefault(entity.layer, []).append(entity)
        return grouped

    def counts(self):
        result = {}
        for entity in self.entities:
            result[entity.kind] = result.get(entity.kind, 0) + 1
        return dict(sorted(result.items(), key=lambda kv: -kv[1]))

    def layer_map(self):
        return {layer.name: layer for layer in self.layers}

    @property
    def units_name(self) -> str:
        return INSUNITS.get(self.insunits, f"unknown({self.insunits})")

    def ignored(self):
        """从告警里挑出"忽略 N 个…"这类计数（解析时被跳过的内容）。"""
        return [w for w in self.warnings if w.startswith("忽略 ")]

    def report(self) -> str:
        lines = [
            f"图纸：{os.path.basename(self.path)}",
            f"格式：{self.format} 版本：{self.version} 单位：{self.units_name}",
            f"图元：{len(self.entities)} 个 {self.counts()}",
            f"图层：{len(self.layers)} 个，块：{len(self.blocks)} 个",
        ]
        if self.extents:
            low, high = self.extents
            lines.append(
                f"范围：({low[0]:.3f}, {low[1]:.3f}) – ({high[0]:.3f}, {high[1]:.3f})"
            )
        if self.warnings:
            lines.append("告警：")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


def _convert_entity(raw: _CEntity) -> Entity:
    return Entity(
        kind=KIND_NAMES.get(raw.kind, f"UNKNOWN({raw.kind})"),
        layer=_text(raw.layer) or "0",
        aci=raw.aci,
        color24=None if raw.color24 < 0 else raw.color24,
        linetype=_text(raw.linetype),
        owner=_text(raw.owner) or "",
        space=raw.space,
        visible=bool(raw.visible),
        ltscale=raw.ltscale,
        flags=int(raw.flags),
        dimtype=raw.dimtype,
        colcount=raw.colcount,
        rowcount=raw.rowcount,
        align_h=raw.align_h,
        align_v=raw.align_v,
        name=_text(raw.name),
        text=_text(raw.text),
        radius=raw.radius,
        start_angle=raw.start_angle,
        end_angle=raw.end_angle,
        ratio=raw.ratio,
        elevation=raw.elevation,
        height=raw.height,
        rotation=raw.rotation,
        xscale=raw.xscale,
        yscale=raw.yscale,
        zscale=raw.zscale,
        widthscale=raw.widthscale,
        oblique=raw.oblique,
        degree=raw.degree,
        colspace=raw.colspace,
        rowspace=raw.rowspace,
        p1=(raw.p1[0], raw.p1[1], raw.p1[2]),
        p2=(raw.p2[0], raw.p2[1], raw.p2[2]),
        p3=(raw.p3[0], raw.p3[1], raw.p3[2]),
        points=tuple(_array(raw.points, raw.npoints * 2)),
        bulges=_array(raw.bulges, raw.npoints),
        knots=_array(raw.knots, raw.nknots),
        weights=_array(raw.weights, raw.nweights),
        loop_offsets=tuple(int(v) for v in _array(raw.loop_offsets, raw.nloops)),
    )


def read(path: str) -> CadFile:
    """读一张 DXF/DWG，返回 :class:`CadFile`（解析不了抛 :class:`CadIoError`）。"""
    if not os.path.exists(path):
        raise CadIoError(f"找不到文件：{path}")
    lib = _load()
    error = ctypes.c_char_p()
    handle = lib.moz_cad_read(os.fsencode(path), ctypes.byref(error))
    if not handle:
        message = _text(error.value) or "未知原因"
        if error.value:
            lib.moz_str_free(error)
        raise CadIoError(message)

    try:
        cad = CadFile(
            path=path,
            format=_text(lib.moz_cad_format(handle)) or "dxf",
            version=_text(lib.moz_cad_version(handle)) or "",
            insunits=lib.moz_cad_insunits(handle),
        )
        low = (ctypes.c_double * 3)()
        high = (ctypes.c_double * 3)()
        if lib.moz_cad_extents(handle, low, high):
            cad.extents = (tuple(low), tuple(high))
        for index in range(lib.moz_cad_layer_count(handle)):
            raw = lib.moz_cad_layer_at(handle, index).contents
            flags = int(raw.flags)
            cad.layers.append(
                Layer(
                    name=_text(raw.name) or "0",
                    aci=raw.aci,
                    color24=None if raw.color24 < 0 else raw.color24,
                    linetype=_text(raw.linetype),
                    off=bool(flags & 1),
                    frozen=bool(flags & 2),
                    locked=bool(flags & 4),
                    lineweight=raw.lineweight,
                )
            )
        for index in range(lib.moz_cad_block_count(handle)):
            raw = lib.moz_cad_block_at(handle, index).contents
            cad.blocks.append(
                Block(
                    name=_text(raw.name) or "",
                    base_point=(raw.base_point[0], raw.base_point[1], raw.base_point[2]),
                    first_entity=raw.first_entity,
                    entity_count=raw.entity_count,
                )
            )
        for index in range(lib.moz_cad_entity_count(handle)):
            cad.entities.append(_convert_entity(lib.moz_cad_entity_at(handle, index).contents))
        for index in range(lib.moz_cad_warning_count(handle)):
            text = _text(lib.moz_cad_warning_at(handle, index))
            if text:
                cad.warnings.append(text)
    finally:
        lib.moz_cad_free(handle)
    return cad


def report(path: str) -> str:
    """便捷入口：读一张图并打印解析报告。"""
    return read(path).report()
