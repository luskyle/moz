# 架构

## 三层

```
┌──────────────────────────────────────────────────────────────┐
│ py/  Python 层                                               │
│   moz_openscad.py  建模 API（ctypes 绑定 + 源码拼装 + 取值） │
│   moz_viewer.py    预览器（PySide6：3D 用 OpenGL，2D 用 SVG）│
│   verify_examples.py  示例保真度验证（开发工具）             │
├──────────────────────────────────────────────────────────────┤
│ 3rd/openscad/src/moz/  C ABI 层（本项目唯一新增的 C++）       │
│   moz_api.h  moz_api.cc                                      │
│   moz_eval_* · moz_eval_value · moz_export* · moz_dump       │
│   moz_render_png* · moz_geom_face_colors · moz_geom_measure  │
│   moz_eval_animation* · moz_add/get_library_path             │
├──────────────────────────────────────────────────────────────┤
│ 3rd/openscad/  OpenSCAD 2021.01 内核（vendored，见下）        │
│   解析器 → 实例化 → CGAL 布尔求值 → 导出 / 离屏渲染          │
└──────────────────────────────────────────────────────────────┘
```

共享库 `build/lib/libmozopenscad.so`（约 9 MB）由 `CMakeLists.txt` 里的 `mozopenscad` 目标产出
（`OUTPUT_NAME=openscad_moz`，脚本再拷成 `libmozopenscad.so`）。

## 目录地图

| 路径 | 作用 |
| --- | --- |
| `py/moz_openscad.py` | 全部建模 API，纯 `ctypes`，不依赖第三方（除 `numpy`/`PySide6` 只在预览器里用） |
| `py/moz_viewer.py` | 3D/2D 预览器 |
| `py/verify_examples.py` | 逐示例保真度验证脚本 |
| `py/examples/` | 48 个示例（按上游 `examples.json` 的分类组织） |
| `py/demo.py` | 参数化支架演示（导出 STL/3MF + 预览 + CSG dump） |
| `3rd/openscad/src/moz/moz_api.{h,cc}` | C ABI 实现 |
| `3rd/openscad/` | vendored OpenSCAD 源码（含 `libraries/MCAD/fonts.scad`） |
| `scripts/build_moz_openscad.sh` | 唯一的构建配方 |
| `build/` | 构建目录与产物（**未入库**：`build/lib`、`build/out`） |

## 数据流

1. Python 侧**只拼 SCAD 源码字符串**：`moz.cube(10)` → `Shape("cube(size = 10, center = false)")`。
   没有 Python 端的几何运算、没有 CSG 求值，全部推迟给引擎。
2. 求值/导出/渲染时，`moz_openscad.py` 通过 `ctypes` 调 C ABI；C ABI 内部沿用上游
   命令行 `src/openscad.cc` 的调用链：
   `parse()` → `instantiateWithFileContext()` → `GeometryEvaluator` → `exportFile*()`。
3. 渲染（PNG）走**上游的 preview 路径**：`CsgInfo::compile_products()` +
   `OpenCSGRenderer`/`ThrownTogetherRenderer`，这样 `color()` 才会生效（等价 GUI 的 F5）；
   `renderer="cgal"` 时走上游 `--render=cgal` 的无颜色几何渲染。
4. 逐面颜色（预览器上色）：把 CSG 链上的彩色叶子与最终网格做归属判定，
   输出与 `binstl` 三角面一一对应的 RGBA 数组。

## 几个关键设计决定

- **用 C ABI + ctypes，而不是 pybind11/CPython 扩展**：绑定层零编译依赖，Python 代码可读可改；
  跨语言边界只有 20 个函数，语义边界清晰（错误统一走 `err` 字符串）。
- **Python 不做几何运算**：SCAD 的求值语义（$fn/$fa/$fs、布尔顺序、Nef 结构）很难在 Python 里复刻一致。
  让引擎算，是本项目能让「Python 版与原生 .scad 结果一致」的前提（见 [verification.md](verification.md)）。
- **共享库而不是可执行文件**：headless 目标（`HEADLESS=ON` + `OPENSCAD_NOGUI`）把 GUI/Qt 依赖摘掉，
  与 `mozopenscad` 库共用同一套 `CORE_SOURCES + CGAL_SOURCES + OFFSCREEN_SOURCES`。
- **渲染分两条路径**：preview 路径保留颜色（默认），CGAL 路径保留上游 `--render=cgal` 的行为；
  两条路径的相机都遵循模型里的 `$vpr/$vpt/$vpd/$vpf`。

## 线程与内存模型

- 引擎内部有静态全局状态（parser、内置函数、字体缓存），因此 C ABI 的**所有入口串行化**
  （一个全局互斥量），包括 `moz_geom_free` 与日志读取。并发调用会排队，不会并行加速。
- `moz_geom *` 是一次「解析 + 实例化 + 求值」的产物句柄，进程内独立；用完必须 `moz_geom_free`。
  Python 侧 `Geometry` 对象在 `close()`/`__del__` 时释放。
- 所有返回给调用方的字符串/缓冲都是 `malloc` 出来的，分别用
  `moz_str_free` / `moz_bytes_free` 释放；`err` 非空时也要释放。

## 对上游 OpenSCAD 的改动清单

vendored 树里只有 5 处与本项目相关的改动（其余保持上游原样）：

| 文件 | 改动 |
| --- | --- |
| `CMakeLists.txt` | 增加 `HEADLESS` / `NULLGL` 选项、`mozopenscad` 共享库目标、`BUILD_TESTING` 默认关闭（`tests/` 依赖缺失的 MCAD submodule） |
| `src/moz/moz_api.h`、`src/moz/moz_api.cc` | **新增**：C ABI 实现 |
| `src/cgalutils-polyhedron.cc` | CGAL ≥ 5.4 删掉了 `generic_print_polyhedron`，改为手写 writer 回调输出 |
| `src/cgalutils-tess.cc` | 按 CGAL 版本在 `Triangulation_2_projection_traits_3` / `..._filtered_...` 之间切换 |
| `src/export.h` | 补出 `exportFile(geom, ostream&)` 重载声明，供库内调用 |

版本以 `openscad.pro` 的 `VERSION=2021.01`（`VERSIONDATE=2021.01.31`）为准；
`RELEASE_NOTES.md` 标题仍是 2019.05——上游是在发布时才更新该文件的，不能据此判断版本。

第三方组件与许可见 [third-party.md](third-party.md)。