# moz

> 借助 mcp server，一句话生成一个令人惊叹的 3d 场景，除了让人惊叹一下，挺唬人的之外，实际很难应用到工业生产中。因为自然语言不是描述 3d 物体的最佳方式。
>
> 自然语言擅长表达 **意图、功能、约束和上下文** ，比如“这个支架要轻、能承受50公斤、安装在左侧”。但它不擅长精确表达：
>
> * 空间拓扑：谁在谁里面、谁穿过谁、谁与谁相切；
> * 定量几何：尺寸、角度、曲率、位置度；
> * 自由曲面：汽车外壳、人脸、螺旋桨叶片；
> * 装配关系与运动：间隙、配合、行程；
> * 制造要求：公差、表面粗糙度、材料、热处理。

>
> 所以自然语言适合说“要什么”，不适合直接定义“几何长什么样”。
>
> 2D工程图纸不是普通2D图片，而是一套 **符号化、标准化的技术语言** 。它通常包含：
>
> * 多视图正投影：主视图、俯视图、左视图；
> * 剖视图、断面图、局部放大图；
> * 尺寸标注、公差、基准、GD&T；
> * 表面粗糙度、材料、热处理、装配关系、BOM。
>
> 它的核心优势是：
>
> 1. **精确且可检验** ：尺寸和公差定义了“合格范围”，不依赖测量图纸本身。
> 2. **制造导向** ：工人、机床、检验员可以直接按图加工和检测。
> 3. **信息压缩** ：几个视图加标注，就能定义一个简单零件的完整制造要求。
> 4. **标准化** ：第一角法、第三角法、ISO/GB 等规则让全球工程师能读懂。
> 5. **法律与合同属性** ：图纸长期是工程交付和验收的依据。
>
> 对于轴、板、支架、法兰、齿轮这类由基本几何构成的零件，2D工程图几乎是最有效的描述方式。
>
> 但2D工程图不是万能的。
>
> 它的根本局限在于：**3D物体被压缩到2D，必然丢失信息，必须靠约定、视图和标注补回来。** 对于简单几何，补得回来；对于复杂几何，很难补全。
>
> * **自由曲面** ：汽车车身、飞机机翼、涡轮叶片，靠三视图和尺寸几乎无法精确描述，通常必须依赖3D曲面模型、点云或数学曲面数据。
> * **有机形状** ：雕塑、医疗植入物、艺术造型，2D图纸基本无能为力。
> * **装配与运动** ：零件之间的运动干涉、间隙、动态包络，3D装配模型更直观。
> * **直接制造与仿真** ：CAM、CAE、3D打印通常直接需要3D模型，而不是2D图纸。
> * **多视图歧义** ：不同形状可能产生相同投影，必须靠更多视图、剖视或3D模型消除歧义。
> * **阅读门槛** ：2D图纸需要专业训练，普通人难以从图纸还原3D形象。
>
> 我想设计一个一体化的解决方案，辅助我更加轻松地完成结构与外观设计。
>
> 作者：luskyle

## 目前有什么

一句话：**把 OpenSCAD 2021.01 内核改造成一个可以被程序和脚本调用的几何内核，并提供一个与之语义严格对齐的 Python 建模 API。**

```
py/                      Python 层：建模 API（moz_openscad）+ 2D 制图（moz_drawing）+ 预览器（moz_viewer）+ 示例与验证脚本
3rd/openscad/src/moz/    C ABI（本项目唯一新增的 C++），编译成 libmozopenscad.so
3rd/openscad/            vendored 的 OpenSCAD 2021.01 源码（含自研的 libraries/MCAD/fonts.scad 字形表）
assets/fonts/            自带中文字库子集（OFL 1.1，脚本生成）
scripts/                 构建脚本、字库/字形表生成脚本
build/                   构建目录与产物（未入库）
docs/                    文档
```

| 能力 | 入口 |
| --- | --- |
| 用 Python 拼模型并导出 STL/3MF/OFF/AMF/DXF/SVG/PDF/PNG | `py/moz_openscad.py` |
| 交互预览（3D 旋转/缩放，颜色来自 `color()`） | `shape.show()` / `py/moz_viewer.py` |
| 直接调 C ABI（25 个函数） | `3rd/openscad/src/moz/moz_api.h` |
| 从引擎里取值（`dxf_dim`/`rands`/`lookup`/`version`…，全精度） | `moz.value()` / `moz.number()` / `moz.vector()` |
| 逐面颜色（与导出的 STL 三角面一一对应） | `Geometry.face_colors()` |
| 几何测量（包围盒/体积/表面积/面数/顶点数/质心） | `Geometry.measure` |
| 截面 / 轮廓投影（任意视线方向的切平面 → 2D） | `moz.section()` / `moz.outline()` / `moz.view_basis()` |
| 2D 工程图（视图、剖视、尺寸标注、图框标题栏；导出 SVG/DXF/PDF） | `py/moz_drawing.py`，示例 `py/drawing_demo.py` |
| 动画帧（逐帧设 `$t` 并回调，对应上游 `--animate`） | `moz.eval_animation()` |
| 库搜索路径运行时接口 | `moz.add_library_path()` / `moz.library_paths()` |
| 校验「Python 版和原生 `.scad` 是不是同一个几何」 | `py/verify_examples.py` |

## 快速上手

前置：Python ≥ 3.10、`numpy`、`PySide6`；构建几何库需要 C++ 工具链与 CGAL/OpenCSG 等依赖
（清单见 [docs/build.md](docs/build.md)）。

```bash
# 1) 构建几何内核（首次 3~5 分钟，改过 C++ 后增量约 30 秒）
bash scripts/build_moz_openscad.sh

# 2) 直接用 Python 建模
PYTHONPATH=py python3 -c "
import moz_openscad as moz
shape = moz.difference(moz.cube(20, center=True), moz.sphere(12))
shape.export('binstl', '/tmp/out.stl')
print('dimension =', shape.dimension, '| empty =', shape.is_empty)
"

# 3) 预览某个示例（窗口里左键旋转、右键平移、滚轮缩放）
PYTHONPATH=py python3 py/examples/Basics/CSG.py

# 4) 校验示例与原生 .scad 的几何是否一致
PYTHONPATH=py python3 py/verify_examples.py Basics/CSG
```

## Python 直接建模

示例模块统一暴露 `build()`，返回一个 `Shape`（Python 侧**只拼 SCAD 源码**，求值交给引擎）：

```python
import moz_openscad as moz

def build():
	return moz.difference(moz.cube(20, center=True), moz.sphere(12))
```

```bash
PYTHONPATH=py python3 py/examples/Basics/CSG.py                      # 预览
PYTHONPATH=py python3 py/moz_viewer.py py/examples/Basics/CSG.py     # 或把任意 build() 交给预览器
```

## 示例

`py/examples/` 下 48 个示例，分类与文件名完全对应上游 `3rd/openscad/examples/`：
`Basics/` 9 个、`Functions/` 5 个、`Advanced/` 8 个、`Parametric/` 2 个、`Old/` 24 个。
它们引用外部数据文件（`.dxf`/`.dat`/`.stl`/`.png`）与 JSON 参数集时，**指向原始示例目录里的同一份文件**，不做拷贝。

保真度已逐个校验：`PYTHONPATH=py python3 py/verify_examples.py` 输出 `汇总: OK=48`
（其中 32 个连导出字节都一致，其余是「同一网格不同面序」或「同一实体不同三角化」）。
判定标准与结果明细见 [docs/verification.md](docs/verification.md)。

## 文档

| 主题 | 文档 |
| --- | --- |
| 索引与快速开始 | [docs/README.md](docs/README.md) |
| 三层架构、数据流、对上游的改动清单 | [docs/architecture.md](docs/architecture.md) |
| 构建、依赖、运行时环境变量、排错 | [docs/build.md](docs/build.md) |
| C ABI 参考（逐函数语义/错误/内存所有权） | [docs/c-api.md](docs/c-api.md) |
| Python API 参考 | [docs/python-api.md](docs/python-api.md) |
| 截面与 2D 工程图（视图、剖视、尺寸标注、导出） | [docs/drawing.md](docs/drawing.md) |
| 示例组织方式与迁移 `.scad` 的清单 | [docs/examples.md](docs/examples.md) |
| 保真度验证方法、判据与当前结果 | [docs/verification.md](docs/verification.md) |
| **SCAD 语义陷阱（实测清单）** | [docs/scad-semantics.md](docs/scad-semantics.md) |
| 预览器 | [docs/viewer.md](docs/viewer.md) |
| 现状与已知限制 | [docs/limitations.md](docs/limitations.md) |
| 第三方组件与许可 | [docs/third-party.md](docs/third-party.md) |

## 路线

当前形态是「内核 + Python 绑定（桌面预览）」，下一步的产品形态是 Web/服务化
（见 [docs/limitations.md](docs/limitations.md) 里列出的能力缺口：几何查询、动画帧、服务化封装等）。

## 许可

本仓库自有代码为 Apache-2.0（见 [LICENSE](LICENSE)）；vendored 的 OpenSCAD 内核为 GPLv2（含 CGAL 例外）；
仓库里的两个字体资产——自研的 `libraries/MCAD/fonts.scad` 字形表与 `assets/fonts/MozSansSC-Regular.ttf`
中文字库子集——均为 SIL OFL 1.1（可商用、可再分发）。链接出的 `libmozopenscad.so` 属于 GPL 派生物——
对外分发/服务化前请先确认许可义务，详见 [docs/third-party.md](docs/third-party.md)。