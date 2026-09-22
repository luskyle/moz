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

## 打包（pip / wheel）

`bash scripts/build_wheel.sh` 打一个**自带全部运行时数据**的平台 wheel（本机上是
`py3-none-linux_x86_64`，约 7 MB）：

| wheel 里带什么 | 位置 |
| --- | --- |
| Python 代码（含类型存根） | `moz_openscad.py` / `moz_viewer.py` / `moz_drawing.py` / `demo.py` / `moz_openscad.pyi` |
| 预编译的几何内核 | `moz_data/lib/libmozopenscad.so` |
| 配色方案（`<资源>/color-schemes/render/*.json`） | `moz_data/color-schemes/` |
| 引擎自带字体（Liberation）+ 自带中文字库 | `moz_data/fonts/` |
| SCAD 库（`use <MCAD/fonts.scad>`） | `moz_data/libraries/` |
| 示例引用的外部数据（dxf/dat/stl/png/json） | `moz_data/examples/` |

这些是从 `3rd/openscad/` 与生成脚本复制的**副本**。import 时 `moz_openscad` 会自动把
`moz_data` 设成资源目录、把 `moz_data/fonts` 追加进 `OPENSCAD_FONT_PATH`，并把 `moz_data/lib`
纳入 `.so` 搜索路径——装完即用，不需要再按仓库布局找东西：

```bash
bash scripts/build_wheel.sh                      # 缺 .so 时会自动先构建
python3 -m venv /tmp/mozvenv
/tmp/mozvenv/bin/pip install build/dist/moz_openscad-*.whl
cd /tmp && /tmp/mozvenv/bin/python <repo>/scripts/smoke_installed.py   # 打包 smoke test
```

要点：

- wheel 带**平台标签**（`py3-none-linux_x86_64` 这种）：`.so` 是纯 C ABI 动态库，不需要 `cp3xx`
  标签，但平台必须对上，所以它是「平台相关、解释器无关」的 wheel。
- `.so` 仍然依赖系统的 CGAL/OpenCSG/Qt 等动态库（这些不随 wheel 分发）：换机器装完可能要按上面的
  「依赖」再 `apt install` 一遍。做成 manylinux 自包含 wheel 是另一件事。
- `py/moz_data/lib/*.so` 是打包时从 `build/lib` 拷进来的，**不入库**（见 `.gitignore`）。

只装 Python 代码（`pip install -e .` / `pip install .`，或仓库里 `PYTHONPATH=py`）时数据都在
仓库里、能直接用；若把这些文件挪走，就按下面自己指：

| 需要什么 | 怎么给 |
| --- | --- |
| 几何库 | 先 `bash scripts/build_moz_openscad.sh`；不在仓库布局时用 `MOZ_OPENSCAD_LIB` 指到那个 `.so` |
| 数据目录（配色/字体/库/示例数据） | 仓库里自动定位 `py/moz_data`（没有则回退 `3rd/openscad`）；挪走后用 `MOZ_OPENSCAD_RESOURCE_DIR` 指过去 |
| `use <MCAD/...>` | 资源目录下的 `libraries` 会被引擎自动加进搜索路径；也可设 `OPENSCADPATH` 或用 `moz.add_library_path()` |

`.so` 搜索顺序（`moz_openscad.py` 的 `_find_lib()`）：`MOZ_OPENSCAD_LIB` → 模块同目录 →
`../build/lib/`（仓库里构建产物最新）→ `moz_data/lib/`（wheel 里唯一的一份）。

## 测试与 lint

```bash
python3 -m pytest          # 单元测试（py/tests/，需 pytest；无 .so 时整体 skip）
ruff check .               # lint（配置见 pyproject.toml）
```

## 运行时环境变量

| 变量 | 作用 |
| --- | --- |
| `MOZ_OPENSCAD_LIB` | 指定 `libmozopenscad.so` 路径（优先于默认搜索） |
| `MOZ_OPENSCAD_RESOURCE_DIR` | 指定数据目录（`color-schemes/`、`fonts/`、`libraries/` 所在处，默认 `py/moz_data`） |
| `OPENSCADPATH` | 额外的库搜索路径（`use <>` / `import` 找库用），多个用 `:` 分隔 |
| `OPENSCAD_FONT_PATH` | 额外的字体目录（import 时自动追加 `moz_data/fonts`） |

`.so` 搜索顺序（`moz_openscad.py` 的 `_find_lib()`）：`MOZ_OPENSCAD_LIB` → 模块同目录 →
`../build/lib/` → `moz_data/lib/`。

`MOZ_OPENSCAD_RESOURCE_DIR` 一般**不用手设**：`moz_openscad.py` 在 import 时会自动指向
`py/moz_data`（该目录不存在时回退到 `3rd/openscad`；两者都没有则不设）。把数据挪到别处又没设
这个变量，就会：

- `render_png(..., colorscheme="Tomorrow")` 之类退回默认配色（引擎会记一条
  `Unknown color scheme '...'` 警告）；
- `use <MCAD/fonts.scad>` 找不到库（除非用 `OPENSCADPATH` 指到它的 `libraries`）。

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `libmozopenscad.so not found` | 还没构建，或路径不对；用 `MOZ_OPENSCAD_LIB` 指定 |
| `text()` 报找不到字体 | 缺 `libfontconfig1-dev` / 系统字体；或 `font=` 写了不存在的字体名 |
| `text("中文")` 变成空心方框（**不报错**） | 该字体没有中文字形（引擎默认字体只有拉丁字形）：用 `font="Moz Sans SC"`（随包自带）或系统里的中文字体家族名 |
| `colorscheme=` 不生效 | 资源目录没定位到（见上） |
| 渲染出的 PNG 没颜色 | 用了 `renderer="cgal"`；该路径与上游 `--render=cgal` 一样是无颜色的，默认的 preview 路径才有颜色 |
| `use <MCAD/...>` 找不到 | 数据目录里的 `libraries/MCAD/fonts.scad`（自研 drop-in，只实现 `8bit_polyfont()`，见 [third-party.md](third-party.md)）；要用完整 MCAD 库就把上游文件放好并设 `OPENSCADPATH` |
| 同样的模型每次导出的字节不同 | 应该不会：CGAL 求值与导出是确定性的；若出现，先跑 `py/verify_examples.py` 对照原生行为 |
| 构建时 `generic_print_polyhedron` 相关报错 | 说明 CGAL 版本低于 5.4，需要把 `cgalutils-polyhedron.cc` 的适配改回上游写法 |