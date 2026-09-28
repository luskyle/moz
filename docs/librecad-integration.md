# 借 LibreCAD 读 DXF/DWG（对 Python 的抽取与渲染集成）

一句话：**把 `libdxfrw`（DXF/DWG 解析库，上游 2.0.0）抽成一个零 Qt 依赖的 `.so`，用 C ABI 接到 Python，读成"规范化 2D 实体模型"；渲染器新增一条直画图元的路径，于是我们自己的预览器能查阅 DXF/DWG**——这是后续"图纸 → 模型"（[2d-to-3d.md](2d-to-3d.md)）吃 DWG 的前置条件。LibreCAD 的作用是**参考实现**（它的过滤器语义、容错姿态、图元体系）。

```
DXF / DWG 文件
     │   ① libdxfrw（纯 C++、零 Qt、零 zlib）——解析 + 容错
     ▼
DRW_Interface 回调（addLine/addCircle/addEllipse/addSpline/addInsert/addHatch/…）
     │   ② 我们自己的 driver：把回调收成 POD 记录数组
     ▼
libmozcadio.so（C ABI，只出裸数据，不出 C++ 对象）
     │   ③ ctypes
     ▼
py/moz_cadio.py —— 规范化 2D 实体模型（图层/线型/颜色/块/标注/文字/样条…）
     ├──► py/moz_viewer.py 的 2D 直画（N2：图层显隐、ACI/真彩、线型、真曲线）
     └──► py/moz_dxf.Drawing（N3：图纸 → 可改参数化模型，DWG 也能走）
```

**为什么不用 ezdxf 顶掉**：ezdxf（MIT）只吃 DXF，DWG 一点都读不了——而"车间里发过来的图"常见就是 DWG。DWG 是自己写解析器不划算：libdxfrw 的 DWG 侧是一整套读取器（`libdwgr.cpp` + `intern/dwgreader{R1_40,R11,15,18,21,24,27,32}.cpp`，覆盖 **R1.40–2018+**）。

**为什么要抽而不是直接用**：LibreCAD 的解析入口挂在 GUI 上——它的 CMake 只产出**一个** `add_executable(librecad …)`，控制台能力（`dxf2pdf/dxf2png/dxf2svg`）也都要 `QApplication`（`librecad/src/main/console_dxf2pdf/console_dxf2pdf.cpp:51`）。而真正的解析库 `libdxfrw` 与 Qt **完全无关**（全树 `#include <Q…>` 零命中），所以抽它是干净的。

**为什么不用 LibreCAD 树里那份 libdxfrw（实测后改的结论）**：我们先把 LibreCAD 随树分发的拷贝编了出来，用真实 DWG 一验就露馅了——那份是 **0.5.11 时代**的拷贝，`AC1018/AC1021/AC1024/AC1027` 全部读不了（`BAD_READ_BLOCKS`/`BAD_READ_TABLES`/`BAD_READ_FILE_HEADER`）、AC1032 直接拒绝，连 `AC1014` 都只读出 **104** 个实体（上游读 145，**老那份在静默丢几何**）。而上游 **libdxfrw 2.0.0**（commit `25a2f8d`）多了 `dwgreaderR11/R1_40/32`，同一批 16 个样本**全通**、实体数也对得上；上游仓库里还躺着 `LIBRECAD_DXFRW_UPGRADE_PLAN.md`（他们自己也正打算把 LibreCAD 升到这个版本）。所以我们的**构建源是上游 2.0.0**（vendored 在 `3rd/libdxfrw/`），LibreCAD 树里那份只作参考。C ABI 一行没改就编过了——说明这个接口层是稳定的。

## 一、目标与非目标

**目标**

1. Python 侧能打开 DXF/DWG，拿到**可渲染的全部图元**与图层/线型/颜色语义（不是只抽成材料轮廓）；
2. 我们自己的预览器（`py/moz_viewer.py`）能像看图软件一样查阅这些文件：图层开关、颜色、线型、文字、样条真曲线；
3. 为后续集成铺路：DWG 也能进"图纸 → 参数化模型"（P1 那条链）；
4. 零 Qt 依赖、零额外第三方库（只多一个 `.so`），随平台 wheel 分发。

**非目标（明确不做）**

- ❌ 不编 LibreCAD 的 GUI/实体语义层（`RS_*`、`lib/gui`）：那是路线 B，需要 Qt Core+Gui、要处理 `draw()` 对 `RS_GraphicView` 的链接依赖、还要字体/图案资源目录；将来若真要"解析后可直接编辑/改图"再单独立项；
- ❌ 不做 DWG **写**（libdxfrw 的写侧是 DXF；出图我们已有 SVG/DXF/PDF）；
- ❌ 不引入 Qt/OCCT 等新依赖（本方案一个都不需要）；
- ❌ 不自造文件格式——对外仍是标准格式，中间层只是内存模型（同 [2d-to-3d.md](2d-to-3d.md) §六②）。

## 二、现状盘点（实测，不是推断）

| 事实 | 证据 |
| --- | --- |
| 解析核心是 libdxfrw **上游 2.0.0**（vendored） | `3rd/libdxfrw/src/`：**36 个 `.cpp`**（清单与它自带的 `libdxfrw_sources.cmake` 一致）；`libdxfrw.h` 的 `dxfRW`（DXF，`read(DRW_Interface*, bool ext)`）与 `libdwgr.h` 的 `dwgR`（DWG）。LibreCAD 树里那份 0.5.11 时代的拷贝只作参考 |
| 它**不依赖 Qt** | 全树 `#include <Q…>` **0 命中**；头文件只用 `<string>/<unordered_map>/<vector>`（`libdxfrw.h:17-21`） |
| 它**不依赖 zlib** | DWG 解压自带（`intern/dwgutil.h` 的 `dwgCompressor`），全树无 `zlib.h` |
| 许可 **GPLv2-or-later** | `libdxfrw.h:9`：“either version 2 of the License, or (at your option) any later version” |
| DWG 覆盖 **R1.40–2018+** | 上游 `src/libdwgr.cpp:3300` 的版本分派：`AC14`→`dwgReaderR1_40`、`AC210/AC1003/AC1004/AC1006/AC1009`→`dwgReaderR11`、`AC1012/AC1014/AC1015`→15、`AC1018`→18、`AC1021`→21、`AC1024`→24、`AC1027`→27、**`AC1032`→32**；不支持的只剩 R2.5 之前的古董（`MC0.0/AC1.2/AC1.50/AC1002`）。实测 16 个真实样本全通（`corpus/dwg/README.md` 有逐个体量） |
| 上游自认 DWG 不完整 | `librecad/src/lib/fileio/rs_fileio.cpp:74` 的 “DWG support is not complete!” 提示 |
| 图元回调齐全 | `drw_interface.h:29` 的 `DRW_Interface`：point/line/ray/xline/arc/circle/ellipse/lwPolyline/polyline/spline/insert/trace/3dface/solid/mText/text/dimAlign/dimLinear/dimRadial/dimDiametric/dimAngular/dimAngular3P/dimOrdinate/leader/hatch + 表回调（header/lType/layer/dimStyle/vport/textStyle/appId/block） |
| 每个图元自带图层/颜色/线型/可见性 | `drw_entities.h:127-150` 的 `DRW_Entity`：`eType/handle/space/layer/lineType/color(ACI)/color24/colorName/lWeight/ltypeScale/visible` |
| LibreCAD 侧只是"翻译层" | `librecad/src/lib/filters/rs_filterdxfrw.h:61`：`RS_FilterDXFRW : public RS_FilterInterface, DRW_Interface`——把 `DRW_*` 转成 `RS_*` |
| 可复用的源清单 | 上游自带的 `3rd/libdxfrw/libdxfrw_sources.cmake`（36 个 `.cpp`）；`3rd/libdxfrw/moz/CMakeLists.txt` 与它一致 |
| 现成冒烟样本 | LibreCAD 树里的 `screw2012ascii.DXF`（27 个实体，读得通）与它的二进制孪生 `screw2012binary.dxf`（**对象段连上游也读不了**：`BAD_READ_OBJECTS`；ezdxf 读它没问题） |
| 我们这边的接缝 | `.so` 的既有做法：`scripts/build_moz_openscad.sh` → CMake 目标 → `build/lib/*.so` → 拷进 `py/moz_data/lib/` 随 wheel 分发；预览器 2D 现在是 `Interactive2D(QGraphicsView)` 吃**引擎导出的 SVG**（`py/moz_viewer.py:631-646`） |
| 我们这边的 Python 资产 | `py/moz_dxf.py` 已有 bulge 展开、圆弧离散、端点吸附、嵌套/成环、奇偶填充、标注取值一整套——**libdxfrw 只出原始图元，规范化这一层我们已经有现成的** |

## 三、技术规格（路线 A）

### 3.1 C ABI（`libmozcadio.so`）

只出 POD，不出 C++ 对象；借用缓冲的生命周期绑定在文件句柄上（与现有 `moz_geom_triangles` 的借用语义一致）：

```c
typedef struct moz_cad_file moz_cad_file;                      // 不透明句柄
typedef struct { /* 见 3.2 的字段表 */ } moz_cad_entity;

moz_cad_file *moz_cad_read(const char *path, char **error);     // 自动判别 DXF/DWG；失败返回 NULL 并给原因
const char   *moz_cad_version(moz_cad_file *f);                 // "AC1015" / "AC1027" 等
int           moz_cad_entity_count(moz_cad_file *f);
const moz_cad_entity *moz_cad_entity_at(moz_cad_file *f, int i); // 借用指针，free 前有效
int           moz_cad_layer_count(moz_cad_file *f);
const moz_cad_layer  *moz_cad_layer_at(moz_cad_file *f, int i);  // 名字/ACI/真彩/线型/线宽/开闭冻结
int           moz_cad_block_count(moz_cad_file *f);
const moz_cad_block  *moz_cad_block_at(moz_cad_file *f, int i);  // 块名 + 基点（块内实体按 owner 归组）
int           moz_cad_warning_count(moz_cad_file *f);            // 解析告警（不静默）
const char   *moz_cad_warning_at(moz_cad_file *f, int i);
void          moz_cad_free(moz_cad_file *f);
```

- **不在这里做离散化**：样条/椭圆/bulge 原样交给 Python（我们已有一套离散口径，N3 要与 `moz_dxf.py` 对齐，不能有两套）。
- **失败要带原因**：libdxfrw 用 `DRW::error` 记 `BAD_OPEN/BAD_VERSION/BAD_READ_*`，driver 把它翻成一条可读的 `error` 字符串（例如"这个版本没有可用的读取器（上游只支持 R1.40–2018+…）"；AC1032 这类**支持**的版本读失败时不会误报成"不支持"）。
- 线程/并发：与内核一致——**不做**（每次 `read` 独立句柄，Python 侧多进程即可）。

### 3.2 规范化 2D 实体模型（`py/moz_cadio.py`）

`CadFile(version, extents, units, layers[], blocks[], entities[], warnings[])`，实体按种类带自己的载荷：

| 种类 | 载荷（关键字段） |
| --- | --- |
| `Point` / `Line` / `Ray` / `Xline` | 起点/方向（**RAY/XLINE 原样保留**，不像 LibreCAD 那样降级成有限线段） |
| `Circle` / `Arc` | 圆心/半径/起止角（弧度）、`isReversed` |
| `Ellipse` | 中心/长轴向量/短长轴比 `ratio`/起止参数角/旋转——注意参数角≠几何角，离散要按同心圆映射（`RS_Ellipse` 也是这么处理的） |
| `Spline` | degree/flags/控制点/节点向量/拟合点/权重；**两条路**：`degree==2 且 3 控制点`是抛物线、其余按 NURBS 求值 |
| `Polyline` | 顶点序列 `(x, y, bulge)` + `closed`（LWPolyline 与老 Polyline 统一成这一种） |
| `Insert` | 块名/插入点/缩放(x,y,z)/旋转/行列阵列参数（**块展开由 Python 决定**：展开或保留引用） |
| `Text` / `MText` | 位置/高度/旋转/对齐/文字串/样式名（**不解析字形**，渲染交给 Qt 字体） |
| `Dimension` | 标注子类 + 定义点 + 文字覆盖 + 测量值（与 `dxf_dim(file, name)` 认的同一列，N3 直接复用） |
| `Hatch` | 图案名/实体填充标志/边界环（**不求值填充**，渲染时按边界画/按图案铺） |
| 其它 | `Solid/Trace/3Dface/Leader/Image`：能拿到就存，拿不到就记进 `unsupported` 计数（不静默丢） |

配套方法：`tessellate(chord_tolerance=…)`（离散成折线，供渲染与 P1）、`to_drawing()`（N3：喂 `moz_dxf.Drawing` 的轮廓/孔/标注）、`report()`（解析/忽略/告警清单）。

### 3.3 构建与打包

- **driver 放哪**：`3rd/libdxfrw/moz/moz_cadio.cc`（+ `moz_cadio.h`、`CMakeLists.txt`），与 `3rd/openscad/src/moz/moz_api.cc` 同一套路——**跟着被绑的库走**，便于随上游升级；
- **源**：上游 `libdxfrw_sources.cmake` 那 36 个 `.cpp` + driver（**不需要** `DWGSUPPORT` 之类的宏：libdxfrw 里 DWG 代码是无条件编的）；
- **脚本**：`scripts/build_moz_cadio.sh`（仿 `build_moz_openscad.sh`：cmake → `build/3rd/libdxfrw/`，产物落到 `build/lib/libmozcadio.so`）；
- **随包分发**：`.so` 拷进 `py/moz_data/lib/`、在 `pyproject.toml` 登记（打包不变式见 [build.md](build.md)）；`py/moz_cadio.py` 的 `.so` 搜索顺序与 `moz_openscad` 一致（`MOZ_CADIO_LIB` 环境变量 → 模块同目录 → `../build/lib/` → `moz_data/lib/`）；
- **可选依赖**：`ezdxf` 保持原样（`[dxf]` extra）；新通路**不需要** Python 侧第三方依赖。

### 3.4 渲染器直画（N2）

`py/moz_viewer.py` 的 `Interactive2D` 现在只吃引擎出的 SVG；新增一条**独立于内核**的画图路径：

- QGraphicsScene + 自绘 item（线/弧/圆/椭圆/多段线/样条/文字/剖面线边界），线宽按 mm→屏幕换算；
- 图层树（显隐/颜色跟随图层/冻结灰显），线型（实线/虚线/中心线/点划线，按 DXF 的 dash 定义画）；
- 颜色：ACI（含 BYLAYER/BYBLOCK）→ 表，`color24` 真彩优先；
- 大图性能：语料里已有 2.7 MB 的 `api-cw750-details.dxf`、135 孔的 PCB 板框——用批量 item + 视口裁剪（QGraphicsView 自带 BSP），必要时按视口抽稀。

## 四、批次与验收

| 批次 | 交付物 | 验收 |
| --- | --- | --- |
| **N1 抽取 + 绑定** | `3rd/libdxfrw/moz/*`、`scripts/build_moz_cadio.sh`、`py/moz_cadio.py`、`py/tests/test_cadio.py` | ① DXF 与 ezdxf **交叉核对**（同一张图的图元数、坐标、图层/颜色一致或差异可解释）；② DWG 样本读通（`corpus/dwg/`）；③ 对 `corpus/dxf/` 全量 + `3rd/openscad/testdata/**/*.dxf` 不崩、不静默；④ `.so` 进 wheel、`scripts/smoke_installed.py` 验证 |
| **N2 渲染器直画** | `py/moz_cadview.py`（直画 + 图层/颜色/线型 + `moz-cadview` 命令行） | ① 语料图与原图逐项对得上（图层/颜色/线型/文字/样条）；② 大图（2.7 MB、135 孔）打开与平移不卡；③ 与现有引擎渲染路径共存不回归 |
| **N3 归一进 P1** | `moz_dxf.Drawing` 从"规范化实体模型"构建；`moz_dxf` 支持 DWG 入口 | ① 现有 226 文件回归与用例**不回归**；② 一张 DWG 走完"图纸 → 模型 → 再出图"闭环；③ 文档同步（[2d-to-3d.md](2d-to-3d.md)、[roadmap.md](roadmap.md)） |

### N1 实现状态：已完成（2026-09-28）

| 验收项 | 结果 |
| --- | --- |
| C ABI + driver | `3rd/libdxfrw/moz/moz_cadio.{h,cc}`（8 个函数、POD 记录、借用缓冲、错误带原因），`scripts/build_moz_cadio.sh` 一个命令编出 `build/lib/libmozcadio.so`（约 30 秒，**不需要** Qt/内核） |
| Python 绑定 | `py/moz_cadio.py`（ctypes + 规范化模型：19 种图元、图层/块/颜色/线型、`report()`/`counts()`/`by_layer()`） |
| 与 ezdxf 交叉核对 | 三个样例图纸的**模型空间逐类一致**（plate/bracket/messy：`CIRCLE 4+DIMENSION 2+LINE 8` 等），圆坐标/半径逐个一致，图层名集合一致，标注文字与 `dxf_dim` 名一致 |
| DWG | 16 个真实样本全通（AC1014→AC1032 版本阶梯 + 编码页 + 多边形/径向标注/富文本），见 `corpus/dwg/README.md` |
| 语料回归 | `py/verify_cadio.py`：**225 个文件，OK=213、EMPTY=10、预期读不通 2、FAIL=0** |
| 单元测试 | `py/tests/test_cadio.py` 29 个用例（交叉核对/边界/错误路径/DWG 阶梯） |
| 打包 | `.so` 进 wheel（`moz_data/lib/libmozcadio.so`）+ `scripts/smoke_installed.py` 在干净 venv 里验过（含"必须用随包那份 .so"的断言） |
| 实测改掉的两个判断 | ① 构建源从 LibreCAD 树里的 0.5.11 换成**上游 2.0.0**（老那份读不了 AC1018+ 且静默丢实体）；② 逗号小数的图上游会**直接拒绝**（与引擎/`moz_dxf` 态度一致），所以不需要我们再做启发式告警 |

### N2 实现状态：已完成（2026-09-28）

| 验收项 | 结果 |
| --- | --- |
| 直画看图器 | `py/moz_cadview.py`：QGraphicsScene 直画（折线/填充/文字/点），块与标注展开、图层开关面板、ACI/真彩/BYLAYER 颜色、线型近似、文字带旋转；入口 `moz-cadview`（也可 `python3 py/moz_cadview.py`） |
| 渲染层只认模型 | `load()` 先 libdxfrw，DXF 读不通换 ezdxf 兜底（实测上游读不了那个二进制样本的对象段，兜底顶上并给告警）——两条解析路径产出同一种 `CadFile` |
| 离散口径 | 弧/椭圆按弦高容差、bulge 展开、样条是**有理 de Boor**（RATIONAL 带权重）；与 P1 共用同一套 `entity_polylines`，不出现"两套口径" |
| 不静默 | 块参照查不到定义（DWG 匿名块名被上游截断 `*U19`→`*U`）、剖面线没有边界环（MPOLYGON）都会报出来 |
| 性能 | 2.7 MB / 5260 item 的整图约 **0.31 秒**；16 个真实 DWG 全部画得出来 |
| 目录与图纸列表 | **打开目录**（`list_drawings()` 递归扫描，上限 500）：右侧「图纸」面板点一下就换；打开单张图则列出同目录的兄弟文件；`Ctrl+O`/`Ctrl+Shift+O`/拖图纸或目录都能开 |
| 随手可用的示例 | `py/cadview_demo.py`：不给参数时弹一个**两个按钮**的选择框（选择文件… / 选择目录…，外加取消），选完就打开；无显示器时给提示与样例清单 |
| 导出与无窗口模式 | `--export-png` / `--export-svg` / `--report`（给目录则逐个打印）/ `--layers` / `--stats`（无显示器即可跑） |
| 测试 | `py/tests/test_cadview.py` **19 个用例**（离散数学、颜色/线型、场景装配、块与标注展开、退化输入、大图性能、兜底读取、导出、命令行） |
| 打包 | wheel 带 `moz_cadview.py` 与 `moz-cadview` 入口；`scripts/smoke_installed.py` 里 offscreen 画过一遍 |
| 人眼核对 | 导出 PNG 看过：轮廓、4 个红孔、旋转的标注文字（"plateheight"/"bodywidth"）都在位 |

## 五、许可与合规

- `libdxfrw` = **GPLv2-or-later**（`libdxfrw.h:9`）；LibreCAD 本体 = GPLv2。**GPLv2 内核可以吃 GPLv2-or-later，两者可直接链接**——所以这里**不需要**像早先对 LibreDWG(GPLv3) 设想的那样隔离成独立进程（[2d-to-3d.md](2d-to-3d.md) §五的那条可以作废）。
- 代价是新的 `libmozcadio.so` 与本仓库里的 `libmozopenscad.so` 一样是 **GPL 派生物**：对外分发/服务化时同样要过许可这一关（以法务判断为准）。
- 需要补的文档：`docs/third-party.md` 的 LibreCAD 树（提交 `603537d`）、`3rd/libdxfrw/`（上游 2.0.0）与 `corpus/dwg/` 三个条目**都已补上**（2026-09-28）。
- Python 侧不新增第三方依赖，不存在新的 MIT/Apache 纠缠。

## 六、覆盖面与已知边界

- **DWG：R1.40–2018+**（`AC14/AC210/AC1003/AC1004/AC1006/AC1009` 走 `dwgReaderR11`，`AC1012/AC1014/AC1015`→15、`AC1018`→18、`AC1021`→21、`AC1024`→24、`AC1027`→27、`AC1032`→32）。**R2.5 之前的几个古董版本**（`MC0.0/AC1.2/AC1.50/AC1002`）没有解析器，会明确报"没有可用的读取器"而不是静静地读成空图。所以原计划里给 DWG 留的 ODA 转换器兜底**不再是必需**（用户自装那条通道仍可作为极端情况的备用）。
- **DWG 成熟度**：上游自述不完整，`dwgR::read` 是"尽力而为 + 错误码"；所以 DWG 通路按"尽力"定位，报告里如实给告警，不承诺与 AutoCAD 一致。
- **双曲线**：libdxfrw/DXF 都拿不到（LibreCAD 的 `LC_Hyperbola` 过滤器从不创建）；抛物线只在"3 控制点 2 次样条"这种特殊形态下才存在——我们的模型**按通用 NURBS/样条**收，反而比 LibreCAD 的降级更完整。
- **文字**：只取字符串与样式，不做字形（渲染用系统字体；与 `moz_dxf` 的"文字不进几何"策略一致）。
- **剖面线**：拿图案名与边界环，不做填充求值（渲染可回退成"只画边界"）。
- **代理对象/图片/ACIS 实体**：拿不到细节，记进 `unsupported` 并计数。
- **单位**：DXF/DWG 的 `$INSUNITS` 仍是那个"模板默认值"陷阱（[2d-to-3d.md](2d-to-3d.md) §三.4），沿用现有 `unit_policy` 处理。

## 七、DWG 验证样本（已解决，2026-09-28）

原来仓库里**一个 DWG 都没有**（`find . -name '*.dwg'` = 0）。照 DXF 语料的做法抓了两批公开样本，
落在 `corpus/dwg/`（**仅开发期回归，不进 wheel**），抓取脚本 `scripts/fetch_dwg_samples.py`：

1. **ACadSharp（MIT）**：同一张图的 `sample_AC1014/1015/1018/1021/1024/1027.dwg` 版本阶梯——
   正好一次覆盖 `dwgReader15/18/21/24/27`；另加动态块与地理定位两个 AC1032 专项；
2. **LibreCAD/libdxfrw（GPLv2-or-later）**：解析库自己的 `tests/fixtures/dwg/`（按版本命名 +
   ANSI932 编码页 + 多边形/径向标注/富文本）；
3. LibreDWG（GPLv3）类的来源按原计划**只做本地验证、不入库**，这次没用到。

实测结果与逐个体量见 `corpus/dwg/README.md`：**16 个样本全通**（含 AC1032）。

## 八、风险

- **DWG 解析质量**是最大不确定性（版本、编码页、特殊实体）→ 用"报告 + 人确认"的既有姿态兜底，不静默；
- **两套 DXF 路径并存**（ezdxf 与 libdxfrw）可能给出不同结果 → 明确分工：**ezdxf 是 DXF 主路径**（P1 全套语义与 206 文件回归都在它上面），libdxfrw 负责 DWG，DXF 只做交叉校验，避免"两套语义互相打架"；
- **许可**：GPL 派生库的对外分发义务（与现状同类，非新增风险，但要在文档里说清）；
- **上游在快速演进**：我们 vendored 的是 2.0.0（commit `25a2f8d`），它比 LibreCAD 树里的拷贝新得多——好处是覆盖面广，代价是**升级要跟**（上游还在加读取器与修 DWG 细节）。所以 C ABI 边界要留干净：driver 只依赖 `DRW_Interface`，换实现不动 Python 侧（实测：0.5.11 → 2.0.0 的迁移，driver 一行没改就编过）。

## 九、需要拍板的决策点

**已全部拍板并落地（2026-09-28，用户授权"四件事全部做了"）**：

1. DWG 样本 → **我抓公开的**（ACadSharp MIT + libdxfrw GPLv2-or-later），落在 `corpus/dwg/`（§七 已写清）；
2. `docs/third-party.md` → **已补** LibreCAD 树、`3rd/libdxfrw/`、`corpus/dwg/` 三个条目；
3. 预览器直画 → **渲染层只认规范化模型**，两条解析路径都喂它（N2 里 DXF 还会带 ezdxf 兜底：libdxfrw 读不了的文件换 ezdxf 试，因为实测有二进制 DXF 它在对象段上失败）；
4. N2 入口 → **单独一个 `moz-cadview` 命令行**（`py/moz_cadview.py`），看图与建模分开。