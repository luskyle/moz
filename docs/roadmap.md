# 路线与待办

本文件把「下一步要加/要优化什么」按优先级固定下来，作为后续执行的清单。
状态：`[ ]` 未做 · `[~]` 进行中 · `[x]` 已完成。

## 0. 已知的小问题（低成本、优先修）

- [x] `pyproject.toml` 的 `moz-demo = "demo:main"` 指向未打包的模块（`py-modules` 没列 `demo`），
      wheel 安装后 `moz-demo` 会因 `import demo` 失败 —— 把 `demo` 加进 `py-modules`。
- [x] viewer 每帧对同一个 `Shape` 调 `export_bytes` + `face_colors` → **2 次 CGAL 求值/帧**
      —— 见 §2 的 `Shape` 求值缓存（缓存后自动降为 1 次），并改用新的网格接口。
- [x] `Shape._geometry()` 每次访问都重新求值、没有缓存 —— 加惰性缓存（按 `variables` 快照失效）。
- [x] `docs/build.md` 的依赖清单补上 `cmake`/`g++`/`flex`/`bison`；环境描述更新为 24.04 / CGAL 5.6
      （`limitations.md` 同步）。

## 1. 工程化（目前最薄弱，收益最高）

- [x] **测试**：`py/tests/`（pytest，95 个用例），覆盖 measure/查询数值、eval/export 往返、取值通道、
      动画帧、库路径、网格/颜色、`Shape` 缓存、错误路径、viewer 逻辑（不 show 窗口）。
- [x] **CI**：`.github/workflows/ci.yml` —— 装依赖 → 构建 `.so` → `ruff check` → pytest → 48 示例保真度。
- [x] **打包**：**把 `.so` 与运行时数据一起打进平台 wheel**（`py3-none-linux_x86_64` 这种：
      纯 C ABI 的 `.so` 不需要 cp3xx 标签，但平台标签必须对上）。数据（配色方案、字体、MCAD 库、
      示例数据）复制到 `py/moz_data/`，由 `scripts/build_wheel.sh` 打包、`scripts/smoke_installed.py`
      在干净 venv 里验证；`.so` 仍依赖系统 CGAL/OpenCSG/Qt，见 [build.md](build.md)。
- [x] **lint/format**：`pyproject.toml` 加 `[tool.ruff]`（E/F/W/I/UP/B，排除 `3rd`/`build`/`py/examples`），
      `ruff check .` 已全绿，并接入 CI。

## 2. API 与性能

- [x] `moz_geom_triangles`：直取三角面顶点数组，viewer 不再解析 STL 字节。
- [x] `moz_geom_face_colors_ex`：给逐面颜色加 `colorscheme` 参数（GL 预览切换配色的前提）。
- [x] `Shape` 惰性求值缓存（按 `variables` 快照失效）。
- [x] **三角化缓存**：measure / triangles / face_colors / 几何查询共用一次三角化（缓存在句柄里）。
- [x] 动画预计算：改为**带进度且可取消**。不做「按需求值 + LRU」——取景前必须知道全部帧的包围盒，
      否则逐帧重新居中会抖动（见 [viewer.md](viewer.md)）。
- [x] 并发：**明确不做**（引擎的 parser/builtins/字体缓存/`RenderSettings` 都是进程级静态状态，
      改线程安全等于重写上游；服务化只能多进程）。理由记在 [limitations.md](limitations.md)。

## 3. 新 API（延续 C ABI 补全）

- [x] 相机覆盖：`moz_render_options` 增加 `has_camera`/`vpr`/`vpt`/`vpd`/`vpf`/`projection`，
      渲染不再只能靠模型里的 `$vpr`（Python：`render_png(..., vpr=..., vpd=..., projection="ortho")`）。
- [x] viewer 视角同步：`Interactive3D.engine_camera()` 把窗口视角精确换算成 `$vpr/$vpt/$vpd/$vpf`
      + 投影方式（`R = Lᵀ·M_lookAt` 反解欧拉角），引擎导出的 PNG 与所见一致（实测轮廓比 0.5% 内）。
- [x] 几何查询：点包含 `contains_point`、点到表面距离 `distance_to_surface`、惯性张量 `inertia`
      （凸包已有建模原语 `moz.hull`）。
- [x] 截面 `slice`（切平面 → 2D 轮廓）：`moz.section(obj, normal, through)` +
      `moz.outline(obj, normal)` + `moz.view_basis()`——用「刚体变换把平面搬到 z=0，再
      `projection(cut = true)`」实现，等价于平面 ∩ 实体，无需改 C++；解析对照见
      `py/tests/test_section.py`。详见 [drawing.md](drawing.md)。
- [x] **2D 制图层** `py/moz_drawing.py`：图框/标题栏、视图摆放与比例、剖面线、中心线、
      线性/直径/半径尺寸标注（文字随尺寸线旋转）、版式自查 `fits()`，导出 SVG/DXF/PDF；
      示例 `py/drawing_demo.py`，测试 `py/tests/test_drawing.py`。详见 [drawing.md](drawing.md)。
- [ ] 制图的进阶项：自动布图与投影对齐、隐藏线/虚线、剖切位置符号、GD&T/公差/粗糙度符号、
      多页图纸集（见 [drawing.md](drawing.md) 的「已知限制」）。
- [x] `resize()` 封装（零 C++ 改动）+ 修饰符助手 `background`/`highlight`/`only`/`disable`（`%`/`#`/`!`/`*`）。
- [x] 2D 交互：viewer 的 2D 改为 `QGraphicsView`（滚轮缩放、拖动平移、双击适应窗口）。
- [x] **类型存根 `moz_openscad.pyi`**（对应 `__init__.pyi`）；`mypy` 校验通过。

## 4. viewer 增强

- [x] 配色方案菜单（用 `face_colors(colorscheme)` 逐帧重取颜色并重传缓冲）。
- [x] 视角预设（前/右/俯/等轴测）；预览器改为 **Z-up**（此前是 Y-up，与 OpenSCAD 不一致）。
- [x] 「导出整个视图序列 PNG」（GL 截图，与窗口所见一致）。
- [x] 把窗口视角同步给引擎再导出 PNG —— 见 §3（`engine_camera()` 精确换算）。
- [x] 坐标轴（X/Y/Z 三色）+ 地面网格（Z=0）叠加层，视图菜单开关。
- [x] **动画工具条**：帧滑块 + 播放速度（静态几何下隐藏；拖帧自动暂停）。
- [x] GL 边线 / wireframe：三角面的去重唯一边 + `GL_POLYGON_OFFSET_FILL` 防 z-fighting。
- [x] **点选测量**：左键单击 → 射线与三角面求最近交点，状态栏给出世界坐标/距离/面号/部件名。
- [x] **多部件视图**：`moz.show_parts`（合并缓冲 + 顶点区间 + 右侧可见性列表 + 点选报告部件名）。
- [x] GIF 导出（Pillow **可选**依赖；缺了只提示，不硬引）。

## 5. 面向产品愿景的大方向（README 的「结构 + 外观设计」）

这层是结构性的，超出「内核 + 绑定 + 预览器」，需单独立项：

- [x] **2D 工程图（出图）**：多视图摆放、剖视、尺寸标注、图框标题栏已完成（见 [drawing.md](drawing.md)）；
      自动布图/隐藏线/剖切符号/GD&T/多页仍是待办（§3 末尾那条）。
- [x] **2D → 3D（图纸变模型）P1**：单视图零件已通——`py/moz_dxf.py` 解析 DXF（ezdxf）→ 图层语义 →
      轮廓修复（去重/桥接/共线/自交诊断，只报告不静默）→ 标注取值（与 `dxf_dim` 同列）→ 挤出成型；
      `py/dxf_demo.py` 走完整闭环（图纸→模型→再出图），`py/verify_dxf.py` 拿上游 DXF 语料回归
      （OK=32、预期开口 2、预期坏图 1、FAIL=0），并用真实板框图验证过。多视图推深度（P4）、
      B-rep 特征与约束求解（P2/P3）见 **[2d-to-3d.md](2d-to-3d.md)**。
- [ ] **装配与运动**：间隙、配合、行程。
- [ ] **自由曲面/NURBS**、**圆角/倒角**（OpenSCAD 无原生倒角）。
- [ ] **公差与合格判定**（可检验性）。
- [ ] **CAM/CAE 直连**。
- [ ] **服务化（Web）**：HTTP / 任务队列 / 沙箱。

## 执行顺序（建议）

1. §0 + §1 + §2 的 API/缓存（低风险，半天量级）。
2. §3 的类型存根与 `resize()` 助手。
3. §4 viewer 增强（配色、视角预设、整段动画导出）。
4. §5 按产品规划单独立项。