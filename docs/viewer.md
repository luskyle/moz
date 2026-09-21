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
| 2D 几何 | `QGraphicsView` 显示导出的 SVG：滚轮缩放、左键拖动平移、双击（或 `Home`）适应窗口 |
| 空几何 | 显示「空几何」文字（**判空必须先于判维度**：上游语义下空几何的 `dimension` 仍是 3） |

## 菜单

| 菜单 | 项（快捷键） |
| --- | --- |
| 文件 | 导出当前帧 STL… (`Ctrl+S`) · 导出当前帧 PNG（引擎渲染）… (`Ctrl+E`) · 保存视图截图… (`Ctrl+Shift+S`) · 导出整个视图序列 PNG…（按当前视角） · 退出 (`Ctrl+Q`) |
| 视图 | 重置视角 (`Home`) · 视角预设（前视图 / 右视图 / 俯视图 / 等轴测） · 正交投影（勾选切换） · 显示坐标轴 · 显示地面网格（Z=0） · 配色方案（默认 + `color-schemes/render/*.json` 里的全部） |
| 动画 | 播放/暂停 (`Space`) · 上一帧 (`←`) · 下一帧 (`→`) · 回到首帧 (`Ctrl+Home`) · 循环播放（勾选） |
| 帮助 | 关于 moz viewer |

- 「导出 STL / PNG（引擎渲染）」走**引擎**：静态用原始几何、动画用 `frame_fn(当前帧)` 重新求值一次，
  所以导出的是精确几何（PNG 保留 `color()`）。引擎 PNG 的相机由 `Interactive3D.engine_camera()`
  从窗口视角换算而来（`$vpr/$vpt/$vpd/$vpf` + 投影方式），**与所见一致**。
- 「保存视图截图」与「导出整个视图序列 PNG」走 **GL 截图**，画面与你在窗口里看到的当前视角一致
  （后者会逐帧切帧再抓图，动画序列因此和播放时所见相同）。
- 「配色方案」切换的是**全局**配色（上游语义）；动画下要逐帧重新取色，帧多时会慢。
- 动画菜单在**静态几何**下自动禁用。

### 叠加层（坐标轴 / 地面网格）

视图菜单里可开关两组线框（单独的线框着色器 + 顶点缓冲，和网格各画一遍）：

- **坐标轴**：X 红 / Y 绿 / Z 蓝，从原点向两侧各画半条（归一化空间里长 1.25，即模型半径的 1.25 倍）。
- **地面网格**：铺在 **Z=0 平面**上（因为预览器是 Z-up），步长 0.25、范围 ±1.25。

线框和实体一起参与深度测试，所以被模型挡住的部分会被正确遮挡（不是永远浮在最上层）。

### 窗口视角 → 引擎相机

预览器是 `lookAt(eye, target, +Z)`（roll-free），上游是 `R = Rx(rx)·Ry(ry)·Rz(rz)` 后从
`(0, -dist, 0)` 用 `+Z` 观察。两者的旋转部分相等即可精确对齐：

```
R = Lᵀ · M_lookAt          # L 是上游那次 lookAt 的旋转部分
vpr = (90 - rx, -ry, -rz)  # 见 Camera::setVpr
```

`vpt` 取目标点、`vpd` 取 `半径 × 视角距离`（预览器把网格归一化到单位半径，引擎渲染原始模型），
`vpf` 透视取 45°、正交取 `2·atan(0.55)`（与 `_projection` 的 `half = distance*0.55` 对齐）。
实测轮廓高宽比：默认视角 2.547(GL) vs 2.535(引擎)，前视 4.010 vs 4.000（前视精确对应 `vpr=[90,0,0]`）。

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

- 打开窗口时**一次性预计算**全部帧的网格，之后播放/逐帧不再求值。预计算带**进度对话框且可取消**
  （大模型 × 多帧时不必干等；取消后若已算出部分帧，就用这部分显示）。
- 各帧共用**同一套** center/radius（取所有帧包围盒的并集）再居中/缩放——否则每帧会被独立
  重新居中，看起来模型「原地抖动」而不是运动。**这也是不做「按需求值 + LRU」的原因**：
  取景前必须知道全部帧的包围盒。
- 播放用 `QTimer`（间隔 `1000/fps` ms）换顶点缓冲；「循环」关闭时到末帧自动停。
- 窗口底部有**动画工具条**（帧滑块 + 播放速度，静态几何下隐藏）：拖滑块会暂停播放并跳到该帧；
  改速度会立刻改定时器间隔。
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