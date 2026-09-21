# C ABI 参考（`libmozopenscad.so`）

头文件：`3rd/openscad/src/moz/moz_api.h`，实现：`moz_api.cc`。
编译目标：`add_library(mozopenscad SHARED ...)`，`OUTPUT_NAME=openscad_moz`，
构建脚本再拷成 `build/lib/libmozopenscad.so`。

**语义对齐基准是上游命令行 `src/openscad.cc`**，不是 GUI：

- `moz_eval_*` / `moz_export*` 对应 `openscad -o <3D/2D 格式>`（F6，`$preview=false`）
- `moz_render_*` 默认对应 `openscad -o x.png`（preview 渲染器，保留 `color()`）
- `moz_render_*(renderer=MOZ_RENDER_CGAL)` 对应 `openscad --render=cgal -o x.png`（无颜色）

## 通用约定

| 约定 | 说明 |
| --- | --- |
| 错误 | 失败时返回 NULL / 负值，并把 **malloc 字符串**写进 `err`（`moz_str_free` 释放）。字符串里通常是**整段引擎日志**（含 `WARNING:` / `ERROR:` 原文），比一句「失败」有用 |
| 内存所有权 | 出参缓冲（`char *` / `unsigned char *`）由被调方 malloc，调用方分别用 `moz_str_free` / `moz_bytes_free` 释放 |
| 句柄 | `moz_geom *` 由 `moz_eval_*` 创建、`moz_geom_free` 释放；为空几何时也不是 NULL（是空几何句柄，用 `moz_geom_is_empty` 判断） |
| 线程安全 | 所有入口共用一个全局互斥量**串行执行**（引擎内部有静态全局状态）；不保证并行加速 |
| 工作目录 | 求值期间会临时 `chdir` 到文档所在目录再恢复；`path` 会先绝对化，保证同目录 `import`/`use` 能解析 |
| 参数传递 | `assignments` 是 `"name=value"` 字符串数组，对应上游 `-D`（会作为命令行段追加在源码之后，`$` 开头的特殊变量也生效） |

## 求值

```c
moz_geom *moz_eval_text(const char *source, const char *const *assignments, int n, char **err);
moz_geom *moz_eval_file(const char *path,     const char *const *assignments, int n, char **err);
```

解析 + 实例化 + CGAL 几何求值，返回句柄。`moz_eval_file` 读文件后按**绝对路径**求值
（与上游一致：chdir 到文档父目录，同时保留绝对文档名）。

```c
int moz_geom_dimension(const moz_geom *g);   /* 上游语义：空 Nef 也是 3，空 Polygon2d 是 2；无效句柄 -1 */
int moz_geom_is_empty(const moz_geom *g);    /* 空几何（零面积/零体积）返回 1；无效句柄也返回 1 */
```

注意 `dimension` 是**上游语义**：`Functions/echo.scad` 这种没有几何的模型 `dimension == 3`
且 `is_empty == 1`。要判断「有没有东西」请用 `moz_geom_is_empty`。

## 取值

```c
char *moz_eval_value(const char *source, const char *expression,
                     const char *const *assignments, int n, char **err);
```

在 `source` 的顶层作用域里求值一个 **SCAD 表达式**，返回它的文本形式。用于那些
「有返回值、拿不到几何」的函数：`dxf_dim()` / `dxf_cross()` / `rands()` / `lookup()` /
`search()` / `version()` / 自定义 `function`。

实现方式：把一个注册进引擎的内置函数 `moz_capture(value = <表达式>)` 追加到源码顶层，
实例化阶段求值后由 C++ 侧按 **17 位有效数字**格式化（`echo()`/`str()` 只保留 6 位，
所以不能拿 echo 文本当取值通道）。

返回文本格式：数字 `%.17g`（整数值写成整数）、字符串带引号、向量 `[a, b, c]`、
`undef`、其它类型退化为引擎的 echo 文本。

表达式求值不出来时（引擎给出 `undef` 并附警告，例如未知函数、参数类型不对）返回 NULL，
`err` 里带引擎原文——**不会**回一个光秃秃的 `"undef"`。

## 日志

```c
char *moz_geom_log(const moz_geom *g, int clear);
```

返回该句柄累积的消息（`echo()`、警告、导出/渲染日志），文本与 OpenSCAD 控制台一致
（`ECHO: "x", 3` / `WARNING: ... in file ..., line N`）。`clear != 0` 时读取后清空。

求值成功但带警告时，这是唯一能看到警告的途径（上游是打到 stderr）。

## 导出

```c
int moz_export(const moz_geom *g, const char *format, const char *outfile, char **err);
int moz_export_bytes(const moz_geom *g, const char *format,
                     unsigned char **out, size_t *out_len, char **err);
```

`format`：`asciistl` / `binstl` / `stl`(等价 asciistl，上游已弃用) / `off` / `amf` / `3mf` /
`dxf` / `svg` / `pdf` / `nef3` / `nefdbg` / `png`。

- 3D 格式要求 3D 几何、2D 格式（`dxf`/`svg`/`pdf`）要求 2D 几何，不匹配会明确报错
  （上游是导出前 `checkAndExport` 检查维度）。
- 文本格式（`csg`/`ast`/`term`/`echo`）不能当导出格式用，请用 `moz_dump`。
- `png` 走渲染路径（见下），用默认渲染选项。

## 逐面颜色

```c
int moz_geom_face_colors(const moz_geom *g, unsigned char **out, size_t *out_len, char **err);
```

输出 **4 字节/面**（RGBA，0..255）的缓冲，顺序与 `moz_export_bytes(g, "binstl")` 写出的
三角面**一一对应**（调用方仍应校验 `4 * 面数 == out_len`）。

颜色来源：CSG 链上的 `color()`。判定顺序是「这个面贴在哪个对象的表面上」——与
OpenCSG 预览里各基本体分别着色的行为一致（`difference` 的切面因此取被减对象的颜色）；
贴不到任何表面时退化为「面内一点属于哪个对象」。未着色的对象取当前配色方案的材质色。

预览器用它给 GL 网格上色（见 [viewer.md](viewer.md)）。实测开销：1.6k~15.5k 面时
连同 STL 导出共 0.08~1.13 s（远小于 CGAL 求值本身）。

## 渲染

```c
enum moz_render_mode {
  MOZ_RENDER_OPENCSG = 0,        /* 默认：preview 路径，保留 color()（等同 GUI F5） */
  MOZ_RENDER_THROWNTOGETHER = 1, /* preview 路径的另一种渲染器 */
  MOZ_RENDER_CGAL = 2            /* 上游 --render=cgal：几何渲染，无 color() */
};

typedef struct moz_render_options {
  unsigned int width;        /* 0 -> RenderSettings::img_width（默认 512） */
  unsigned int height;       /* 0 -> RenderSettings::img_height（默认 512） */
  int renderer;              /* 见 enum moz_render_mode */
  int show_faces;            /* 1 = 显示面（默认 1） */
  int show_edges;
  int show_axes;
  int show_scales;
  int show_crosshairs;
  const char *colorscheme;   /* NULL / "" = 沿用当前配色方案 */
} moz_render_options;

void moz_render_options_default(moz_render_options *opts);

int moz_render_png(const moz_geom *g, const char *outfile, const moz_render_options *opts, char **err);
int moz_render_png_bytes(const moz_geom *g, const moz_render_options *opts,
                         unsigned char **out, size_t *out_len, char **err);
```

- 相机遵循模型里的 `$vpr` / `$vpt` / `$vpd` / `$vpf`（等价上游 `camera.updateView`）；
  没有 `$vp*` 时按 `viewall + autocenter` 自动取景。顺序与上游一致：先设
  `viewall/autocenter` 再 `updateView`，这样 `$vp*` 才能把自动取景关掉。
- preview 路径用 `$preview=true` 重新实例化节点树（与上游 `canPreview()` 分支一致），
  因此 `%` 背景对象、`#` 高亮、`render()` 的预览语义都与 F6 不同。
- `colorscheme` 取值来自 `<资源目录>/color-schemes/render/*.json` 里的名字
  （如 `Cornfield`、`Tomorrow`、`Starnight`）；找不到时记一条警告并沿用当前配色。
  资源目录的定位见 [build.md](build.md)。
- `show_*` 为假时对应上游 `ViewOptions` 的同名开关；`show_faces=0` 等价上游的 `wireframe`。

## 文本 dump

```c
char *moz_dump(const char *source, const char *docname, const char *format,
               const char *const *assignments, int n, char **err);
char *moz_dump_file(const char *path, const char *format,
                    const char *const *assignments, int n, char **err);
```

`format`：`csg` / `ast` / `term` / `echo`。前三个与上游 `-o x.csg` / `x.ast` / `x.term`
是同一条代码路径（`Tree::getString` / `root_module->dump("")` /
`CSGTreeEvaluator::buildCSGTree(...)->dump()`），不需要几何求值。
`echo` 返回解析 + 实例化过程中 `echo()` 输出的文本（等价上游 `-o x.echo`）。

## 内存管理

```c
void moz_geom_free(moz_geom *g);
void moz_str_free(char *s);
void moz_bytes_free(unsigned char *p);
```

## 与上游的已知差异（有意保留）

| 项 | 说明 |
| --- | --- |
| `dump` 里的文件路径 | 我们统一先绝对化文档路径，所以 `ast`/`csg` 文本里的路径是绝对路径；上游回显你传入的写法 |
| `echo` 格式 | 只回 echo 文本行，不回其它日志（上游是写到 stdout/`.echo` 文件） |
| PNG 默认尺寸 | 未指定时用 `RenderSettings` 默认（512×512）；上游命令行默认同源，但 GUI 里是另一个值 |
| 空几何维度 | 与上游一致（空 Nef 仍是 3），另提供 `moz_geom_is_empty` 便于判断 |
| 维度校验 | 导出前做维度匹配检查（3D 格式 ↔ 3D 几何），上游在同位置检查，行为一致但错误码是我们定义的负值 |