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
- **已知的上游限制（DWG 标注的块名拿不到）**：标注实体本身只有 `dimtype`/定义点/文字，画标注的
  线/箭头/文字全在它的**匿名块**（`*D…`）里，而块名要靠标注的"块句柄"查。上游**有**读这个字段
  （`DRW_Dimension::parseDwgDimensionHandles` 把两个句柄都读出来），但实测这几张 ACadSharp 样本里
  那个句柄是**空句柄**（块句柄恒为 0，而同一次读出的 dimstyle 句柄是正常的 → 不是读歪了），所以
  名字确实拿不到。那些 `*D` 块本身在文件里、**没被任何地方引用**、几何已经是最终位置（WCS，
  实测块内点与标注定义点重合 0.000）。**解法**：绘制侧按"没被引用的 `*D` 块"整体补画，且只在
  「无名标注数 ≥ 候选块数」时才做（实测 11:11 对得上）；对不上就只报告、不猜
  （`py/moz_cadio.py` 的 `iter_draw`，面板里会写明这次补画了哪些块）。
- **以前静默丢掉、现在画出来了的实体族**（`DRW_Interface` 里这些回调**有默认空实现**，不覆盖就等于
  丢几何；上游确实会派发它们：DXF 侧 `libdxfrw.cpp:10079`/`10855`，DWG 侧 `intern/dwgreader.cpp:9904`/
  `10257`）：**MLINE**（多线→N 条平行线）、**MLEADER**（多重引线→引线折线+文字/内容块）、**MESH**
  （细分网格→去重后的边线框）、**WIPEOUT**（遮罩→裁剪边界）、**UNDERLAY**（PDF/DGN/DWF→裁剪边界占位）、
  **SHAPE**（形→插入点标记）、**HELIX**（螺旋→按轴/半径/圈数采样）、**IMAGE**（图片→整幅边框）。
  实测 ACadSharp 那张版本阶梯样本每张含 **15 个 MLEADER、3 个 MLINE、2 个 MESH、1 个 SHAPE、
  1 个 UNDERLAY、1 个 WIPEOUT、1 个 IMAGE**，以前全都不声不响地没了；语料里还有一张**模型空间只有
  MLEADER** 的 DXF（`dxf-parser/test__data__mleader.dxf`）以前整张判成空白，现在正常。
- **这些实体的实现细节（都实测过）**：
  - **多线的偏移量纲**：DWG 每个顶点的段参数（`DRW_MLineVertex::segParms` 的第一个值）**已经乘过
    `scale`**（实测 scale 1.5 的实体给出 ±0.75），而 MLINESTYLE 的元素偏移是样式单位、还要乘 `scale`；
    我们优先用顶点参数（两种格式都带），样式作兜底。实测三条多线展开出的两条平行线在**每个顶点**都
    恰好相隔一个 `scale` ✓。另外 R14（≤AC1014）的 DWG 布局里**没有**多线的样式句柄（上游编码器同样
    `if (version > DRW::AC1014)`）。
  - **标注的块句柄**（回看上面那条）：这几张 ACadSharp 样本的标注里块句柄是**空句柄**（块句柄读出来
    恒为 0，而 dimstyle 句柄正常——所以不是读歪了），那些 `*D` 块因此是"没人引用的"孤儿；绘制侧按
    "无名标注数 ≥ 未被引用的 `*D` 块数"整体补画，并在面板里写明。
  - **外部参照的名字是后到的**：IMAGE/UNDERLAY 实体在读实体段时来、`IMAGEDEF`/`UNDERLAYDEFINITION`
    对象在对象段才到（上游注释也这么说），所以名字要**读完再解析**（跟块名同一套路），拿到后进
    `name`（面板里能看到具体的 .jpg/.pdf 文件名）。同理 MLINESTYLE 也要等读完。
  - **MLEADER 的引线折点上游不给**（实测 15/15 只有文字，`DRW_MLeaderAnnotContext::roots` 是空的）。
    原因看文件里的类名就清楚了：这几张 ACadSharp 样本把 MLEADER 的上下文（引线几何）放在
    **`ROUNDTRIP_MLCONTEXT`**（连同 `ACAD_ROUNDTRIP_2010_MLEADER`）里——即把 2010 才有的特性用
    "round-trip 容器对象"塞进 R14/2000 格式的文件。上游能解的是 `MLEADEROBJECTCONTEXTDATA`
    （`intern/dwgreader.cpp:2721` 按语义名匹配），这个名字它匹配不上，于是当普通对象放过。
    同一张图的 **DXF** 版反而能给出引线（实测 3 个 MLEADER 各带 2–5 个折点，文字 "I am leader"），
    所以是我们的绘制路径没问题、是 DWG 那份数据源缺。记在 `docs/roadmap.md`。
- **还没画的**：SURFACE（曲面）与代理实体（上游不解其几何）——仍然**计数报出来**，不静默；
  SHAPE 的字形、IMAGE 的像素、PDF/DGN/DWF 底图内容都需要外部文件/字体，本层不解释（画占位并说明）。
- **R12 及更早的 DXF 按码页解字（moz 补丁）**：`DRW_TextCodec::setVersion` 对 AC1006/AC1009 现在
  **直接装 cp1252 表转换器**。原代码 `setCodePage("ANSI_1252", dxf=true)` 没有 1252 的表分支、
  落到"当成 UTF-8 原样过"的普通转换器——实测 `integration_tests__data__ASCII_R12.dxf` 的
  0xC4/0xDC/0xD6（ÄÜÖ）变成 U+FFFD，而且高字节被当 UTF-8 前导，把后面 `\U+` 转义的第一个反斜杠
  "吞掉"（同串 3 个转义只解出 2 个，留下字面 `\U+03B1`）。现在字节按码页解、`\U+XXXX` 全解：
  `ABCÄÜÖαβγ`、图层 `ΛΑΓΕΡÄÜÖ`（R12 时代没有 UTF-8 编码的 DXF，按码页是唯一正确解）。
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