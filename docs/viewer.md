# 预览器

`py/moz_viewer.py`，基于 PySide6（`QOpenGLWidget` + `QSvgWidget`）。

```bash
PYTHONPATH=py python3 py/moz_viewer.py py/examples/Basics/CSG.py   # 给一个暴露 build() 的文件
PYTHONPATH=py python3 py/examples/Basics/CSG.py                    # 或者示例自己的 __main__
```

Python 里的入口是 `Shape.show(title=..., width=..., height=...)`。

## 行为

| 情况 | 视图 |
| --- | --- |
| 3D 几何 | OpenGL 网格：左键旋转、右键平移、滚轮缩放 |
| 2D 几何 | `QSvgWidget` 显示导出的 SVG 矢量图 |
| 空几何 | 显示「空几何」文字（**判空必须先于判维度**：上游语义下空几何的 `dimension` 仍是 3） |

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
app = QApplication([])
w = Interactive3D(shape); w.resize(360, 260); w.show()
for _ in range(6): app.processEvents()
img = w.grabFramebuffer(); img.save("/tmp/view.png")     # 抓帧后统计像素颜色即可确认上色生效
```

## 依赖与限制

- 需要 `numpy` 与 `PySide6`（见 `pyproject.toml`）；3D 视图需要可用的 OpenGL 上下文。
- 预览器读的是 **STL 网格**（`export_bytes("binstl")`），因此显示的是**求值后的实体**，
  不是 CSG 预览：`%` 背景对象、`#` 高亮都不显示。
- 每次构造/重载都会重新求值（Python 侧不缓存几何），大模型上「求值」才是耗时大头
  （实测 1.3~31.6 s，而导出 STL + 逐面颜色只要 0.08~1.13 s）。