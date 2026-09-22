# 现状与已知限制

这份文档记「现在还不能做什么」，避免把期望建在不存在的接口上。

## C ABI / Python 侧的能力缺口

| 项 | 状态 / 说明 |
| --- | --- |
| 几何查询 | ✅ 已提供：`moz_geom_measure` / `Geometry.measure` → 包围盒、体积（3D）、表面积（3D）/面积（2D）、三角面数、去重顶点数、质心（3D 体积质心 / 2D 面积质心） |
| 动画帧 | ✅ 已提供：`moz_eval_animation` / `moz_eval_animation_file` / `moz.eval_animation`，逐帧把 `$t = frame / fps` 传给模型并回调（等价上游 `--animate`） |
| 库搜索路径的运行时接口 | ✅ 已提供：`moz_add_library_path` / `moz_get_library_paths`，不再只能靠 `OPENSCADPATH` 环境变量 |
| 细粒度导出选项 | ⚠️ **基本没有可暴露的**：2021.01 里 STL 只有 ascii/二进制之分（由 format 决定）、3MF 无元数据/单位参数、AMF 的 `unit="millimeter"` 与 producer 元数据是硬编码。仅透出 `ExportInfo` 真正可配的 `sourceFileName`/`sourceFilePath`（`moz_export_ex` / `Geometry.export(..., source_file_name=...)`，只有 PDF 会用到） |
| 截面 / 2D 工程图 | ⚠️ **已提供一层，但不是完整制图**：`moz.section` / `moz.outline`（任意视线方向的切平面与轮廓投影）+ `py/moz_drawing.py`（视图摆放、剖面线、中心线、线性/直径/半径标注、图框标题栏、`fits()` 版式自查，导出 SVG/DXF/PDF）。**没有**自动布图与投影对齐、隐藏线/虚线、剖切位置符号、GD&T/公差/粗糙度、多页图纸集——清单见 [drawing.md](drawing.md) |
| 没有 CSG 树/颜色以外的中间产物接口 | 例如「每个 CSG product 的几何 + 颜色 + 变换」这种数据结构只用于内部的逐面颜色判定 |
| 单实例串行 | 所有入口共享一个全局**递归**互斥量（引擎有静态全局状态），并发请求只是排队；递归是为了让动画回调里能再调 `measure`/`export`/`render`。**并行化做不了**：解析器、builtins、字体缓存、`RenderSettings`（含全局配色）都是进程级静态状态，改成分线程安全等于重写上游内核，故此项不做（服务化只能靠多进程） |
| 没有服务化封装 | Web/服务化是项目路线目标，目前只有库 + 绑定 + 预览器；尚无 HTTP/任务队列/沙箱 |

## 与上游行为的已知差异（有意保留，避免误导）

- `moz_dump` 的 `csg`/`ast` 里显示**绝对路径**（我们把文档路径绝对化了）。
- `echo` 格式只回 echo 文本行，不含其它日志；其它日志走 `moz_geom_log`。
- PNG 未指定宽高时用 `RenderSettings` 默认（512×512）。
- 空几何的 `dimension` 与上游一致（仍是 3），另给 `is_empty` 便于判断。
- 预览器显示的是**求值后的实体网格**，所以看不到 `%` 背景对象与 `#` 高亮。

## vendored 内核的既有约束

- `tests/` 与 `tests/MCAD` 依赖缺失（上游 submodule 不在源码包里），因此 `BUILD_TESTING` 默认关闭，
  上游自带测试没有接入。
- 上游示例里凡是依赖 MCAD 库的（当前只有 `Old/example023`）都需要 `libraries/MCAD/fonts.scad`，
  见 [third-party.md](third-party.md)。
- 对 CGAL 版本有要求：源码树里的补丁是按 **CGAL ≥ 5.4** 写的，用更旧的 CGAL 需要改回上游写法
  （见 [build.md](build.md)）。
- 渲染依赖离屏 OpenGL（`OffscreenView`）；`NULLGL=ON` 的构建会让 PNG 渲染变成空实现，仅够做几何验证。

## 尚未验证/未覆盖

- **只在本机（Ubuntu 24.04.5 / CGAL 5.6 / OpenCSG）验证过**；原文档环境 22.04 / CGAL 5.4 未复测，
  也没有 Windows/macOS、别的 CGAL/编译器组合的验证记录。
- **示例保真度只针对 48 个上游示例**；自己写的模型没有额外的黄金数据可比对。
- 逐面颜色的归属判定在「面同时贴在多个对象表面」这种退化情形下按固定顺序取首个命中，
  可能与你直觉不同（预览路径的渲染结果不受影响）。
- 没有做性能基准，只有零散实测：CGAL 求值 1.3~31.6 s（示例规模）、
  导出 STL + 逐面颜色 0.08~1.13 s（1.6k~15.5k 面）、增量重构建 ~30 s。