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

## 3rd/openscad/libraries/MCAD/fonts.scad —— MCAD 字形库

- 用途：`Old/example023.scad` 的 `use <MCAD/fonts.scad>`（用 `8bit_polyfont()` 的字形表排钟面）。
- 来源：`https://raw.githubusercontent.com/openscad/MCAD/master/fonts.scad`
  （OpenSCAD 官方 MCAD 库仓库；2026-09-21 取回，743 行 / 33 477 字节）。
- 许可：**LGPL 2.1**（文件头注明的作者与许可：Author: Andrew Plumb, License: LGPL 2.1）。
- 为什么是 `master` 而不是 2021.01 对应的 submodule commit：本仓库没有 submodule 记录，
  该文件多年未变；若要严格对齐版本，可换成 OpenSCAD 2021.01 的 `.gitmodules` 指向的 commit。
- Python 侧**不复制**这份数据：`Old/example023.py` 通过 `moz.vector("8bit_polyfont()", "use <...>")`
  让引擎自己求值拿到同一份字形表。

## 许可注意事项

| 组件 | 许可 |
| --- | --- |
| 本仓库自有代码（`py/`、`docs/`、`scripts/` 等） | Apache-2.0（见根目录 `LICENSE`） |
| `3rd/openscad/`（含我们新增的 `src/moz/`） | GPLv2 + CGAL 例外 |
| `3rd/openscad/libraries/MCAD/fonts.scad` | LGPL 2.1 |

`build/lib/libmozopenscad.so` 是把三者的代码链成一个共享库（CGAL 例外允许链接 CGAL），
因此**这个库属于 GPL 派生物**：如果将来把 moz 做成对外服务/产品对外分发，
需要先确认 GPL 义务与你们的发布方式是否相容——这部分请以法务判断为准，本文档只陈述所依据的事实。

另外：`pyproject.toml` 目前没有 `license` 字段，若要对外发布 Python 包，建议补上并把上面的
第三方许可关系一并说明。