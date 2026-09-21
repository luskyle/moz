# 构建与运行环境

## 依赖（Ubuntu 24.04 实测；原文档环境为 22.04）

```bash
sudo apt-get install -y cmake g++ flex bison \
  libcgal-dev libgmp-dev libmpfr-dev libopencsg-dev \
  libglew-dev libdouble-conversion-dev libzip-dev lib3mf-dev libgettextpo-dev \
  libglib2.0-dev libcairo2-dev libfreetype-dev libfontconfig1-dev libharfbuzz-dev \
  libxml2-dev qtbase5-dev libeigen3-dev libboost-all-dev
```

`cmake` / `g++` / `flex` / `bison` 是构建工具链（`flex` 缺失会让 configure 直接报
`Could NOT find FLEX`）；OpenSCAD 的 lexer/parser 需要后两者。

实测环境（Ubuntu 24.04.5）：CGAL 5.6、OpenCSG 已安装并被链接（`ENABLE_OPENCSG` 已定义）、
Eigen 3.4.0、Boost 1.83、harfbuzz 8.3、fontconfig 2.15（`text()` 依赖它找字体）。
原文档的 22.04 / CGAL 5.4 组合未在本机复测——源码里的 CGAL 适配按 **≥ 5.4** 写，两版都应可用。

## 构建

```bash
bash scripts/build_moz_openscad.sh          # 等价于下面的 cmake 调用，并拷产物
JOBS=$(nproc) bash scripts/build_moz_openscad.sh   # 指定并行度
```

脚本做的事（`scripts/build_moz_openscad.sh`）：

```bash
cmake -S 3rd/openscad -B build/3rd/openscad \
  -DHEADLESS=ON -DNULLGL=OFF -DINFO=OFF -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/3rd/openscad --target mozopenscad -j"$JOBS"
# 产物：build/3rd/openscad/objects/libopenscad_moz.so → build/lib/libmozopenscad.so
```

- **首次构建**约 3~5 分钟（要编 CGAL 相关的一大批源文件）。
- **改过 `src/moz/moz_api.cc` 后增量构建**约 30 秒（实测 28 s）。
- 只改 Python 不需要重新构建。
- 产物不入库（`build/` 在 `.gitignore` 里），所以 clone 之后必须自己构建一次。

### 为什么脚本里是「先写临时文件再 mv」

脚本最后一步用原子替换而不是原地 `cp`：

```bash
cp "$BUILD/objects/libopenscad_moz.so" "$OUT/.libmozopenscad.so.tmp"
mv -f "$OUT/.libmozopenscad.so.tmp" "$OUT/libmozopenscad.so"
```

原地覆盖一个**正在被进程映射**的 `.so`，那个进程下次换页会收到 `SIGBUS`（总线错误）并直接崩掉。
实测踩过一次：一个跑了 7 分钟的验证进程在库里被覆盖后 `总线错误（核心已转储）`。
原子替换后，已加载旧库的进程继续用旧 inode，重构建不会打断它。

## 运行时环境变量

| 变量 | 作用 |
| --- | --- |
| `MOZ_OPENSCAD_LIB` | 指定 `libmozopenscad.so` 路径（优先于默认搜索） |
| `MOZ_OPENSCAD_RESOURCE_DIR` | 指定 OpenSCAD 资源目录（`color-schemes/` 等所在处，即 `3rd/openscad`） |
| `OPENSCADPATH` | 额外的库搜索路径（`use <>` / `import` 找库用），多个用 `:` 分隔 |

库搜索顺序（`moz_openscad.py` 的 `_find_lib()`）：`MOZ_OPENSCAD_LIB` → 模块同目录 →
`../build/lib/`。

`MOZ_OPENSCAD_RESOURCE_DIR` 一般**不用手设**：`moz_openscad.py` 在 import 时会按仓库布局
自动指向 `3rd/openscad`（仅当该目录里确实有 `color-schemes` 时才设）。装成 wheel 之后该目录
不存在，就需要调用方自己指定，否则：

- `render_png(..., colorscheme="Tomorrow")` 之类会退回默认配色（引擎会记一条
  `Unknown color scheme '...'` 警告）；
- `use <MCAD/fonts.scad>` 会找不到库（除非设了 `OPENSCADPATH`）。

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `libmozopenscad.so not found` | 还没构建，或路径不对；用 `MOZ_OPENSCAD_LIB` 指定 |
| `text()` 报找不到字体 | 缺 `libfontconfig1-dev` / 系统字体；或 `font=` 写了不存在的字体名 |
| `colorscheme=` 不生效 | 资源目录没定位到（见上） |
| 渲染出的 PNG 没颜色 | 用了 `renderer="cgal"`；该路径与上游 `--render=cgal` 一样是无颜色的，默认的 preview 路径才有颜色 |
| `use <MCAD/...>` 找不到 | 需要 `3rd/openscad/libraries/MCAD/fonts.scad`（见 [third-party.md](third-party.md)），或设 `OPENSCADPATH` |
| 同样的模型每次导出的字节不同 | 应该不会：CGAL 求值与导出是确定性的；若出现，先跑 `py/verify_examples.py` 对照原生行为 |
| 构建时 `generic_print_polyhedron` 相关报错 | 说明 CGAL 版本低于 5.4，需要把 `cgalutils-polyhedron.cc` 的适配改回上游写法 |