# 第三方组件与许可

## 3rd/openscad —— OpenSCAD 内核（vendored）

- 来源：OpenSCAD 2021.01 源码（快照时间约 2021-02-01），**直接以源码形式 vendored**，
  没有用 submodule、没有 `.gitmodules`。
- 版本判断依据：`3rd/openscad/openscad.pro` 的 `VERSION=2021.01` / `VERSIONDATE=2021.01.31`。
  注意 `RELEASE_NOTES.md` 标题仍是 2019.05——上游发布时才更新该文件，不能据此判断版本。
- 许可：**GPLv2（带 CGAL 例外条款）**，见 `3rd/openscad/COPYING`。
- 本项目对它的改动只有 5 处（清单见 [architecture.md](architecture.md)），其余保持上游原样。
- 上游源码包里 **不含**：`tests/MCAD`（submodule）、`libraries/MCAD/*`（submodule，
  目录存在但为空）。

## 3rd/librecad —— LibreCAD 源码树（vendored）

- 来源：LibreCAD master 的整棵源码树（提交 `603537d`）：3388 文件 / 约 179 MB，**没有嵌套
  `.git`、没有 submodule**。版本依据 `CMakeLists.txt` 的 `LC_VERSION=2.2.1.1_rc`
  （它自己的 CHANGELOG 记 2.2.1-alpha，unreleased）。
- 用途：抽出它的解析核心 `libraries/libdxfrw` 编成 `libmozcadio.so` 读 **DXF/DWG**，见
  [librecad-integration.md](librecad-integration.md)。**注意**：我们最终用的是**上游 libdxfrw 2.0.0**
  （`3rd/libdxfrw/`），不是这棵树里那份 0.5.11 时代的拷贝——原因见下面 libdxfrw 一节。
  LibreCAD 本体（`librecad/`，Qt GUI）也**不参与构建**，只作参考（对照它的过滤器语义与容错）。
- 许可：**GPLv2**（`licenses/gpl-2.0.txt`）；随树分发的字体另有 OFL / MIT / KST32B，
  全文都在 `licenses/` 下。
- 这棵树**保持上游原样**（我们的 C ABI driver 不在里面，在 `3rd/libdxfrw/moz/`）。
- 注意：它自带的 `.gitignore` 会误伤 9 个**上游本已跟踪**的文件（`/*.txt` 写在
  `!/CMakeLists.txt` 之后把例外覆盖了，另有 `*generated*`、`debug/`、`*.rc`、`/dotfiles`），
  这些是用 `git add -f` 收进来的——少了它们就不是一份完整可构建的检出。

## 3rd/libdxfrw —— DXF/DWG 解析库（vendored，上游 2.0.0；`libmozcadio.so` 的构建源）

- 来源：上游 [LibreCAD/libdxfrw](https://github.com/LibreCAD/libdxfrw) master，commit
  `25a2f8d5544d5d0311aa8fee477304b93abc877e`（`CMakeLists.txt` 里 `project(DXFRW VERSION 2.0.0)`）。
  vendored 的是它的 `src/`（36 个 `.cpp`）+ `COPYING` + `AUTHORS`/`ChangeLog`/`NEWS` +
  它自己的源清单 `libdxfrw_sources.cmake` + `LIBRECAD_SYNC.md`；我们的 driver 在 `moz/` 下。
- **纯 C++，不依赖 Qt、不依赖 zlib**（DWG 解压是它自带的 `intern/dwgutil.*`）。
- 许可：**GPLv2-or-later**（`src/libdxfrw.h:9`）。GPLv2 的内核可以直接链接它，所以
  `libmozcadio.so` 与本仓库的 `libmozopenscad.so` 同属 **GPL 派生物**，不需要像早先对
  LibreDWG(GPLv3) 设想的那样隔离成独立进程。
- 覆盖面（实测，不是推断）：DWG 支持 **R1.40–2018+**（`AC14`/`AC210`/`AC1003`/`AC1004`/`AC1006`/
  `AC1009`→`dwgReaderR11`，`AC1012`/`AC1014`/`AC1015`→15，`AC1018`→18，`AC1021`→21，`AC1024`→24，
  `AC1027`→27，`AC1032`→32）；不支持的是 R2.5 之前的几个古董版本（`MC0.0`/`AC1.2`/`AC1.50`/`AC1002`）。
  16 个真实 DWG 样本全通，见 `corpus/dwg/README.md`。
- **为什么不用 LibreCAD 树里那份**（重要）：`3rd/librecad/libraries/libdxfrw/` 里的是 **0.5.11 时代的
  拷贝**，实测读不了 `AC1018+` 的真实 DWG（`BAD_READ_BLOCKS`/`BAD_READ_TABLES`/`BAD_READ_FILE_HEADER`）、
  AC1032 直接拒绝，而且 `sample_AC1014` 只读出 104 个实体（上游读 145 —— **它在静默丢几何**）。
  所以构建源是上游 2.0.0；LibreCAD 树里那份连同整棵 LibreCAD 只作参考实现。
- **已知的上游限制（块参照的匿名块名会被截断）**：DWG 里 INSERT 的名字取自 **block record 表**
  （`intern/dwgreader.cpp:9548` 的 `findTableName(DRW::BLOCK_RECORD, …)`），而块定义的名字在**块实体**
  那边（`addBlock()`）。查表发生在**实体到达时**，那张表可能还没填，于是名字被截成占位名（实测
  `*U19` → `*U`、`*T9` → `*T`），这类块参照查不到块定义、整块画不出来。**解法**：读完整张图后按
  「块记录句柄 → 块实体名」重查一遍（`3rd/libdxfrw/moz/moz_cadio.cc` 的 `resolve_pending()`），
  实测 16 个 DWG 样本里的块参照全部落到真实块定义上（`py/tests/test_cadio.py` 钉住了这项）。
- **已知的上游限制（DWG 标注的块名拿不到）**：`DRW_Dimension::parseDwg` 把标注的块句柄置成空句柄
  后再没填过（实测块句柄恒为 0），所以 DWG 里标注实体的块名**永远是空的**，而标注的线/箭头/文字
  都在那个匿名块里。这些块本身在文件里（`*D…`）、没被任何地方引用、几何已经是最终位置（WCS，
  实测块内点与标注定义点重合 0.000）。**解法**：绘制侧按"没被引用的 `*D` 块"整体补画，且只在
  「无名标注数 ≥ 候选块数」时才做（数量对得上才敢认定）；对不上就只报告、不猜
  （`py/moz_cadio.py` 的 `iter_draw`，面板里会写明这次补画了哪些块）。
- **我们还没画的实体族（上游会派发、`DRW_Interface` 给的是默认空实现）**：MLINE（多线）、
  HELIX（螺旋）、MLEADER（多重引线）、SHAPE（形）、MESH（网格）、SURFACE（曲面）、WIPEOUT（遮罩）、
  UNDERLAY（底图参照）、代理实体。**这些回调不是纯虚**，不覆盖就等于静默丢几何（上游确实会派发它们：
  DXF 侧 `libdxfrw.cpp:10079`/`10855`，DWG 侧 `intern/dwgreader.cpp:9904`/`10257`）。现在**统一报数量**
  （`忽略 N 个MLEADER（多重引线）` 这样进面板），`py/tests/test_cadio.py` 用手写的最小 DXF 钉住
  HELIX/MLINE 两条。实测 ACadSharp 那张版本阶梯样本每张就含 **15 个 MLEADER、3 个 MLINE、2 个 MESH、
  1 个 SHAPE、1 个 UNDERLAY、1 个 WIPEOUT**——以前全都不声不响地没了。**画出来还没做**：
  MLINE 要按样式算每条平行线的偏移（样式在 `addMLineStyle`，我们没取），MLEADER 要解析 context。
- 已知读不通的样本（都在 `py/verify_cadio.py` 的"预期读不通"清单里记名）：LibreCAD 树里的
  `screw2012binary.dxf`（对象段两个版本都读不了：0.5.11 报 `BAD_READ_SECTION`、2.0.0 报
  `BAD_READ_OBJECTS`；ezdxf 读它没问题）、`nothing-decimal-comma-separated.dxf`（小数逗号，
  上游直接拒绝——与引擎和 `py/moz_dxf.py` 态度一致）。另外 `bin_dxf_r12.dxf`（R12 二进制 DXF）
  0.5.11 读不了、**2.0.0 已经能读**（不在清单里了）。

## py/moz_data/libraries/MCAD/fonts.scad —— 自带的字形表（非上游 MCAD）

- 用途：`Old/example023.scad` 的 `use <MCAD/fonts.scad>`（用 `8bit_polyfont()` 的字形表排钟面）。
  引擎会把 `<资源路径>/libraries` 加进 SCAD 库搜索路径，所以不需要设 `OPENSCADPATH`。
- 内容：**本项目自己生成的 drop-in 实现**，只提供 `8bit_polyfont()`（返回值结构、256 项索引、
  `search()` 需要的那一列都与上游一致），由 `scripts/gen_mcad_polyfont.py` 从随引擎分发的
  `3rd/openscad/fonts/Liberation-2.00.1/ttf/LiberationSans-Regular.ttf` 生成。
- 许可：**SIL OFL 1.1**（Liberation 字体本身的许可；字形轮廓数据按同一许可）。
- 为什么不直接用上游：上游 MCAD 的 `fonts.scad` 是 **LGPL 2.1**（Andrew Plumb），项目里只需要
  它的 `8bit_polyfont()`，于是换成 OFL 的自研数据，省掉唯一一处 LGPL 依赖。代价是字形观感
  与上游不同（真字形轮廓 vs 上游的方块笔画），且上游那份文件里的 `polytext()` / `outline_2d()` /
  `braille_*` 没有实现——需要完整 MCAD 就把上游文件放进这个 `libraries` 目录。
- Python 侧**不复制**这份数据：`Old/example023.py` 通过 `moz.vector("8bit_polyfont()", "use <...>")`
  让引擎自己求值拿到同一份字形表。

## py/moz_data/fonts —— 自带的中文字库子集

- 文件：`MozSansSC-Regular.ttf`（2.9 MB）+ 同目录 `MozSansSC-LICENSE.txt`（OFL 1.1 全文）。
- 来源：`Noto Sans CJK SC` 的子集（字符集裁剪、名字改写，字形轮廓未改动），由
  `scripts/make_cjk_subset_font.py` 生成；包含 ASCII、Latin-1、常用标点/符号、全角形式与
  GB2312 一级+二级汉字（6763 字）。
- 许可：**SIL OFL 1.1**（可商用、可再分发；改名为 `Moz Sans SC` 以避开与系统完整 Noto 抢名字——
  `moz_drawing.TEXT_FONT` 默认用它，保证任何机器上渲染一致）。
- 为什么自带：引擎按「家族名」向 fontconfig 要字体，机器上没有中文字体时 `text()` **不报错**，
  只会静默画出空心方框（引擎内置的默认字体 `Liberation Sans:style=Regular` 只有拉丁字形）。
  同目录还有从 `3rd/openscad/fonts/` 复制的引擎自带字体（Liberation 等）；`py/moz_openscad.py`
  在 import 时把整个 `fonts/` 追加进 `OPENSCAD_FONT_PATH`，任何机器上都能出中文。
- 这些字体都随 wheel 分发（`moz_data/fonts/`），随包分发的还有 `color-schemes/`（OpenSCAD 配色方案，
  上游同许可 GPLv2 例外之外无额外限制）、`examples/`（上游示例的外部数据文件）与
  `lib/libmozopenscad.so`（GPL 派生物，见下）。

## 许可注意事项

| 组件 | 许可 |
| --- | --- |
| 本仓库自有代码（`py/`、`docs/`、`scripts/` 等） | Apache-2.0（见根目录 `LICENSE`） |
| `3rd/openscad/`（含我们新增的 `src/moz/`） | GPLv2 + CGAL 例外 |
| `3rd/librecad/` | GPLv2（**只作参考**，不参与构建） |
| `3rd/libdxfrw/`（上游 2.0.0，`libmozcadio.so` 的构建源；含我们新增的 `moz/`） | GPLv2-or-later |
| `py/moz_data/libraries/MCAD/fonts.scad`（自研 drop-in） | SIL OFL 1.1 |
| `py/moz_data/fonts/MozSansSC-Regular.ttf`（自带中文字库子集） | SIL OFL 1.1（Noto Sans CJK SC 子集，见同目录 `MozSansSC-LICENSE.txt`） |
| `py/moz_data/fonts/Liberation-2.00.1/`、`color-schemes/`、`examples/`（从上游复制的副本） | 同上游：OFL 1.1 / GPLv2 例外 / CC 等（见各文件自身声明） |
| `ezdxf`（可选依赖，图纸 → 模型用） | MIT |
| `corpus/dxf/`（**仅开发期**回归语料，不进 wheel） | 各组按其上游：LibreCAD GPLv2、KiCad GPLv3、QCAD GPLv3、dxf-viewer / ezdxf / dxf-parser / three-dxf MIT、FreeCAD-library LGPL-2.1；`local/` 为本项目作者自有图。详见 `corpus/dxf/README.md` |
| `corpus/dwg/`（**仅开发期**回归语料，不进 wheel） | ACadSharp MIT（版本阶梯样本）、LibreCAD/libdxfrw GPLv2-or-later（它自己的测试样本）。详见 `corpus/dwg/README.md` |

`build/lib/libmozopenscad.so`（构建产物；打包时拷进 `py/moz_data/lib/` 随 wheel 分发）
是把 OpenSCAD 核心的代码链成一个共享库（CGAL 例外允许链接 CGAL），因此**这个库属于 GPL 派生物**。
`build/lib/libmozcadio.so`（同样随 wheel 分发）链接的是 GPLv2-or-later 的 libdxfrw，**同属
GPL 派生物**。如果将来把 moz 做成对外服务/产品对外分发，需要先确认 GPL 义务与你们的发布方式
是否相容——这部分请以法务判断为准，本文档只陈述所依据的事实。

另外：`pyproject.toml` 目前没有 `license` 字段，若要对外发布 Python 包，建议补上并把上面的
第三方许可关系一并说明。