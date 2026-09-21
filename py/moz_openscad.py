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

与 OpenSCAD 语义对齐的建模能力（$fn/$fa/$fs 都可直接当具名参数传）::

    moz.text("Hi", size=10, font="Liberation Sans", fn=16)   # 文字（2D）
    moz.import_shape("x.dxf", layer="cutout1")               # 导入 stl/dxf/svg/off
    moz.surface("height.png", center=True)                   # 图像 / 文本高度图
    moz.polyhedron(points, triangles=...)                    # 点表 + 面表
    moz.multmatrix(matrix, shape)                            # 4x4 矩阵变换
    moz.sin_deg(60) / moz.acos_deg(x)                        # 与 SCAD 逐比特一致的角度三角函数
    moz.lookup(30, [[0, 0], [40, 4]])                        # 同 SCAD 的插值算式

取值（拿引擎算出来的数，全精度）::

    moz.value('dxf_dim(file = "/abs/x.dxf", name = "bodywidth")')   # -> "22"
    moz.number('version()[0]')                                      # -> 2026.0
    moz.vector('rands(0, 1, 1000, 18)')                             # -> 1000 个浮点

渲染 / 导出::

    g.render_png_bytes(400, 300, colorscheme="Tomorrow")   # 保留 color()（preview 路径）
    g.render_png_bytes(400, 300, renderer="cgal")          # 上游 --render=cgal（无颜色）
    g.face_colors()                                        # 与 binstl 逐面对齐的 RGBA
    g.log                                                  # echo / warning 日志

注意 ``settings(shape, fn=40)`` 生成的是块作用域赋值，而块里的 ``$fn`` 会**泄漏给同一
子对象列表中后面的兄弟对象**；只影响单个对象时请优先用具名参数（``sphere(r=1, fn=40)``）。
"""

import ctypes as C
import math
import os

# OpenSCAD 的资源目录（color-schemes/*.json、locale 等）靠应用路径向上查找定位；
# 共享库没有可用的应用路径，所以这里按仓库布局把它指到 vendored 的 3rd/openscad。
# 装成 wheel 后该目录不存在，就交给调用方用 MOZ_OPENSCAD_RESOURCE_DIR 指定。
_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "3rd", "openscad")
if os.path.isdir(os.path.join(_RESOURCE_DIR, "color-schemes")):
    os.environ.setdefault("MOZ_OPENSCAD_RESOURCE_DIR", os.path.abspath(_RESOURCE_DIR))

__all__ = [
    "eval_text", "eval_file", "dump", "dump_file", "value", "number", "vector",
    "Geometry", "OpenSCADError", "Shape", "Part", "RenderOptions",
    "cube", "sphere", "cylinder", "circle",
    "square", "polygon", "text", "polyhedron", "union", "difference", "intersection",
    "translate", "rotate", "scale", "mirror", "multmatrix", "hull", "minkowski",
    "linear_extrude", "rotate_extrude", "offset", "projection", "color",
    "import_shape", "surface", "settings", "lookup",
    "sin_deg", "cos_deg", "tan_deg", "asin_deg", "acos_deg", "atan_deg", "atan2_deg",
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
        # repr 给出能精确往返的最短十进制表示；用 15 位有效数字会把双精度截断，
        # 导致 Python 算出的参数（角度、长度）与引擎内部计算值不一致。
        return repr(value)
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

    def render_png(self, path, width=0, height=0, **options):
        return self._geometry().render_png(path, width, height, **options)

    def render_png_bytes(self, width=0, height=0, **options):
        return self._geometry().render_png_bytes(width, height, **options)

    def face_colors(self):
        return self._geometry().face_colors()

    def show(self, title="moz OpenSCAD", width=900, height=650):
        from moz_viewer import show_shape
        show_shape(self, title=title, width=width, height=height)

    def eval(self, **variables):
        merged = dict(self.variables)
        merged.update(variables)
        return eval_text(self.source, **merged)

    @property
    def is_empty(self):
        return self._geometry().is_empty

    @property
    def log(self):
        return self._geometry().log

    def hull(self, *others):
        return _compose("hull", self, *others)

    def minkowski(self, *others):
        return _compose("minkowski", self, *others)

    def linear_extrude(self, height, center=False, scale=None, twist=None, slices=None, convexity=None):
        return linear_extrude(self, height, center=center, scale=scale, twist=twist,
                              slices=slices, convexity=convexity)

    def rotate_extrude(self, angle=360, convexity=None):
        return rotate_extrude(self, angle=angle, convexity=convexity)

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


def _special_options(fn=None, fa=None, fs=None):
    """$fn / $fa / $fs 作为**具名参数**拼进调用。

    必须用具名参数而不是块作用域赋值：实测 ``{ $fn = 8; ... }`` 里的 $fn 会泄漏给
    同一子对象列表中后面的兄弟对象（`union(){ { $fn=8; cylinder(); } sphere(); }` 里的
    sphere 也变成 8 段），而具名参数只作用于该对象自己。
    """
    options = []
    if fn is not None:
        options.append(f"$fn = {_format_open_scad_value(fn)}")
    if fa is not None:
        options.append(f"$fa = {_format_open_scad_value(fa)}")
    if fs is not None:
        options.append(f"$fs = {_format_open_scad_value(fs)}")
    return options


def cube(size=[1, 1, 1], center=False):
    return Shape(f"cube(size = {_format_open_scad_value(size)}, center = {_format_open_scad_value(center)});")


def sphere(r=1, d=None, fn=None, fa=None, fs=None):
    opts = _special_options(fn, fa, fs)
    if d is not None:
        opts.insert(0, f"d = {_format_open_scad_value(d)}")
    else:
        opts.insert(0, f"r = {_format_open_scad_value(r)}")
    return Shape(f"sphere({', '.join(opts)});")


def cylinder(h=1, r=None, r1=None, r2=None, d=None, d1=None, d2=None, center=False,
             fn=None, fa=None, fs=None):
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
    opts.extend(_special_options(fn, fa, fs))
    return Shape(f"cylinder({', '.join(opts)});")


def circle(r=1, d=None, fn=None, fa=None, fs=None):
    opts = []
    if d is not None:
        opts.append(f"d = {_format_open_scad_value(d)}")
    else:
        opts.append(f"r = {_format_open_scad_value(r)}")
    opts.extend(_special_options(fn, fa, fs))
    return Shape(f"circle({', '.join(opts)});")


def square(size=[1, 1], center=False):
    return Shape(f"square(size = {_format_open_scad_value(size)}, center = {_format_open_scad_value(center)});")


def polygon(points, paths=None):
    if paths is None:
        return Shape(f"polygon(points = {_format_open_scad_value(points)});")
    return Shape(f"polygon(points = {_format_open_scad_value(points)}, paths = {_format_open_scad_value(paths)});")


def text(value, size=10, font=None, halign=None, valign=None, spacing=1, direction=None,
         fn=None, fa=None, fs=None):
    options = [f"size = {_format_open_scad_value(size)}", f"spacing = {_format_open_scad_value(spacing)}"]
    if font is not None:
        options.append(f"font = {_format_open_scad_value(font)}")
    if halign is not None:
        options.append(f"halign = {_format_open_scad_value(halign)}")
    if valign is not None:
        options.append(f"valign = {_format_open_scad_value(valign)}")
    if direction is not None:
        options.append(f"direction = {_format_open_scad_value(direction)}")
    options.extend(_special_options(fn, fa, fs))
    return Shape(f"text({_format_open_scad_value(value)}, {', '.join(options)});")


def import_shape(file, layer=None, origin=None, scale=None, convexity=None):
    """import()：导入 stl / dxf / svg / off 等外部文件。

    file 相对路径按文档目录解析；用 moz.eval_file 求值时，同目录的兄弟文件可直接写文件名。
    """
    options = [f"file = {_format_open_scad_value(file)}"]
    if layer is not None:
        options.append(f"layer = {_format_open_scad_value(layer)}")
    if origin is not None:
        options.append(f"origin = {_format_open_scad_value(origin)}")
    if scale is not None:
        options.append(f"scale = {_format_open_scad_value(scale)}")
    if convexity is not None:
        options.append(f"convexity = {_format_open_scad_value(convexity)}")
    return Shape(f"import({', '.join(options)});")


def surface(file, center=False, convexity=None, invert=False):
    """surface()：把图像（png 等）或文本高度图（dat）转成 3D 曲面。"""
    options = [f"file = {_format_open_scad_value(file)}", f"center = {_format_open_scad_value(center)}"]
    if convexity is not None:
        options.append(f"convexity = {_format_open_scad_value(convexity)}")
    if invert:
        options.append("invert = true")
    return Shape(f"surface({', '.join(options)});")


def polyhedron(points, faces=None, triangles=None, convexity=None):
    """polyhedron()：点表 + 面表（faces 或 triangles 二选一）。"""
    if faces is None and triangles is None:
        raise ValueError("polyhedron() requires faces or triangles")
    key, value = ("faces", faces) if faces is not None else ("triangles", triangles)
    options = [f"points = {_format_open_scad_value(points)}", f"{key} = {_format_open_scad_value(value)}"]
    if convexity is not None:
        options.append(f"convexity = {_format_open_scad_value(convexity)}")
    return Shape(f"polyhedron({', '.join(options)});")


def multmatrix(matrix, obj=None):
    """multmatrix()：按 4x4 矩阵变换对象。"""
    if obj is None:
        raise ValueError("multmatrix() requires an object; use multmatrix(matrix, shape)")
    return Shape(f"multmatrix({_format_open_scad_value(matrix)}) {_as_source(obj)}")


def settings(obj, **variables):
    """把 SCAD 变量作用域套在对象外层，复现原示例里的 $fn / $fa / $fs。

    settings(shape, fn=80) 生成 ``{ $fn = 80; <shape> }``。变量名不用写 $ 前缀，
    会自动补上；作为具名参数写的 ``$fn`` 与作用域里赋值的 ``$fn`` 对子对象等价。
    """
    if obj is None:
        raise ValueError("settings() requires an object")
    lines = []
    for name, value in variables.items():
        key = name if name.startswith("$") else f"${name}"
        lines.append(f"{key} = {_format_open_scad_value(value)};")
    lines.append(_as_source(obj))
    body = "\n".join(line if line.rstrip().endswith(";") else f"{line};" for line in lines)
    return Shape("{\n" + body + "\n}")


def lookup(key, pairs):
    """lookup()：按 SCAD 内建 lookup() 的算式复刻（逐比特一致）。

    SCAD 的写法是 ``high_v * f + low_v * (1 - f)``（f = (p-low_p)/(high_p-low_p)），
    与直觉上的 ``low_v + (p-low_p)*(high_v-low_v)/(high_p-low_p)`` 在浮点末位不同。
    """
    if not pairs:
        return None
    low_p, low_v = pairs[0][0], pairs[0][1]
    high_p, high_v = low_p, low_v
    for this_p, this_v in pairs[1:]:
        if this_p <= key and (this_p > low_p or low_p > key):
            low_p, low_v = this_p, this_v
        if this_p >= key and (this_p < high_p or high_p < key):
            high_p, high_v = this_p, this_v
    if key <= low_p:
        return float(high_v)
    if key >= high_p:
        return float(low_v)
    f = (key - low_p) / (high_p - low_p)
    return float(high_v) * f + float(low_v) * (1 - f)


# --- SCAD 的角度三角函数 ---
#
# SCAD 的 sin/cos/tan/acos/atan2 都以度为单位，而且 OpenSCAD 不是简单地把角度
# 乘上 π/180 再调 std::sin：它用 degree_trig.cc 里的专用实现，对 30/45/60/90 等
# 角度直接给出精确常量（M_SQRT1_2 / M_SQRT3_4 ...）。用 math.radians 会差最后几位，
# 进而让导出的网格出现字节差异，所以这里按同一算法复刻。

_M_DEG2RAD = 0.017453292519943295769
_M_RAD2DEG = 57.2957795130823208767
_M_SQRT1_2 = 0.70710678118654752440
_M_SQRT3_4 = 0.86602540378443859659
_M_SQRT1_3 = 0.57735026918962573106
_M_SQRT3 = 1.73205080756887719318
_TRIG_HUGE_VAL = float((1 << 26) * 360.0 * (1 << 26))


def _deg2rad(x):
    return x * _M_DEG2RAD


def _rad2deg(x):
    return x * _M_RAD2DEG


def sin_deg(x):
    """与 SCAD 的 sin(x)（x 为角度）逐一比特一致。"""
    if not (0.0 <= x < 360.0):
        if not (-_TRIG_HUGE_VAL < x < _TRIG_HUGE_VAL):
            return float("nan")
        x -= 360.0 * math.floor(x / 360.0)
    oppose = x >= 180.0
    if oppose:
        x -= 180.0
    if x > 90.0:
        x = 180.0 - x
    if x < 45.0:
        x = 0.5 if x == 30.0 else math.sin(_deg2rad(x))
    elif x == 45.0:
        x = _M_SQRT1_2
    elif x == 60.0:
        x = _M_SQRT3_4
    else:
        x = math.cos(_deg2rad(90.0 - x))
    return -x if oppose else x


def cos_deg(x):
    """与 SCAD 的 cos(x)（x 为角度）逐一比特一致。"""
    if not (0.0 <= x < 360.0):
        if not (-_TRIG_HUGE_VAL < x < _TRIG_HUGE_VAL):
            return float("nan")
        x -= 360.0 * math.floor(x / 360.0)
    oppose = x >= 180.0
    if oppose:
        x -= 180.0
    if x > 90.0:
        x = 180.0 - x
        oppose = not oppose
    if x > 45.0:
        x = 0.5 if x == 60.0 else math.sin(_deg2rad(90.0 - x))
    elif x == 45.0:
        x = _M_SQRT1_2
    elif x == 30.0:
        x = _M_SQRT3_4
    else:
        x = math.cos(_deg2rad(x))
    return -x if oppose else x


def tan_deg(x):
    """与 SCAD 的 tan(x)（x 为角度）一致。"""
    cycles = math.floor(x / 180.0)
    if not (0.0 <= x < 180.0):
        if not (-_TRIG_HUGE_VAL < x < _TRIG_HUGE_VAL):
            return float("nan")
        x -= 180.0 * cycles
    oppose = x > 90.0
    if oppose:
        x = 180.0 - x
    if x == 0.0:
        x = 0.0 if (cycles % 2) == 0 else -0.0
    elif x == 30.0:
        x = _M_SQRT1_3
    elif x == 45.0:
        x = 1.0
    elif x == 60.0:
        x = _M_SQRT3
    elif x == 90.0:
        x = float("inf") if (cycles % 2) == 0 else float("-inf")
    else:
        x = math.tan(_deg2rad(x))
    return -x if oppose else x


def asin_deg(x):
    """与 SCAD 的 asin(x)（返回角度）一致。"""
    degs = _rad2deg(math.asin(x))
    whole = round(degs)
    return whole if sin_deg(whole) == x else degs


def acos_deg(x):
    """与 SCAD 的 acos(x)（返回角度）一致。"""
    degs = _rad2deg(math.acos(x))
    whole = round(degs)
    return whole if cos_deg(whole) == x else degs


def atan_deg(x):
    """与 SCAD 的 atan(x)（返回角度）一致。"""
    degs = _rad2deg(math.atan(x))
    whole = round(degs)
    return whole if tan_deg(whole) == x else degs


def atan2_deg(y, x):
    """与 SCAD 的 atan2(y, x)（返回角度）一致。"""
    degs = _rad2deg(math.atan2(y, x))
    whole = round(degs)
    return whole if abs(degs - whole) < 3.0e-14 else degs


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


def linear_extrude(obj, height, center=False, scale=None, twist=None, slices=None,
                   convexity=None, fn=None, fa=None, fs=None):
    """linear_extrude()：只写出调用方真正指定的参数。

    不能给 scale/twist/slices 塞默认值：原示例不传 slices 时用的是 SCAD 自己的默认
    （按 twist 推导），硬写 slices = 20 会凭空多出 20 层切片、改变网格。
    """
    if obj is None:
        raise ValueError("linear_extrude() requires an object")
    options = [f"height = {_format_open_scad_value(height)}", f"center = {_format_open_scad_value(center)}"]
    if scale is not None:
        options.append(f"scale = {_format_open_scad_value(scale)}")
    if twist is not None:
        options.append(f"twist = {_format_open_scad_value(twist)}")
    if slices is not None:
        options.append(f"slices = {_format_open_scad_value(slices)}")
    if convexity is not None:
        options.append(f"convexity = {_format_open_scad_value(convexity)}")
    options.extend(_special_options(fn, fa, fs))
    return Shape(f"linear_extrude({', '.join(options)}) {_as_source(obj)}")


def rotate_extrude(obj, angle=360, convexity=None, fn=None, fa=None, fs=None):
    if obj is None:
        raise ValueError("rotate_extrude() requires an object")
    options = [f"angle = {_format_open_scad_value(angle)}"]
    if convexity is not None:
        options.append(f"convexity = {_format_open_scad_value(convexity)}")
    options.extend(_special_options(fn, fa, fs))
    return Shape(f"rotate_extrude({', '.join(options)}) {_as_source(obj)}")


def offset(obj, r=None, delta=None, chamfer=None, fn=None, fa=None, fs=None):
    """offset()：第一个位置参数是圆角半径 r（原 .scad 写 offset(10) 就是 r = 10）。

    r 是圆角外扩/内缩（会倒圆角），delta 是尖角外扩/内缩（保留尖角），chamfer 与
    delta 配合做倒角。r 和 delta 至少要给一个。
    """
    if obj is None:
        raise ValueError("offset() requires an object")
    if r is None and delta is None:
        raise ValueError("offset() requires r or delta")
    options = []
    if r is not None:
        options.append(f"r = {_format_open_scad_value(r)}")
    if delta is not None:
        options.append(f"delta = {_format_open_scad_value(delta)}")
    if chamfer is not None:
        options.append(f"chamfer = {_format_open_scad_value(chamfer)}")
    options.extend(_special_options(fn, fa, fs))
    return Shape(f"offset({', '.join(options)}) {_as_source(obj)}")


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
    lib.moz_geom_is_empty.restype = C.c_int
    lib.moz_geom_is_empty.argtypes = [C.c_void_p]
    lib.moz_geom_log.restype = C.c_void_p
    lib.moz_geom_log.argtypes = [C.c_void_p, C.c_int]

    lib.moz_export.restype = C.c_int
    lib.moz_export.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_void_p]
    lib.moz_export_bytes.restype = C.c_int
    lib.moz_export_bytes.argtypes = [C.c_void_p, C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p]
    lib.moz_geom_face_colors.restype = C.c_int
    lib.moz_geom_face_colors.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]

    lib.moz_render_options_default.restype = None
    lib.moz_render_options_default.argtypes = [C.c_void_p]
    lib.moz_render_png.restype = C.c_int
    lib.moz_render_png.argtypes = [C.c_void_p, C.c_char_p, C.c_void_p, C.c_void_p]
    lib.moz_render_png_bytes.restype = C.c_int
    lib.moz_render_png_bytes.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]

    lib.moz_eval_value.restype = C.c_void_p
    lib.moz_eval_value.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_int, C.c_void_p]

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


class RenderOptions(C.Structure):
    """moz_render_options 的镜像（见 3rd/openscad/src/moz/moz_api.h）。"""

    _fields_ = [
        ("width", C.c_uint),
        ("height", C.c_uint),
        ("renderer", C.c_int),
        ("show_faces", C.c_int),
        ("show_edges", C.c_int),
        ("show_axes", C.c_int),
        ("show_scales", C.c_int),
        ("show_crosshairs", C.c_int),
        ("colorscheme", C.c_char_p),
    ]


RENDERER_OPENCSG = 0
RENDERER_THROWNTOGETHER = 1
RENDERER_CGAL = 2

_RENDERER_NAMES = {
    "opencsg": RENDERER_OPENCSG,
    "throwntogether": RENDERER_THROWNTOGETHER,
    "cgal": RENDERER_CGAL,
}


def _render_options(width=0, height=0, renderer="opencsg", faces=True, edges=False,
                    axes=False, scales=False, crosshairs=False, colorscheme=None):
    """构造渲染选项。width/height 为 0 时用库默认值（RenderSettings，512x512）。

    renderer="opencsg"/"throwntogether" 走上游 preview 路径（color() 生效），
    renderer="cgal" 走上游 --render=cgal 的几何渲染（无颜色）。
    """
    if isinstance(renderer, str):
        renderer = _RENDERER_NAMES[renderer]
    return RenderOptions(
        width, height, renderer,
        int(bool(faces)), int(bool(edges)), int(bool(axes)),
        int(bool(scales)), int(bool(crosshairs)),
        colorscheme.encode() if colorscheme else None,
    )


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


def _split_scad_list(text):
    """按顶层逗号切分 SCAD 列表内容（跳过括号与字符串内部）。"""
    parts, depth, current, in_string, escaped = [], 0, [], False, False
    for ch in text:
        if in_string:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_scad_value(text):
    """把 value() 的文本结果解析成 Python 值（数字 / 字符串 / 布尔 / 列表 / 区间）。"""
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "undef":
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        if "," not in inner and inner.count(":") in (1, 2):
            # 区间字面量 [begin : end] / [begin : step : end]
            return [_parse_scad_value(part) for part in inner.split(":")]
        return [_parse_scad_value(part) for part in _split_scad_list(inner)]
    try:
        return float(text)
    except ValueError:
        return text


def value(expression, source="", **variables):
    """在 source 的顶层作用域中求值一个 SCAD 表达式，返回其值文本。

    用于 dxf_dim() / dxf_cross() / rands() / lookup() / search() / version() 这类
    有返回值、无法通过几何句柄取得的函数。数值按 17 位有效数字输出（双精度无损）。
    source 里的变量、函数均可直接使用；**variables 对应 -D 参数。

    表达式求值不出来时（引擎会给出 undef 并附警告，例如未知函数、参数类型不对）
    抛 OpenSCADError，消息里带引擎日志。
    """
    lib = _load()
    err = _as_err()
    arr, n = _assignments(variables)
    out = C.c_void_p(lib.moz_eval_value(source.encode(), expression.encode(), arr, n, C.byref(err)))
    if not out.value:
        raise OpenSCADError(_err_msg(err) or "OpenSCAD expression evaluation failed")
    try:
        return C.string_at(out.value).decode("utf-8", "replace")
    finally:
        lib.moz_str_free(out)


def number(expression, source="", **variables):
    """value() 的数值版，返回 float。"""
    text = value(expression, source, **variables).strip()
    try:
        return float(text)
    except ValueError as exc:
        raise OpenSCADError(f"expression {expression!r} did not produce a number: {text!r}") from exc


def vector(expression, source="", **variables):
    """value() 的列表版，返回 Python list（元素递归解析为数字/字符串/列表）。"""
    parsed = _parse_scad_value(value(expression, source, **variables))
    if not isinstance(parsed, list):
        raise OpenSCADError(f"expression {expression!r} did not produce a vector: {parsed!r}")
    return parsed


class Geometry:
    """一次解析 + 求值的产物句柄。释放底层节点树 / 模块树 / 几何。"""

    def __init__(self, handle):
        self._handle = handle
        self._closed = False

    @property
    def dimension(self):
        """几何维度（上游语义）：3 / 2；空几何仍返回 3（空 Nef 的 getDimension 恒为 3）。"""
        self._check()
        return _load().moz_geom_dimension(self._handle)

    @property
    def is_empty(self):
        """是否为空几何（零面积 / 零体积）。"""
        self._check()
        return bool(_load().moz_geom_is_empty(self._handle))

    @property
    def log(self):
        """本次求值 / 导出 / 渲染累积的消息日志（echo + warning），与 OpenSCAD 控制台文本一致。"""
        self._check()
        lib = _load()
        out = lib.moz_geom_log(self._handle, 0)
        if not out:
            return ""
        try:
            return C.string_at(out).decode("utf-8", "replace")
        finally:
            lib.moz_str_free(out)

    def take_log(self):
        """读取并清空消息日志（每行一条，含 "ECHO: " / "WARNING: " 前缀）。"""
        self._check()
        lib = _load()
        out = lib.moz_geom_log(self._handle, 1)
        if not out:
            return ""
        try:
            return C.string_at(out).decode("utf-8", "replace")
        finally:
            lib.moz_str_free(out)

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

    def face_colors(self):
        """逐面颜色：4 字节/面（RGBA），与 export_bytes("binstl") 的三角面一一对应。

        颜色来自 color()；未着色对象取当前配色方案的材质色。预览器用它给网格上色。
        """
        self._check()
        lib = _load()
        err = _as_err()
        buf = C.c_void_p()
        length = C.c_size_t()
        rc = lib.moz_geom_face_colors(self._handle, C.byref(buf), C.byref(length), C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"face color export failed ({rc})")
        try:
            return C.string_at(buf.value, length.value) if length.value else b""
        finally:
            lib.moz_bytes_free(buf)

    def render_png(self, path, width=0, height=0, **options):
        """渲染 PNG 到文件。width/height 为 0 时用库默认尺寸（RenderSettings，512x512）。

        options 见 _render_options：renderer / colorscheme / faces / edges / axes ...
        """
        self._check()
        lib = _load()
        err = _as_err()
        opts = _render_options(width, height, **options)
        rc = lib.moz_render_png(self._handle, path.encode(), C.byref(opts), C.byref(err))
        if rc != 0:
            raise OpenSCADError(_err_msg(err) or f"PNG render failed ({rc})")

    def render_png_bytes(self, width=0, height=0, **options):
        self._check()
        lib = _load()
        err = _as_err()
        opts = _render_options(width, height, **options)
        buf = C.c_void_p()
        length = C.c_size_t()
        rc = lib.moz_render_png_bytes(self._handle, C.byref(opts),
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