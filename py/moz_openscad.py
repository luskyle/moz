"""moz_openscad — OpenSCAD 2021.01 无 GUI 核心的 Python 绑定（纯 ctypes，零依赖）

底层是 3rd/openscad 构建出的 libmozopenscad.so（C ABI，见 src/moz/moz_api.h）。

用法::

    import moz_openscad as moz

    g = moz.eval_text('cube([10, 20, 30]);')
    print(g.dimension)          # 3
    g.export('binstl', 'out.stl')

    g2 = moz.eval_text('circle(r=10);')
    g2.export('dxf', 'out.dxf')
    print(moz.dump('cube(2);', 'csg'))

库路径解析顺序: 环境变量 MOZ_OPENSCAD_LIB > 模块同目录 libmozopenscad.so > build/lib/
"""

import ctypes as C
import os

__all__ = [
    "eval_text", "eval_file", "dump", "dump_file",
    "Geometry", "OpenSCADError", "Shape", "Part",
    "cube", "sphere", "cylinder", "circle",
    "square", "polygon", "union", "difference", "intersection",
    "translate", "rotate", "scale", "mirror", "hull", "minkowski",
    "linear_extrude", "rotate_extrude", "offset", "projection", "color",
    "Box", "Cylinder", "Sphere", "Plate", "Hole", "Bracket",
]

_c_char_p = C.c_char_p
_c_pp_char = C.POINTER(C.c_char_p)


def _format_open_scad_value(value):
    if isinstance(value, Shape):
        return f"({value.source})"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_open_scad_value(v) for v in value) + "]"
    if isinstance(value, dict):
        items = [f"{_format_open_scad_value(k)}: {_format_open_scad_value(v)}" for k, v in value.items()]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "undef"
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def _as_source(obj):
    if obj is None:
        return ""
    if isinstance(obj, Shape):
        return obj.source
    if isinstance(obj, str):
        return obj.strip()
    return _format_open_scad_value(obj)


def _compose(op, *items):
    exprs = [_as_source(item) for item in items if item is not None]
    if not exprs:
        raise ValueError(f"{op} requires at least one operand")
    body = "\n".join(f"{expr};" if not expr.rstrip().endswith(";") else expr.rstrip() for expr in exprs)
    return Shape(f"{op}() {{\n{body}\n}}")


class Shape:
    """Python-level OpenSCAD shape object backed by the C++ shared library eval path."""

    def __init__(self, source, **variables):
        self.source = source.strip().rstrip(";")
        self.variables = dict(variables)

    def _source_for_eval(self):
        text = self.source.strip()
        if not text:
            return text
        if text.endswith(";"):
            return text
        if text.endswith("}"):
            return text
        return text + ";"

    def _geometry(self):
        return eval_text(self._source_for_eval(), **self.variables)

    def union(self, *others):
        return _compose("union", self, *others)

    def difference(self, *others):
        return _compose("difference", self, *others)

    def intersection(self, *others):
        return _compose("intersection", self, *others)

    def translate(self, vector):
        return Shape(f"translate({_format_open_scad_value(vector)}) {_as_source(self)}")

    def rotate(self, a, v=None):
        if v is None:
            if isinstance(a, (list, tuple)):
                body = _format_open_scad_value(a)
                expr = f"rotate(a = {body})"
            else:
                expr = f"rotate(a = {_format_open_scad_value(a)})"
        else:
            expr = f"rotate(a = {_format_open_scad_value(a)}, v = {_format_open_scad_value(v)})"
        return Shape(f"{expr} {_as_source(self)}")

    def scale(self, vector):
        return Shape(f"scale(v = {_format_open_scad_value(vector)}) {_as_source(self)}")

    def mirror(self, vector):
        return Shape(f"mirror(v = {_format_open_scad_value(vector)}) {_as_source(self)}")

    @property
    def dimension(self):
        return self._geometry().dimension

    def export(self, fmt, path):
        return self._geometry().export(fmt, path)

    def export_bytes(self, fmt):
        return self._geometry().export_bytes(fmt)

    def render_png(self, path, width=800, height=600):
        return self._geometry().render_png(path, width, height)

    def render_png_bytes(self, width=800, height=600):
        return self._geometry().render_png_bytes(width, height)

    def show(self, title="moz OpenSCAD", width=900, height=650):
        from moz_viewer import show_shape
        show_shape(self, title=title, width=width, height=height)

    def eval(self, **variables):
        merged = dict(self.variables)
        merged.update(variables)
        return eval_text(self.source, **merged)

    def union(self, *others):
        return _compose("union", self, *others)

    def difference(self, *others):
        return _compose("difference", self, *others)

    def intersection(self, *others):
        return _compose("intersection", self, *others)

    def hull(self, *others):
        return _compose("hull", self, *others)

    def minkowski(self, *others):
        return _compose("minkowski", self, *others)

    def linear_extrude(self, height, center=False, scale=1, twist=0, slices=20):
        return Shape(f"linear_extrude(height = {_format_open_scad_value(height)}, center = {_format_open_scad_value(center)}, scale = {_format_open_scad_value(scale)}, twist = {_format_open_scad_value(twist)}, slices = {_format_open_scad_value(slices)}) {_as_source(self)}")

    def rotate_extrude(self, angle=360):
        return Shape(f"rotate_extrude(angle = {_format_open_scad_value(angle)}) {_as_source(self)}")

    def offset(self, delta):
        return Shape(f"offset(delta = {_format_open_scad_value(delta)}) {_as_source(self)}")

    def projection(self, cut=False):
        return Shape(f"projection(cut = {_format_open_scad_value(cut)}) {_as_source(self)}")

    def color(self, name, alpha=None):
        if alpha is None:
            return Shape(f"color({_format_open_scad_value(name)}) {_as_source(self)}")
        return Shape(f"color({_format_open_scad_value(name)}, {_format_open_scad_value(alpha)}) {_as_source(self)}")

    def cut(self, *others):
        return self.difference(*others)

    def add(self, *others):
        return self.union(*others)

    def __str__(self):
        return self.source

    def __repr__(self):
        return f"Shape({self.source!r})"


def cube(size=[1, 1, 1], center=False):
    return Shape(f"cube(size = {_format_open_scad_value(size)}, center = {_format_open_scad_value(center)});")


def sphere(r=1, d=None):
    if d is not None:
        return Shape(f"sphere(d = {_format_open_scad_value(d)});")
    return Shape(f"sphere(r = {_format_open_scad_value(r)});")


def cylinder(h=1, r=None, r1=None, r2=None, d=None, d1=None, d2=None, center=False):
    opts = [f"h = {_format_open_scad_value(h)}", f"center = {_format_open_scad_value(center)}"]
    if r is not None:
        opts.append(f"r = {_format_open_scad_value(r)}")
    if r1 is not None:
        opts.append(f"r1 = {_format_open_scad_value(r1)}")
    if r2 is not None:
        opts.append(f"r2 = {_format_open_scad_value(r2)}")
    if d is not None:
        opts.append(f"d = {_format_open_scad_value(d)}")
    if d1 is not None:
        opts.append(f"d1 = {_format_open_scad_value(d1)}")
    if d2 is not None:
        opts.append(f"d2 = {_format_open_scad_value(d2)}")
    return Shape(f"cylinder({', '.join(opts)});")


def circle(r=1, d=None):
    if d is not None:
        return Shape(f"circle(d = {_format_open_scad_value(d)});")
    return Shape(f"circle(r = {_format_open_scad_value(r)});")


def square(size=[1, 1], center=False):
    return Shape(f"square(size = {_format_open_scad_value(size)}, center = {_format_open_scad_value(center)});")


def polygon(points, paths=None):
    if paths is None:
        return Shape(f"polygon(points = {_format_open_scad_value(points)});")
    return Shape(f"polygon(points = {_format_open_scad_value(points)}, paths = {_format_open_scad_value(paths)});")


def union(*items):
    return _compose("union", *items)


def difference(*items):
    return _compose("difference", *items)


def intersection(*items):
    return _compose("intersection", *items)


def translate(vector, obj=None):
    if obj is None:
        raise ValueError("translate() requires an object; use shape.translate(vector)")
    return Shape(f"translate({_format_open_scad_value(vector)}) {_as_source(obj)}")


def rotate(a, v=None, obj=None):
    if obj is None:
        if v is not None and hasattr(v, "source"):
            obj = v
            v = None
        elif isinstance(v, (list, tuple, str, int, float, bool)):
            obj = None
        else:
            raise ValueError("rotate() requires an object; use shape.rotate(a, v)")
    if obj is None:
        raise ValueError("rotate() requires an object; use shape.rotate(a, v)")
    if v is None:
        text = f"rotate(a = {_format_open_scad_value(a)})"
    else:
        text = f"rotate(a = {_format_open_scad_value(a)}, v = {_format_open_scad_value(v)})"
    return Shape(f"{text} {_as_source(obj)}")


def scale(vector, obj=None):
    if obj is None:
        raise ValueError("scale() requires an object; use shape.scale(vector)")
    return Shape(f"scale(v = {_format_open_scad_value(vector)}) {_as_source(obj)}")


def mirror(vector, obj=None):
    if obj is None:
        raise ValueError("mirror() requires an object; use shape.mirror(vector)")
    return Shape(f"mirror(v = {_format_open_scad_value(vector)}) {_as_source(obj)}")


def hull(*items):
    return _compose("hull", *items)


def minkowski(*items):
    return _compose("minkowski", *items)


def linear_extrude(obj, height, center=False, scale=1, twist=0, slices=20):
    if obj is None:
        raise ValueError("linear_extrude() requires an object")
    return Shape(f"linear_extrude(height = {_format_open_scad_value(height)}, center = {_format_open_scad_value(center)}, scale = {_format_open_scad_value(scale)}, twist = {_format_open_scad_value(twist)}, slices = {_format_open_scad_value(slices)}) {_as_source(obj)}")


def rotate_extrude(obj, angle=360):
    if obj is None:
        raise ValueError("rotate_extrude() requires an object")
    return Shape(f"rotate_extrude(angle = {_format_open_scad_value(angle)}) {_as_source(obj)}")


def offset(obj, delta):
    if obj is None:
        raise ValueError("offset() requires an object")
    return Shape(f"offset(delta = {_format_open_scad_value(delta)}) {_as_source(obj)}")


def projection(obj, cut=False):
    if obj is None:
        raise ValueError("projection() requires an object")
    return Shape(f"projection(cut = {_format_open_scad_value(cut)}) {_as_source(obj)}")


def color(obj, name, alpha=None):
    if obj is None:
        raise ValueError("color() requires an object")
    if alpha is None:
        return Shape(f"color({_format_open_scad_value(name)}) {_as_source(obj)}")
    return Shape(f"color({_format_open_scad_value(name)}, {_format_open_scad_value(alpha)}) {_as_source(obj)}")


class Part:
    """更接近工程设计语言的高层对象，最终仍然落回 Shape -> native OpenSCAD library."""

    def __init__(self, shape, name=None):
        if isinstance(shape, Shape):
            self.shape = shape
        elif isinstance(shape, Part):
            self.shape = shape.shape
        else:
            self.shape = Shape(str(shape))
        self.name = name

    @property
    def source(self):
        return self.shape.source

    @property
    def dimension(self):
        return self.shape.dimension

    def export(self, fmt, path):
        return self.shape.export(fmt, path)

    def export_bytes(self, fmt):
        return self.shape.export_bytes(fmt)

    def render_png(self, path, width=800, height=600):
        return self.shape.render_png(path, width, height)

    def render_png_bytes(self, width=800, height=600):
        return self.shape.render_png_bytes(width, height)

    def show(self, title="moz OpenSCAD", width=900, height=650):
        self.shape.show(title=title, width=width, height=height)

    def at(self, x=0, y=0, z=0):
        return Part(translate([x, y, z], self.shape), name=self.name)

    def move(self, vector):
        return Part(translate(vector, self.shape), name=self.name)

    def rotate(self, a, v=None):
        return Part(self.shape.rotate(a, v), name=self.name)

    def scale(self, vector):
        return Part(self.shape.scale(vector), name=self.name)

    def mirror(self, vector):
        return Part(self.shape.mirror(vector), name=self.name)

    def add(self, *others):
        merged = [self.shape]
        for other in others:
            merged.append(other.shape if isinstance(other, Part) else Shape(str(other)))
        return Part(union(*merged), name=self.name)

    def cut(self, *others):
        merged = [self.shape]
        for other in others:
            merged.append(other.shape if isinstance(other, Part) else Shape(str(other)))
        return Part(difference(*merged), name=self.name)

    def __add__(self, other):
        return self.add(other)

    def __sub__(self, other):
        return self.cut(other)

    def __str__(self):
        return self.source

    def __repr__(self):
        return f"Part({self.source!r})"


class Box(Part):
    def __init__(self, size=(1, 1, 1), center=False, name=None):
        super().__init__(cube(size, center), name=name)


class Cylinder(Part):
    def __init__(self, h=1, r=None, r1=None, r2=None, d=None, d1=None, d2=None, center=False, name=None):
        super().__init__(cylinder(h=h, r=r, r1=r1, r2=r2, d=d, d1=d1, d2=d2, center=center), name=name)


class Sphere(Part):
    def __init__(self, r=1, d=None, name=None):
        super().__init__(sphere(r=r, d=d), name=name)


class Hole(Part):
    def __init__(self, diameter, depth=None, name=None):
        h = depth if depth is not None else 10
        super().__init__(cylinder(h=h, d=diameter, center=True), name=name)


class Plate(Part):
    def __init__(self, size=(50, 50), thickness=3, hole_diameter=None, hole_positions=None, center=True, name=None):
        plate = cube([size[0], size[1], thickness], center=center)
        if hole_diameter is not None and hole_positions:
            holes = []
            for x, y in hole_positions:
                hole = Hole(hole_diameter, depth=thickness + 2)
                hole = hole.move([x, y, 0])
                holes.append(hole)
            plate = plate.cut(*holes)
        super().__init__(plate, name=name)


class Bracket(Part):
    def __init__(self, width=40, height=60, thickness=6, depth=None, hole_diameter=None, hole_positions=None, name=None):
        if depth is None:
            depth = width
        base = Box((width, thickness, height), center=False, name="base")
        side = Box((thickness, depth, height), center=False, name="side")
        part = base.add(side.move([0, width - thickness, 0]))
        if hole_diameter is not None and hole_positions:
            holes = [Hole(hole_diameter, depth=height + 2, name="hole").move([x, y, 0]) for x, y in hole_positions]
            part = part.cut(*holes)
        super().__init__(part.shape, name=name)


class OpenSCADError(RuntimeError):
    """OpenSCAD 解析 / 求值 / 导出失败。消息来自底层 err 缓冲。"""


def _find_lib():
    env = os.environ.get("MOZ_OPENSCAD_LIB")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "libmozopenscad.so"),
        os.path.join(here, "..", "build", "lib", "libmozopenscad.so"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise OpenSCADError(f"libmozopenscad.so not found; build it first (see build_moz_openscad.sh), "
                        f"or set MOZ_OPENSCAD_LIB. Searched: {candidates}")


_lib = None


def _load():
    global _lib
    if _lib is not None:
        return _lib
    lib = C.CDLL(_find_lib())

    lib.moz_eval_text.restype = C.c_void_p
    lib.moz_eval_text.argtypes = [C.c_char_p, C.c_void_p, C.c_int, C.c_void_p]
    lib.moz_eval_file.restype = C.c_void_p
    lib.moz_eval_file.argtypes = [C.c_char_p, C.c_void_p, C.c_int, C.c_void_p]

    lib.moz_geom_dimension.restype = C.c_int
    lib.moz_geom_dimension.argtypes = [C.c_void_p]

    lib.moz_export.restype = C.c_int
    lib.moz_export.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_void_p]
    lib.moz_export_bytes.restype = C.c_int
    lib.moz_export_bytes.argtypes = [C.c_void_p, C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p]

    lib.moz_render_png.restype = C.c_int
    lib.moz_render_png.argtypes = [C.c_void_p, C.c_char_p, C.c_uint, C.c_uint, C.c_void_p]
    lib.moz_render_png_bytes.restype = C.c_int
    lib.moz_render_png_bytes.argtypes = [C.c_void_p, C.c_uint, C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p]

    lib.moz_dump.restype = C.c_void_p
    lib.moz_dump.argtypes = [C.c_char_p, C.c_char_p, C.c_char_p, C.c_void_p, C.c_int, C.c_void_p]
    lib.moz_dump_file.restype = C.c_void_p
    lib.moz_dump_file.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_int, C.c_void_p]

    lib.moz_geom_free.argtypes = [C.c_void_p]
    lib.moz_str_free.argtypes = [C.c_void_p]
    lib.moz_bytes_free.argtypes = [C.c_void_p]

    _lib = lib
    return lib


def _as_err():
    return C.c_void_p()


def _err_msg(err_p):
    val = err_p.value
    if not val:
        return ""
    try:
        return C.string_at(val).decode("utf-8", "replace")
    finally:
        _load().moz_str_free(val)


def _assignments(variables):
    items = [f"{k}={v}" for k, v in variables.items()]
    if not items:
        return None, 0
    buf = (_c_char_p * len(items))(*[C.c_char_p(s.encode()) for s in items])
    return C.cast(buf, C.c_void_p), len(items)


def eval_text(source, **variables):
    """解析并求值 SCAD 源码，返回 Geometry。关键字参数为预定义变量（对应 -D）。"""
    lib = _load()
    err = _as_err()
    arr, n = _assignments(variables)
    handle = C.c_void_p(lib.moz_eval_text(source.encode(), arr, n, C.byref(err)))
    if not handle.value:
        raise OpenSCADError(_err_msg(err) or "OpenSCAD evaluation failed")
    return Geometry(handle)


def eval_file(path, **variables):
    lib = _load()
    err = _as_err()
    arr, n = _assignments(variables)
    handle = C.c_void_p(lib.moz_eval_file(path.encode(), arr, n, C.byref(err)))
    if not handle.value:
        raise OpenSCADError(_err_msg(err) or "OpenSCAD evaluation failed")
    return Geometry(handle)


def dump(source, fmt="csg", **variables):
    """解析 SCAD 源码并输出文本结构：csg / ast / term / echo。"""
    lib = _load()
    err = _as_err()
    arr, n = _assignments(variables)
    out = C.c_void_p(lib.moz_dump(source.encode(), None, fmt.encode(), arr, n, C.byref(err)))
    if not out.value:
        raise OpenSCADError(_err_msg(err) or "OpenSCAD dump failed")
    try:
        return C.string_at(out.value).decode("utf-8", "replace")
    finally:
        lib.moz_str_free(out)


def dump_file(path, fmt="csg", **variables):
    lib = _load()
    err = _as_err()
    arr, n = _assignments(variables)
    out = C.c_void_p(lib.moz_dump_file(path.encode(), fmt.encode(), arr, n, C.byref(err)))
    if not out.value:
        raise OpenSCADError(_err_msg(err) or "OpenSCAD dump failed")
    try:
        return C.string_at(out.value).decode("utf-8", "replace")
    finally:
        lib.moz_str_free(out)


class Geometry:
    """一次解析 + 求值的产物句柄。释放底层节点树 / 模块树 / 几何。"""

    def __init__(self, handle):
        self._handle = handle
        self._closed = False

    @property
    def dimension(self):
        """几何维度：2 / 3 / 0（空）。"""
        self._check()
        return _load().moz_geom_dimension(self._handle)

    def export(self, fmt, path):
        """导出到文件。fmt: stl / binstl / asciistl / off / amf / 3mf / dxf / svg / pdf / nef3 / nefdbg"""
        self._check()
        lib = _load()
        err = _as_err()
        rc = lib.moz_export(self._handle, fmt.encode(), path.encode(), C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"export failed ({rc})")

    def export_bytes(self, fmt):
        """导出到内存，返回 bytes。"""
        self._check()
        lib = _load()
        err = _as_err()
        buf = C.c_void_p()
        length = C.c_size_t()
        rc = lib.moz_export_bytes(self._handle, fmt.encode(),
                                  C.byref(buf), C.byref(length), C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"export failed ({rc})")
        try:
            return C.string_at(buf.value, length.value)
        finally:
            lib.moz_bytes_free(buf)

    def render_png(self, path, width=800, height=600):
        self._check()
        lib = _load()
        err = _as_err()
        rc = lib.moz_render_png(self._handle, path.encode(), width, height, C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"PNG render failed ({rc})")

    def render_png_bytes(self, width=800, height=600):
        self._check()
        lib = _load()
        err = _as_err()
        buf = C.c_void_p()
        length = C.c_size_t()
        rc = lib.moz_render_png_bytes(self._handle, width, height,
                                      C.byref(buf), C.byref(length), C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"PNG render failed ({rc})")
        try:
            return C.string_at(buf.value, length.value)
        finally:
            lib.moz_bytes_free(buf)

    def close(self):
        if not self._closed:
            _load().moz_geom_free(self._handle)
            self._closed = True

    def _check(self):
        if self._closed:
            raise OpenSCADError("geometry handle already closed")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()