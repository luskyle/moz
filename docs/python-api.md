# Python API 参考（`moz_openscad`）

```python
import moz_openscad as moz
```

**核心心智模型**：Python 侧**只拼 SCAD 源码**，不在这里做任何几何运算；
`.dimension` / `.export()` / `.render_png()` 这些访问才真正调引擎求值。
因此：

- 同一个 `Shape` 有**惰性求值缓存**：第一次访问 `.dimension` / `.measure` / `.export()` / `.triangles()`
  等才真正求值，之后复用同一个几何句柄（改 `shape.variables` 会自动失效）。要跨多个 `Shape`
  复用同一份几何，仍可显式 `.eval()` 成 `Geometry`。
- **不要做「等价简化」**。例如把 `union(a, b)` 改写成「反正一样」的另一种写法、
  把 `difference` 的层数压平、给 `linear_extrude` 补默认参数，都可能改变最终的网格
  （原因见 [scad-semantics.md](scad-semantics.md)）。

---

## 1. 形状原语

| 调用 | 生成的 SCAD |
| --- | --- |
| `moz.cube(size=[1,1,1], center=False)` | `cube(size = [...], center = ...)` |
| `moz.sphere(r=1, d=None, fn=None, fa=None, fs=None)` | `sphere(r = ...)` |
| `moz.cylinder(h=1, r=None, r1=None, r2=None, d=None, d1=None, d2=None, center=False, fn=None, fa=None, fs=None)` | `cylinder(...)` |
| `moz.circle(r=1, d=None, fn=None, fa=None, fs=None)` | `circle(r = ...)` |
| `moz.square(size=[1,1], center=False)` | `square(size = [...], center = ...)` |
| `moz.polygon(points, paths=None)` | `polygon(points = [...], paths = [...])` |
| `moz.text(value, size=10, font=None, halign=None, valign=None, spacing=1, direction=None, fn=None, fa=None, fs=None)` | `text("...", size = ...)` |
| `moz.polyhedron(points, faces=None, triangles=None, convexity=None)` | `polyhedron(points = [...], faces/triangles = [...])` |
| `moz.import_shape(file, layer=None, origin=None, scale=None, convexity=None)` | `import(file = "...", layer = ...)` |
| `moz.surface(file, center=False, convexity=None, invert=False)` | `surface(file = "...", center = ...)` |

`text()` 是 2D 的，要立体请自己套 `linear_extrude`。

## 2. 布尔与变换

| 调用 | 说明 |
| --- | --- |
| `moz.union(*items)` / `moz.difference(*items)` / `moz.intersection(*items)` | 布尔运算，第一个操作数是主体 |
| `moz.hull(*items)` / `moz.minkowski(*items)` | 凸包 / 闵可夫斯基和 |
| `moz.translate(vector, obj)` / `moz.scale(vector, obj)` / `moz.mirror(vector, obj)` | 平移 / 缩放 / 镜像 |
| `moz.rotate(a, v=None, obj=None)` | `a` 与 SCAD 一样是**角度**（度）；`v` 是旋转轴 |
| `moz.multmatrix(matrix, obj)` | 4×4 矩阵变换 |
| `moz.color(obj, name, alpha=None)` | 颜色名或 `[r, g, b]`（0~1）；`alpha` 可给透明度 |
| `moz.projection(obj, cut=False)` | 投影（`cut=True` 取 Z=0 剖面） |
| `moz.section(obj, normal=UP, through=(0,0,0), up=UP)` | 任意点法平面的**截面**（2D；等价于「平面 ∩ 实体」，内部结构如实切出） |
| `moz.outline(obj, normal=UP, up=UP)` | 沿任意视线方向的**轮廓投影**（2D，不切） |
| `moz.view_basis(normal, up=UP)` | 视图三轴 `(x, y, z)`；方向常量 `UP/DOWN/FRONT/BACK/LEFT/RIGHT` |
| `moz.linear_extrude(obj, height, center=False, scale=None, twist=None, slices=None, convexity=None, fn=None, fa=None, fs=None)` | 2D → 3D |
| `moz.rotate_extrude(obj, angle=360, convexity=None, fn=None, fa=None, fs=None)` | 绕 Z 轴旋转成型 |
| `moz.offset(obj, r=None, delta=None, chamfer=None, fn=None, fa=None, fs=None)` | `r` 是**圆角**外扩/内缩，`delta` 是**尖角**外扩/内缩 |

要点：

- `linear_extrude` / `offset` **只写出你真正传了的参数**。原 `.scad` 不写 `slices` 时由引擎推导，
  硬补一个 `slices = 20` 会凭空多出 20 层切片、改变网格。
- `offset(10)` 在 SCAD 里是 `r = 10`（圆角），不是 `delta`；两种语义的几何完全不同
  （方 50 的方块：`r=10` 得 172 面，`delta=10` 得 12 面）。
- `cylinder(h, N)` 的第二个位置参数是 `r1`，`r2` 不给时引擎按 1 处理——所以那是**圆台**。
  要圆柱请写 `cylinder(h=..., r=...)`。

## 3. `$fn` / `$fa` / `$fs`：优先具名参数

```python
moz.sphere(r=5, fn=64)                     # -> sphere(r = 5, $fn = 64)
moz.rotate_extrude(moz.square(2), fn=80)   # -> rotate_extrude(angle = 360, $fn = 80) square(...)
moz.text("J", fn=16)                       # 字形曲线细分
```

块作用域的写法 `moz.settings(shape, fn=40)` 生成 `{ $fn = 40; <shape> }`，它有两个特点：

1. **块里的 `$fn` 会泄漏给同一子对象列表中后面的兄弟对象**：
   `union(){ { $fn=8; cylinder(); } sphere(); }` 里的 `sphere` 也变成 8 段。
2. 当原 `.scad` 就是**文件级/模块级赋值**（例如 `offset.scad` 的 `$fn = 40;`、
   `GEB.scad` 的 `$fn = 64;`）时，用它包住整个模型才是对应写法。

结论：只影响单个对象 → 具名参数；对应原文件的顶层赋值 → `settings()` 包整体。

## 4. 取值通道（拿引擎算出来的数）

```python
moz.value("1/3")                                     # '0.33333333333333331'（17 位有效数字）
moz.number("sqrt(2)")                                # 1.4142135623730951
moz.vector("rands(0, 1, 1000, 18)")                  # 1000 个浮点（与引擎逐比特一致）
moz.value('dxf_dim(file = "/abs/x.dxf", name = "bodywidth")')   # '22'
moz.vector("8bit_polyfont()[2]", "use </abs/MCAD/fonts.scad>\n") # 引用库里的函数/变量
```

- 表达式在 `source` 的顶层作用域里求值，因此能直接用它定义的变量与 `function`。
- **不能用 `echo()` 拿数**：`echo()` / `str()` 打印数字只保留 6 位有效数字，`1/3` 会退化成
  `0.333333`；本通道用注册内置函数取原值，按 17 位有效数字输出。
- 表达式算不出来时（未知函数、参数类型不对）抛 `OpenSCADError`，消息里是引擎原文，
  不会静默返回 `'undef'`。

## 5. 与引擎逐比特一致的角度三角函数

SCAD 的三角函数以**度**为单位，而且 OpenSCAD 用的是 `src/degree_trig.cc` 的专用实现
（30/45/60/90 直接给精确常量，反三角在结果接近整数时取整）。用 `math.radians` 会差末位，
进而让网格出现字节差异。所以请用：

```python
moz.sin_deg(x)  moz.cos_deg(x)  moz.tan_deg(x)
moz.asin_deg(x) moz.acos_deg(x) moz.atan_deg(x)  moz.atan2_deg(y, x)
```

`atan2_deg(y, x)` 的参数顺序与 SCAD 的 `atan2(y, x)` 一致。另外 `moz.lookup(key, pairs)`
按 SCAD 内建 `lookup()` 的算式复刻（`high_v * f + low_v * (1 - f)`，含端点回退），逐比特一致。

## 6. `Geometry`：一次求值的产物

```python
g = moz.eval_text("cube([10,20,30]);", side=5)   # 关键字参数 = -D 参数
g.dimension          # 上游语义：3 / 2；空几何仍是 3
g.is_empty           # 是否空几何（判断「有没有东西」用这个）
m = g.measure        # 几何测量快照：bbox / volume / area / facets / vertices / centroid（见 §12）
g.export("binstl", "out.stl")
data = g.export_bytes("3mf")
png  = g.render_png_bytes(400, 300, colorscheme="Tomorrow")
colors = g.face_colors()      # 4 字节/面（RGBA）；顺序与 export_bytes("binstl")/triangles() 一一对应
colors = g.face_colors("Tomorrow")   # 指定配色（未着色对象取该配色的材质色）
tris   = g.triangles()        # array('f')：每 9 个 float 一个三角面（直取网格，免于解析 STL）
g.log                         # echo + 警告（与 OpenSCAD 控制台文本一致）
g.take_log()                  # 同上，读取后清空
g.show()                      # 打开预览器（同 Shape.show()）
g.close()                     # 也可用 with 语句
```

`SHAPE` 与 `GEOMETRY` 的关系：`Shape.export()` / `.dimension` 等内部都是
`self._geometry()`（首次求值后缓存）再委托给 `Geometry`。

`Shape` 还提供 `source`（拼出来的 SCAD 源码）、`eval(**variables)`（显式求值成 `Geometry`）、
`show()`（打开预览器）、以及同名的方法式写法 `shape.union(...)` / `shape.translate(...)` /
`shape.linear_extrude(...)` 等。

`moz.eval_file(path, **variables)` 按**绝对路径**求值，所以示例里引用同目录的
`.dxf`/`.stl`/`.dat` 能正常解析。

## 7. 渲染选项

```python
g.render_png_bytes(800, 600)                              # 默认 preview 路径（保留 color()）
g.render_png_bytes(800, 600, renderer="cgal")             # 上游 --render=cgal（无颜色）
g.render_png_bytes(800, 600, colorscheme="Starnight")     # 配色方案（来自 color-schemes/*.json）
g.render_png_bytes(800, 600, edges=True, axes=True)       # 显示边 / 坐标轴
g.render_png("out.png", 0, 0)                             # 宽高给 0 = 用库默认（512×512）
g.render_png_bytes(800, 600, vpr=[55, 0, 25], vpt=[0, 0, 0], vpd=200)   # 相机覆盖
g.render_png_bytes(800, 600, projection="ortho")          # 正交投影
```

可选项（`_render_options`）：`renderer`（`"opencsg"` / `"throwntogether"` / `"cgal"`）、
`colorscheme`、`faces`、`edges`、`axes`、`scales`、`crosshairs`、`vpr`/`vpt`/`vpd`/`vpf`、
`projection`（`"perspective"` 默认 / `"ortho"`）。

**相机覆盖**：给了 `vpr`/`vpt`/`vpd`/`vpf` 任意一个就忽略模型里的 `$vp*`、也不自动取景，
此时**必须给 `vpd`**（相机距离，模型单位）；`vpr` 是旋转角（度）、`vpt` 是目标点、
`vpf` 是视场角（度）。`projection` 可单独给（不触发相机覆盖）。

⚠️ `colorscheme` 切换的是**全局**配色（对应上游 `set_render_color_scheme`），会影响后续的
渲染/`face_colors()` 调用——需要多套配色并存时，自己记下并在用完切回。

模型里的 `$vpr` / `$vpt` / `$vpd` / `$vpf` 会影响相机（例如 `Basics/logo_and_text.scad`
用它固定视角）；我们复刻时可以直接写进源码：

```python
return moz.settings(model, **{"$vpr": [90, 0, 0], "$vpt": [300, 0, 80], "$vpd": 1600})
```

## 8. 日志

`echo()`、警告（含「未知函数」「参数类型不对」这类）都进日志，与 OpenSCAD 控制台同格式：

```python
g = moz.eval_file("Functions/echo.scad")
print(g.log)        # ECHO: "f1: ", 3, 5 ...
```

`moz.dump(src, "echo")` 只回 echo 文本行。`moz.dump(src, "ast", docname="/abs/x.scad")`
可指定文档名（影响 ast/csg 里显示的路径；不传用 `<stdin>`）。

## 9. 预览器

```python
shape.show(title="moz - demo", width=900, height=650)      # 静态几何（Shape / Geometry / Part）
moz.show_animation(lambda i: build(i / 24), frames=24, fps=12)   # 在窗口里播放动画
```

3D 用 PySide6 的 `QOpenGLWidget` 自绘（逐面颜色来自 `color()`）、2D 用 `QGraphicsView` 显示 SVG、
空几何显示「空几何」。

窗口带菜单栏：**文件**（导出当前帧 STL / 引擎渲染 PNG / 视图截图 / 导出整个视图序列 PNG）、
**视图**（重置视角、视角预设、正交投影、显示坐标轴、显示地面网格、配色方案）、
**动画**（播放/暂停、逐帧、循环；静态几何下禁用）、**帮助**（关于）。快捷键：`Space` 播放/暂停、
`←`/`→` 逐帧、`Home` 重置视角。预览器跟随 **OpenSCAD 的 Z-up**（屏幕上方是 +Z）。
动画模式下窗口底部还有**帧滑块 + 播放速度**工具条。

2D 几何是**可交互**的：滚轮缩放、左键拖动平移、双击（或 `Home`）适应窗口。
视图菜单还能开坐标轴 / 地面网格 / 边线（wireframe）；**左键单击**会做点选测量
（状态栏给出世界坐标、距原点距离、面号）。

「导出当前帧 PNG（引擎渲染）」会把窗口视角换算成引擎相机（`engine_camera()` → `$vpr/$vpt/$vpd/$vpf`
+ 投影方式），所以导出的图与所见一致；「导出整个视图序列 PNG」直接抓 GL 画面，
「导出动画 GIF…」用 Pillow（可选依赖）编码。

```python
moz.show_parts({"底板": base, "立柱": post})   # 多部件：右侧列表可隐藏部件，点选报告部件名
```

`show_animation` 打开窗口时一次性预计算全部帧（各帧共用同一套居中/缩放，模型才是「动」而不是抖动），
播放用定时器换缓冲。细节见 [viewer.md](viewer.md)。

## 9b. 2D 工程图

`moz.section()` / `moz.outline()` 出来的 2D 形状可以直接交给制图层排版并导出图纸：

```python
import moz_drawing as dw

drawing = dw.Drawing(size="A3", landscape=True, title="支座", number="MZ-001")
front = drawing.add_view("front", moz.outline(part, moz.FRONT), at=(85, 175), scale=1.5)
drawing.add_view("A-A", moz.section(part, moz.UP), at=(265, 110), scale=1.5, hatched=True)
drawing.dim(front, "linear", (-30, -10), (30, -10), offset=-12)   # 坐标按**视图坐标**给
drawing.fits()                       # 版式自查：内容是否都在图框内
drawing.export("pdf", "bracket.pdf")  # 也可 svg / dxf
```

视图摆放/比例、剖面线、中心线、线性/直径/半径标注、图框标题栏、已知限制见 [drawing.md](drawing.md)；
可运行示例 `PYTHONPATH=py python3 py/drawing_demo.py`。

图纸上的文字默认用随包分发的 `Moz Sans SC`（`moz_drawing.TEXT_FONT`）；换字体传
`font="<fontconfig 家族名>"`（`Drawing(font=)` / `add_note(..., font=)` / `dim(..., font=)`），
传 `font=""` 退回引擎默认字体（只有拉丁字形，中文会静默变成空心方框）。

## 10. 数据目录与库路径

运行时数据（配色方案、字体、MCAD 库、示例数据）随包分发在 `moz_data/` 下：

```python
moz.DATA_DIR                              # 该目录（装在 site-packages 里或仓库中）
moz.data_path("examples", "Old", "example007.dxf")   # 取外部数据文件的绝对路径
```

import 时会自动：把 `moz_data` 设为资源目录（`MOZ_OPENSCAD_RESOURCE_DIR`）、把 `moz_data/fonts`
追加进 `OPENSCAD_FONT_PATH`、把 `moz_data/lib` 纳入 `.so` 搜索。`.so` 搜索顺序：
`MOZ_OPENSCAD_LIB` → 模块同目录 → `../build/lib/` → `moz_data/lib/`。详见 [build.md](build.md)。

## 11. `Part` 与便利类（早期对象模型）

`moz.Part` 以及 `moz.Box` / `moz.Cylinder` / `moz.Sphere` / `moz.Hole` / `moz.Plate` /
`moz.Bracket` 是更「面向对象」的一层包装（`Part.at()/move()/add()/cut()`、`+`/`-` 运算符），
最终仍然落回 `Shape`。示例统一使用函数式 API；便利类适合快速搭常见零件。

```python
bracket = moz.Bracket(width=40, height=60, thickness=6, hole_diameter=4, hole_positions=[(10, 10)])
```

## 12. 几何测量：`Geometry.measure`

```python
m = g.measure          # 返回 Measure 快照（纯 Python 值，句柄释放后仍可用）
m.dimension            # 3 / 2
m.is_empty             # 是否空几何
m.bbox                 # ((minx,miny,minz), (maxx,maxy,maxz))；空几何为 nan
m.bbox_min, m.bbox_max # 同上，分开取
m.volume               # 3D 体积；2D 为 nan
m.area                 # 3D 表面积；2D 面积
m.facets               # 3D 三角面数；2D 轮廓顶点数
m.vertices             # 去重顶点数
m.centroid             # (x, y, z)：3D 体积质心 / 2D 面积质心；空几何为 nan
```

3D 用与 `export_bytes("binstl")` **同一条三角化路径**的网格（口径与导出一致），
2D 用多边形轮廓（鞋带公式 + 面积质心）。空几何的 `volume`/`area` 为 0，
`bbox`/`centroid` 为 `nan`。`Shape.measure` / `Part.measure` 同理（同一 `Shape` 只求值一次，见开头的心智模型）。

网格直取（免于解析 STL 字节）：

```python
tris = g.triangles()          # array('f')，每 9 个 float 一个三角面（3 顶点，世界坐标）
# numpy 用法：np.frombuffer(g.triangles(), dtype=np.float32).reshape(-1, 3)
```

几何查询（与 measure/triangles/face_colors 共用同一次三角化）：

```python
g.contains_point(0, 0, 0)        # 点是否在实体内（2D/空几何恒 False；表面点不保证）
g.distance_to_surface(6, 0, 0)   # 点到表面的最短距离；2D/空几何抛 OpenSCADError
g.inertia()                      # 3×3 惯性张量（单位密度、关于质心）；2D/空几何抛错
```

```python
moz.eval_text("difference() { cube(20, center=true); sphere(12); }").measure.volume
```

## 13. 动画帧：`moz.eval_animation`

对应上游 `--animate N`：逐帧把 `$t = frame / fps` 传给模型并回调。

```python
def render_frame(frame, geometry):     # geometry 只在本次回调期间有效
    geometry.export("binstl", f"/tmp/frame{frame:03d}.stl")

frames = moz.eval_animation(source, 30, 10.0, callback=render_frame)   # 30 帧, 10fps
frames = moz.eval_animation("", 30, 10.0, callback=render_frame, path="model.scad")  # 按文件
```

- `callback(frame, geometry)` 每帧调用一次；`geometry` **只在回调期间有效**（回调返回后引擎
  立即释放它），之后再访问会抛 `OpenSCADError`。回调里可以照常 `export`/`render_png`/`measure`。
- callback 返回非 0 时提前中止；返回**已完成的帧数**。
- `$t` 由本函数逐帧注入，不要在 `variables` 里再给；其余 `variables` 仍是 `-D` 参数。
- 回调抛出的 Python 异常会被原样重新抛出。

## 14. 库搜索路径

```python
moz.add_library_path("/path/to/libs")   # 追加到 use <...> / import 的搜索列表
moz.library_paths()                     # 当前列表（含 OPENSCADPATH、用户库目录、资源 libraries）
```

## 15. 导出选项

```python
g.export("pdf", "out.pdf", source_file_name="part.scad", source_file_path="/abs/part.scad")
g.export_bytes("svg", source_file_name="part.scad")
```

`source_file_name` / `source_file_path` 覆盖 `ExportInfo` 里 PDF 用的源文档信息。
**OpenSCAD 2021.01 没有更多导出开关**（3MF 无元数据/单位、AMF 单位与 producer 元数据硬编码、
STL 无单位/精度参数），所以这是 C ABI 能透出的全部导出选项。

## 16. 图纸 → 模型（`moz_dxf`，P1）

反向的那条链路：把一张 DXF 单视图图纸读成可改参数/可测量的模型。链路与验收见 [2d-to-3d.md](2d-to-3d.md)。
需要可选依赖：`pip install "moz-openscad[dxf]"`（或 `pip install ezdxf`，MIT）。

```python
import moz_dxf

drawing = moz_dxf.read_dxf("板框.dxf")           # 解析 + 修复，返回 Drawing
print(drawing.report())                           # 解析/修复报告（不静默修补，逐项列计数）
drawing.outlines, drawing.holes, drawing.repairs  # 轮廓 / 孔 / 修复计数
drawing.parameters()                              # {'bodywidth': 120.0, 'plateheight': 40.0}

part = drawing.extrude(height=6.0)                # 外轮廓 - 孔（奇偶规则）
part.measure.volume                               # 体积；也能 export("binstl", ...) / show()

moz_dxf.extrude("板框.dxf", 6.0, layers=("OUTLINE",))   # 便捷入口（可用 layers= 只要某层）
moz_dxf.parameters("板框.dxf")                          # 命名标注 → {名字: 值}
moz_dxf.report("板框.dxf")                              # 只要报告
```

要点：

- **图层语义**：匹配到中心线/虚线/标注/构造线角色的图层不参与几何；**没匹配上的图层（含 `0` 层）
  按轮廓处理**——真实图纸大多不给图层起有语义的名字。`layers=` 只收指定图层，`hole_layers=` 强制当孔，
  `exclude_layers=` 直接排除。
- **与引擎 `import()` 语义对齐**（实测出来的规则）：画断的链默认**隐式闭合**（`open_chains="close"`，
  严格模式 `"report"`）；成环顺序照引擎（先开口链、再闭合链、每步取编号最小的段）；填充用**奇偶规则**
  （重叠区域会被挖掉、嵌套层级自动处理）。全直线段图纸与原生 `import()` 的体积**逐位一致**。
- **修复只报告不静默**：重复段去重、零长丢弃、隐式闭合（含缺口大小）、共线点合并、交叉节点、自交诊断
  都记在 `drawing.repairs` / `drawing.warnings` 里。端点吸附（`snap_tolerance`）只用于拓扑判断，
  **不动输出坐标**。
- **单位**：默认按 `$INSUNITS` 换算到 mm，但**非 1 倍换算一定告警**（这个头字段常是模板默认值——
  ezdxf 新建文件默认就是 6=米，照它换算会放大 1000 倍）；`unit_policy="as-drawn"` 按原始数值
  （与引擎一致），`unit_scale=` 直接指定。
- **标注 ↔ 引擎一致**：名字取 DIMENSION 的 group 1（文字覆盖），与 `dxf_dim(file, name)` 认的是同一列；
  圆孔按弦高离散（`arc_chord_tolerance`，默认 0.01 mm）。
- 已知边界：互相交叉/重叠的线不做平面细分（引擎也不做），成环顺序不同时面积可能差 ~10%。
- 命令行演示：`PYTHONPATH=py python3 py/dxf_demo.py 图纸.dxf --height 6 --export-stl out.stl --drawing out.pdf`
  （`--drawing` 会把模型再画回一张 A4 图，即"图纸 ⇄ 模型"闭环）。
- 语料回归：`PYTHONPATH=py python3 py/verify_dxf.py [额外的.dxf ...]`。