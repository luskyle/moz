"""moz 的运行时数据（随 Python 包一起分发，不放代码）。

这个包**只有数据**，给渲染与建模用；`moz_openscad.DATA_DIR` / `data_path()` 指向这里
（找不到时回退到 vendored 的 `3rd/openscad`，方便还没拷贝数据的检出）。

```
color-schemes/   引擎的配色方案：<资源基础路径>/color-schemes/render/*.json
fonts/           引擎自带字体（Liberation，默认字体靠它）+ 自带的 Moz Sans SC 中文字库
libraries/       引擎会把 <资源路径>/libraries 加进库搜索路径 → use <MCAD/...> 直接可用
examples/        示例引用的外部数据文件（dxf/dat/stl/png/json）
lib/             预编译的 libmozopenscad.so（构建 wheel 时拷进来；不入库）
```

数据来源与许可见 docs/third-party.md；`fonts/MozSansSC-*` 由
`scripts/make_cjk_subset_font.py` 生成，`libraries/MCAD/fonts.scad` 由
`scripts/gen_mcad_polyfont.py` 生成。
"""
