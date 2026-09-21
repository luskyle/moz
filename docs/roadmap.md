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
- [x] **打包**：**决定不把 `.so` 打进平台 wheel**（依赖 CGAL/OpenCSG/Qt，需 manylinux 与多套 wheel，
      收益小于维护成本）；改为在 [build.md](build.md) 写清「安装后配置」。
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
- [ ] 截面 `slice`（切平面 → 2D 轮廓）—— 需要平面与 Nef 求交并产出新句柄，未做。
- [x] `resize()` 封装（零 C++ 改动）+ 修饰符助手 `background`/`highlight`/`only`/`disable`（`%`/`#`/`!`/`*`）。
- [x] 2D 交互：viewer 的 2D 改为 `QGraphicsView`（滚轮缩放、拖动平移、双击适应窗口）。
- [x] **类型存根 `moz_openscad.pyi`**（对应 `__init__.pyi`）；`mypy` 校验通过。

## 4. viewer 增强

- [x] 配色方案菜单（用 `face_colors(colorscheme)` 逐帧重取颜色并重传缓冲）。
- [x] 视角预设（前/右/俯/等轴测）；预览器改为 **Z-up**（此前是 Y-up，与 OpenSCAD 不一致）。
- [x] 「导出整个视图序列 PNG」（GL 截图，与窗口所见一致）。
- [ ] 把窗口视角同步给引擎再导出 PNG —— 见 §3（相机覆盖已完成，剩角度/尺度映射）。
- [ ] 边线/坐标轴/地面网格（`render_png` 有这些选项，GL 视图没有）。
- [ ] 帧滑块 + 播放速度 UI；GIF 导出。
- [ ] 点选测量（需 picking + §3 的几何查询）；多部件/场景列表（对应装配）。

## 5. 面向产品愿景的大方向（README 的「结构 + 外观设计」）

这层是结构性的，超出「内核 + 绑定 + 预览器」，需单独立项：

- [ ] **2D 工程图**：多视图正投影、剖视、尺寸/公差/GD&T、粗糙度 —— OpenSCAD 只有 `projection()`，
      没有制图能力（需自建制图引擎或接 OCCT/FreeCAD）。
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