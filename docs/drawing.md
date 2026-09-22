# 截面与 2D 工程图

两个能力：

1. **截面 / 轮廓投影**（`moz.section` / `moz.outline` / `moz.view_basis`）——把实体沿任意视线方向切开或投影成 2D 形状；
2. **制图层**（`py/moz_drawing.py`）——把这些 2D 形状排成一张图，加尺寸标注、剖面线、中心线、图框与标题栏，导出 SVG/DXF/PDF。

这一层是**纯 Python 组合 SCAD 的 2D 几何**，不需要改 C++、也不需要重新构建库。

## 一、截面与投影

```python
import moz_openscad as moz

part = moz.difference(moz.cube([60, 40, 20], center=True), moz.cylinder(r=8, h=40, center=True, fn=64))

moz.section(part, moz.UP)                      # 过原点、法线 +Z 的截面（2D）
moz.section(part, moz.FRONT, through=(0, 0, 5))# 点法平面：过 (0,0,5)、法线 -Y
moz.outline(part, moz.FRONT)                   # 前视轮廓（不切，整体投影）
moz.view_basis(moz.FRONT)                      # -> (x, y, z) 视图三轴
```

**实现原理**：OpenSCAD 的 `projection(cut = true)` 就是「在 z = 0 处沿 -z 切一刀」，
所以任意平面的截面 = 用刚体变换把该平面搬到 z = 0，再 `projection(cut = true)`。
变换用 `multmatrix` 给出（不用 `rotate(a, v)` 的轴角形式，避免法线趋近 ±Z 时旋转轴退化）。
因此 `section()` 与「平面 ∩ 实体」等价：

- 平面没穿过实体 → 空几何（`is_empty` 为真；注意空截面的 `dimension` 是上游语义的 3）；
- 内部结构会被如实切出来（例如带中心孔的零件截面是外框 + 内孔两个环）；
- 数值精度：与解析解相比，轴对齐/方体情形完全一致，斜平面 ~5e-7、曲线体 ~8e-8 的相对误差（CGAL 求交与投影的算术误差），轮廓投影路径略大 ~2e-6。

### 视图约定

`view_basis(normal, up=UP)` 返回视图三轴 `(x, y, z)`：

- `z` = 归一化后的**视线方向**，指向观察者（所以 `moz.UP` 表示观察者在 +Z、`moz.FRONT` 表示观察者在 -Y）；
- `x` = 视图向右，`y` = 视图向上，三者构成右手系（`x × y = z`）；
- `normal` 与 `up` 平行时自动换参考方向：趋近 ±Z 用 +Y（俯视图的常规约定），趋近 ±Y 用 +X。

标准方向常量：`UP / DOWN / FRONT / BACK / LEFT / RIGHT`。几个实测结果：

| 调用                  | x（右） | y（上） | z（视线） |
| --------------------- | ------- | ------- | --------- |
| `view_basis(UP)`    | +X      | +Y      | +Z        |
| `view_basis(FRONT)` | +X      | +Z      | -Y        |
| `view_basis(RIGHT)` | +Y      | +Z      | +X        |

标注换算需要这个基：视图坐标 `(u, v)` 对应模型点 `u * x + v * y + through`。

## 二、制图层

```python
import moz_drawing as dw

drawing = dw.Drawing(size="A3", landscape=True, margin=12,
                     title="支座", number="MZ-DEMO-01", material="Q235",
                     author="luskyle", date="2026-09-22", scale_note="1.5:1")

front = drawing.add_view("front", moz.outline(part, moz.FRONT), at=(85, 175), scale=1.5,
                         label="主视图")
sectioned = drawing.add_view("A-A", moz.section(part, moz.UP), at=(265, 110), scale=1.5,
                             label="A—A 剖视", hatched=True)

drawing.dim(front, "linear", (-30, -10), (30, -10), offset=-12)   # 坐标是**视图坐标**
drawing.dim(sectioned, "diameter", (0, 0), 8, angle=35)           # -> ⌀16
drawing.add_centerline((60, 110), (90, 110))
drawing.add_note((25, 42), "技术要求：")

print(drawing.fits())            # 版式自查：内容是否都在图框内
drawing.export("pdf", "bracket.pdf")      # 也可 svg / dxf
drawing.show()                   # 用预览器的 2D 视图看（可缩放/平移）
```

完整可运行示例：`PYTHONPATH=py python3 py/drawing_demo.py`（产物在 `build/out/drawing/`）。

### 图面与视图

- 图纸尺寸用 ISO A 系列名字（`A4`…`A0`）或自定义 `(宽, 高)`；`landscape=True` 横向。
  图面坐标 = SCAD 的 XY 平面、单位 mm、+Y 向上（导出 SVG 时 y 轴翻转由引擎处理）。
- `add_view(name, shape, at, scale=, label=, hatched=)`：`shape` 一般是 `section()` / `outline()` 的结果；
  `scale` 只缩放该视图；`hatched=True` 自动加剖面线。
- `View.to_sheet(point)` 把视图坐标换成图面坐标，`Drawing.dim(view, ...)` 内部就是用它——
  所以**标注坐标按视图坐标给**（和你在模型里量到的尺寸一致，不用自己乘比例）。
- `content_bbox()` / `fits(tolerance=)`：版式自查（内容出框时 `fits()` 为 False）。
  线宽会让贴边几何略微越界，惯例留一个线宽容差（`fits(tolerance=dw.THICK_WIDTH)`）。
- 文字字体：`Drawing(font=)` 定整张图，`add_note(..., font=)`、`add_view(..., label=)`、
  `dim(...)` 的文字都跟随它（也能单独覆盖）。默认 `TEXT_FONT = "Moz Sans SC"`——随包分发的
  中文字库子集；**不要**把字体退回引擎默认（`font=""`），它只有拉丁字形，中文会静默变成空心方框。
  传 `font="<fontconfig 家族名>"`（如 `"Noto Sans CJK SC"`）可换成系统字体。

### 标注图元

| 调用                                                                | 说明                                                                                                                      |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `line(p1, p2, width=)` / `polyline(points)`                     | 线段/折线（用扁矩形近似，2D 几何只有填充多边形没有描边）                                                                  |
| `arrow(tip, direction, length=3, width=1)`                        | 箭头（尖端在`tip`，箭身朝 `direction` 的反方向展开）                                                                  |
| `dim_linear(p1, p2, offset=10, text=None, ...)`                   | 线性尺寸：`offset` 为正时尺寸线落在 `p1→p2` 的**左侧**；文字自动取实测长度并**平行于尺寸线**（不会倒读） |
| `dim_diameter(center, radius, angle=45)` / `dim_radius(...)`    | ⌀ / R 标注，带引线与箭头（箭头在圆内一侧）                                                                               |
| `centerline(p1, p2, extension=2)`                                 | 点划线中心线，长划 4 / 间隙 1.5，**两端以长划收尾**，两端各伸出 `extension`                                       |
| `hatch(shape, spacing=3, angle=45)`                               | 剖面线：平行细线与截面求交（空形状原样返回）                                                                              |
| `text_at(anchor, content, size=3.5, halign=, valign=, rotation=, font=)` | 定位文字；`font` 默认用自带中文字库 `TEXT_FONT`（`font=""` 退回引擎默认字体，只有拉丁字形） |

`Drawing.title_block()` 在图框右下角画标题栏（字段见表头 `fields`），`Drawing.border()` 画图框。

### 导出与查看

- `export(fmt, path)` / `export_bytes(fmt)`：`svg` / `dxf` / `pdf`（图面是 2D，导出 3D 格式会被引擎拒绝）。
- `show()`：走预览器的 2D 视图（`QGraphicsView`，滚轮缩放、拖动平移、双击适应窗口）。

## 三、已知限制

- **不自动布图**：视图位置、比例、投影对齐关系要自己给；没有「自动三视图布局」「第一角/第三角切换」。
- **没有隐藏线与剖视符号**：看不到虚线（被遮挡的轮廓不会自动用虚线画），剖切位置符号/箭头要自己用 `line()`/`arrow()` 拼。
- **没有 GD&T / 公差 / 粗糙度**：只有线性、直径、半径三种尺寸与文字说明；没有形位公差框、配合代号、表面粗糙度符号、基准符号。
- **单页**：一次导出就是一张图；多页/图纸集要自己在外面组织。
- **线是填充矩形**：SVG/DXF 里线段是极扁的多边形（0.25 mm ≈ ISO 细线），不是矢量描边；对下游 CAM/DXF 处理一般够用，但如果你需要真正的线实体，得在导出后处理。
- **文字用引擎的字体**：`text_at` 走 `moz.text()`，字体由 fontconfig 家族名决定，默认是自带的
  `Moz Sans SC`（GB2312 6763 字 + ASCII/拉丁/常用符号）；生僻字不在子集里会缺字形，需要时传
  `font="Noto Sans CJK SC"` 之类换系统字体。没有专门的工程字库（长仿宋等是商业字体）。
- 逐面颜色/材质这类 3D 属性与这一层无关（图面是纯 2D 几何）。

## 四、测试

`py/tests/test_section.py`（截面/投影，含「平面与立方体棱求交」的解析对照）与
`py/tests/test_drawing.py`（图元几何、视图坐标换算、剖面线只在实体内部、三种导出的文件头）。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest py/tests/test_section.py py/tests/test_drawing.py -q
```
