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
| `py/moz_data/libraries/MCAD/fonts.scad`（自研 drop-in） | SIL OFL 1.1 |
| `py/moz_data/fonts/MozSansSC-Regular.ttf`（自带中文字库子集） | SIL OFL 1.1（Noto Sans CJK SC 子集，见同目录 `MozSansSC-LICENSE.txt`） |
| `py/moz_data/fonts/Liberation-2.00.1/`、`color-schemes/`、`examples/`（从上游复制的副本） | 同上游：OFL 1.1 / GPLv2 例外 / CC 等（见各文件自身声明） |
| `ezdxf`（可选依赖，图纸 → 模型用） | MIT |
| `corpus/dxf/`（**仅开发期**回归语料，不进 wheel） | 各组按其上游：LibreCAD GPLv2、KiCad GPLv3、dxf-viewer/three-dxf MIT、FreeCAD-library LGPL-2.1；`local/` 为本项目作者自有图。详见 `corpus/dxf/README.md` |

`build/lib/libmozopenscad.so`（构建产物；打包时拷进 `py/moz_data/lib/` 随 wheel 分发）
是把三者的代码链成一个共享库（CGAL 例外允许链接 CGAL），因此**这个库属于 GPL 派生物**：
如果将来把 moz 做成对外服务/产品对外分发，需要先确认 GPL 义务与你们的发布方式是否相容——
这部分请以法务判断为准，本文档只陈述所依据的事实。

另外：`pyproject.toml` 目前没有 `license` 字段，若要对外发布 Python 包，建议补上并把上面的
第三方许可关系一并说明。