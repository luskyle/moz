# 预览器

`py/moz_viewer.py`，基于 PySide6（`QOpenGLWidget` + `QSvgWidget`）。

```bash
PYTHONPATH=py python3 py/moz_viewer.py py/examples/Basics/CSG.py                 # 给一个暴露 build() 的文件
PYTHONPATH=py python3 py/moz_viewer.py py/examples/moz/animation.py --frames 24 --fps 12
PYTHONPATH=py python3 py/examples/Basics/CSG.py                                  # 或者示例自己的 __main__
```

Python 入口：

| 入口 | 作用 |
| --- | --- |
| `shape.show(title=..., width=..., height=...)` | 显示单个静态几何（`Shape.show` / `Geometry.show` / `Part.show`） |
| `moz.show_animation(frame_fn, frames, fps=8.0, ...)` | **在窗口里播放动画**：`frame_fn(i)` 返回第 i 帧的 Shape |

## 行为

| 情况 | 视图 |
| --- | --- |
| 3D 几何 | OpenGL 网格：左键旋转、右键平移、滚轮缩放 |
| 2D 几何 | `QSvgWidget` 显示导出的 SVG 矢量图 |
| 空几何 | 显示「空几何」文字（**判空必须先于判维度**：上游语义下空几何的 `dimension` 仍是 3） |

## 菜单

| 菜单 | 项（快捷键） |
| --- | --- |
| 文件 | 导出当前帧 STL… (`Ctrl+S`) · 导出当前帧 PNG（引擎渲染）… (`Ctrl+E`) · 保存视图截图… (`Ctrl+Shift+S`) · 导出整个视图序列 PNG…（按当前视角） · 退出 (`Ctrl+Q`) |
| 视图 | 重置视角 (`Home`) · 视角预设（前视图 / 右视图 / 俯视图 / 等轴测） · 正交投影（勾选切换） · 配色方案（默认 + `color-schemes/render/*.json` 里的全部） |
| 动画 | 播放/暂停 (`Space`) · 上一帧 (`←`) · 下一帧 (`→`) · 回到首帧 (`Ctrl+Home`) · 循环播放（勾选） |
| 帮助 | 关于 moz viewer |

- 「导出 STL/PNG（引擎渲染）」走**引擎**：静态用原始几何、动画用 `frame_fn(当前帧)` 重新求值一次，
  所以导出的是精确几何（PNG 保留 `color()`，相机按模型 `$vp*` 或自动取景）。
- 「保存视图截图」与「导出整个视图序列 PNG」走 **GL 截图**，画面与你在窗口里看到的当前视角一致
  （后者会逐帧切帧再抓图，动画序列因此和播放时所见相同）。
- 「配色方案」切换的是**全局**配色（上游语义）；动画下要逐帧重新取色，帧多时会慢。
- 动画菜单在**静态几何**下自动禁用。

## 坐标系与视角

预览器跟随 **OpenSCAD 的 Z-up**：屏幕上方是 +Z，`z = 0` 是"地面"。视角由 `yaw`（绕 Z 水平旋转）
与 `pitch`（仰角，夹在 ±89.5° 以避免与 up 向量平行）定义，默认 `(-60°, 30°)`；右键拖动是沿
**屏幕的右/上方向**平移目标点（不是世界 XY）。

| 预设 | yaw / pitch | 效果 |
| --- | --- | --- |
| 前视图 | -90° / 0° | 从 -Y 看向 +Y |
| 右视图 | 0° / 0° | 从 +X 看向 -X |
| 俯视图 | -90° / 89.5° | 从 +Z 向下看 |
| 等轴测 | -60° / 30° | 默认的立体视角 |

## 动画播放

```python
def frame_fn(i):
    return build(t=i / 24)          # 第 i 帧（t ∈ [0, 1)）

moz.show_animation(frame_fn, frames=24, fps=12)
```

- 打开窗口时**一次性预计算**全部帧的网格（状态栏显示进度），之后播放/逐帧不再求值。
- 各帧共用**同一套** center/radius（取所有帧包围盒的并集）再居中/缩放——否则每帧会被独立
  重新居中，看起来模型「原地抖动」而不是运动。
- 播放用 `QTimer`（间隔 `1000/fps` ms）换顶点缓冲；「循环」关闭时到末帧自动停。
- 逐帧求值想用于**批处理**（导出文件）请用 `moz.eval_animation`（见 [python-api.md](python-api.md) §13）；
  两个接口互补：一个用于看，一个用于跑。

## 颜色

3D 视图的顶点色来自 `Geometry.face_colors()`（与 `binstl` 的三角面一一对应，顺序严格对齐），
写入 GPU 的顶点缓冲时按 `position(0) / normal(12) / color(24)`、步长 36 字节交错排列；
着色器用顶点色做基础色，再叠加漫反射 + 边缘光 + 高光。

- 有 `color()` 的对象显示自己的颜色；未着色的对象用当前配色方案的材质色。
- 拿不到颜色数组时（旧库、非 3D）退回默认材质色，不会报错。
- 透明度（`color(..., alpha)`）目前不参与混合，按不透明显示。

拿不到显示器时也可以用离屏方式自测（本项目就是这么验证的）：

```python
from PySide6.QtWidgets import QApplication
import moz_viewer as viewer
app = QApplication([])
meshes = [viewer._mesh_from_shape(shape)]        # 单个静态帧；动画则传入多帧的 mesh 列表
w = viewer.Interactive3D(meshes); w.resize(360, 260); w.show()
for _ in range(6): app.processEvents()
img = w.grabFramebuffer(); img.save("/tmp/view.png")   # 抓帧后统计像素颜色即可确认上色生效
```

## 依赖与限制

- 需要 `numpy` 与 `PySide6`（见 `pyproject.toml`）；3D 视图需要可用的 OpenGL 上下文。
- 预览器读的是 **STL 网格**（`export_bytes("binstl")`），因此显示的是**求值后的实体**，
  不是 CSG 预览：`%` 背景对象、`#` 高亮都不显示。
- 动画**预计算**要逐帧求值，帧多/模型大时打开窗口会慢（状态栏会显示进度）；播放本身是即时的。
- 每次构造/重载都会重新求值（Python 侧不缓存几何），大模型上「求值」才是耗时大头
  （实测 1.3~31.6 s，而导出 STL + 逐面颜色只要 0.08~1.13 s）。