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

- [x] **测试**：新增 `py/tests/`（pytest，61 个用例），覆盖 measure 数值、eval/export 往返、取值通道、
      动画帧、库路径、网格/颜色、`Shape` 缓存、错误路径、viewer 逻辑（不 show 窗口）。
- [x] **CI**：`.github/workflows/ci.yml` —— 装依赖 → 构建 `.so` → 跑 pytest → 跑 48 示例保真度。
- [ ] **打包**：wheel 不含 `libmozopenscad.so`，装完必须设 `MOZ_OPENSCAD_LIB` / `MOZ_OPENSCAD_RESOURCE_DIR`。
      待定：把 `.so` 打进平台 wheel，还是在文档里把「安装后配置」写清。
- [ ] **lint/format**：加 ruff 配置（`pyproject.toml` 里目前没有）。

## 2. API 与性能

- [x] `moz_geom_triangles`：直取三角面顶点数组，viewer 不再解析 STL 字节。
- [x] `moz_geom_face_colors_ex`：给逐面颜色加 `colorscheme` 参数（GL 预览切换配色的前提）。
- [x] `Shape` 惰性求值缓存（按 `variables` 快照失效）。
- [ ] `moz_geom_measure` 每次重新三角化 Nef —— 与 export/face_colors 共享一次三角化（内部缓存）。
- [ ] 动画预计算是 `frames × 求值`；大模型慢 —— 按需求值 + LRU 缓存，或可取消的后台预计算。
- [ ] 并发：全局递归互斥 → 单线程串行。服务化前必须先解决引擎静态全局状态（parser/builtins/字体缓存）。

## 3. 新 API（延续 C ABI 补全）

- [ ] 相机结构（视角 / 正交 / 取景 bbox），让「导出 PNG」与窗口视角一致（现在只能靠模型里的 `$vpr`）。
- [ ] 几何查询扩展：惯性矩、凸包、点包含（point-in-solid）、最近点/距离、截面 slice。
- [ ] `resize()` 封装（零 C++ 改动）+ 修饰符助手 `background/debug/only/disable`（`%`/`#`/`!`/`*`）。
- [ ] 2D 交互：viewer 的 2D 目前只是静态 SVG，无缩放/平移/尺寸标注。
- [ ] **类型存根 `moz_openscad.pyi`**（对应 `__init__.pyi`）：显著改善 IDE 体验。

## 4. viewer 增强

- [ ] 配色方案菜单（依赖 §2 的 `moz_geom_face_colors_ex`）。
- [ ] 边线/坐标轴/地面网格（`render_png` 有这些选项，GL 视图没有）。
- [ ] 视角预设（前/上/等轴测）；把窗口视角同步给引擎再导出 PNG。
- [ ] 帧滑块 + 播放速度 UI；「导出所有帧 PNG / GIF」。
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