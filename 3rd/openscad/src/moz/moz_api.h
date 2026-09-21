/*
 * moz_api.h — C ABI 封装 OpenSCAD 2021.01 核心（解析 / 求值 / 取值 / 导出 / 渲染）
 *
 * 编译进 libmozopenscad.so，供 moz 项目的 Python 绑定（moz_openscad）调用。
 * 所有函数都是进程独立的：错误信息通过 err 返回（malloc，需 moz_str_free 释放）。
 *
 * 语义对齐基准：上游命令行 src/openscad.cc。
 *   - moz_eval_*  对应 `openscad -o <3D/2D 格式>`（F6 / $preview=false）
 *   - moz_render_* 默认对应 `openscad -o x.png`（preview 渲染器，保留 color()），
 *     renderer=MOZ_RENDER_CGAL 时对应 `openscad --render=cgal -o x.png`（无颜色）
 */
#ifndef MOZ_OPENSCAD_API_H
#define MOZ_OPENSCAD_API_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct moz_geom moz_geom;

/* --- 求值：解析 + 实例化 + 几何求值 ---
 * assignments 为 "name=value" 字符串数组（对应 OpenSCAD 的 -D 参数），可为 NULL。
 * 成功返回句柄（moz_geom_free 释放），失败返回 NULL 并填充 err。
 * path 会被解析成绝对路径后再求值，保证同目录的 import / use 能正确解析。
 */
moz_geom *moz_eval_text(const char *source, const char *const *assignments, int n_assignments, char **err);
moz_geom *moz_eval_file(const char *path, const char *const *assignments, int n_assignments, char **err);

/* --- 取值：在 source 的顶层作用域中求值一个 SCAD 表达式，返回其文本形式 ---
 * 用于 dxf_dim() / dxf_cross() / rands() / lookup() / search() / version() 等
 * 返回值的函数（这些结果无法通过几何句柄取得）。
 * 返回 malloc 字符串（moz_str_free 释放）；表达式无值或求值失败时返回 NULL 并填充 err。
 */
char *moz_eval_value(const char *source, const char *expression,
                     const char *const *assignments, int n_assignments, char **err);

/* 几何维度（上游语义：空 Nef 也是 3，空 Polygon2d 是 2）；无效句柄返回 -1 */
int moz_geom_dimension(const moz_geom *g);

/* 几何是否为空（零面积 / 零体积）；无效句柄返回 1 */
int moz_geom_is_empty(const moz_geom *g);

/* --- 几何测量 ---
 * 3D 用与 moz_export_bytes(g, "binstl") 同一条三角化路径的网格；2D 用多边形轮廓。
 * 所有量都在求值后的世界坐标上计算（导出/渲染口径一致）。
 */
typedef struct moz_measure {
  int dimension;       /* 3 / 2；空几何按上游语义仍为 3 */
  int is_empty;        /* 空几何（零面积 / 零体积）为 1 */
  double bbox_min[3];  /* 包围盒最小角（2D 的 z 恒为 0） */
  double bbox_max[3];  /* 包围盒最大角 */
  double volume;       /* 3D 体积；2D 为 NaN */
  double area;         /* 3D 表面积；2D 面积 */
  size_t facets;       /* 3D 三角面数；2D 轮廓顶点数（与 Geometry::numFacets 口径一致） */
  size_t vertices;     /* 去重后的顶点数 */
  double centroid[3];  /* 3D 体积质心；2D 面积质心（空几何为 NaN） */
} moz_measure;

/* 测量几何。成功返回 0 并填充 out；失败返回负值并填充 err。 */
int moz_geom_measure(const moz_geom *g, moz_measure *out, char **err);

/* --- 几何查询（都基于与导出一致的三角化网格） ---
 * 网格只三角化一次并缓存在句柄里，measure / triangles / face_colors / 查询共用它。
 */
/* 点是否在实体内（射线奇偶法）。*out 为 1/0；2D 或空几何为 0。 */
int moz_geom_contains_point(const moz_geom *g, double x, double y, double z, int *out, char **err);

/* 点到实体表面（三角面）的最短距离；空几何返回 -1 并填充 err。 */
int moz_geom_distance_to_surface(const moz_geom *g, double x, double y, double z, double *out, char **err);

/* 惯性张量（3D，单位密度，关于**质心**）。out 为 9 个 double，行优先 [Ixx,Ixy,Ixz, Iyx,Iyy,Iyz, Izx,Izy,Izz]。
 * 2D 或空几何返回负值报错。 */
int moz_geom_inertia(const moz_geom *g, double *out, char **err);

/* --- 消息日志 ---
 * 与 OpenSCAD 控制台文本一致（含 "ECHO: " / "WARNING: " 前缀），覆盖 echo()、
 * 警告、导出与渲染日志。返回 malloc 字符串（moz_str_free 释放）。
 * clear 非 0 时读取后清空累积日志。
 */
char *moz_geom_log(const moz_geom *g, int clear);

/* --- 导出 ---
 * format ∈ stl(ascii) / binstl / asciistl / off / amf / 3mf / dxf / svg / pdf / nef3 / nefdbg / png
 * 3D 格式要求 3D 几何，2D 格式（dxf/svg/pdf）要求 2D 几何，png 走渲染路径。
 * moz_export_bytes 的 *out 为 malloc 缓冲（moz_bytes_free 释放）。
 * 成功返回 0，失败返回负值并填充 err。
 */
int moz_export(const moz_geom *g, const char *format, const char *outfile, char **err);
int moz_export_bytes(const moz_geom *g, const char *format, unsigned char **out, size_t *out_len, char **err);

/* --- 导出选项 ---
 * 对应上游 ExportInfo 里可配置的字段。OpenSCAD 2021.01 的导出格式本身没有更多开关：
 * STL 只有 ascii/二进制之分（由 format 决定），3MF 无元数据/单位参数，
 * AMF 的 unit="millimeter" 与 producer 元数据是硬编码，PDF 会用源文档名做标题。
 * 因此这里只透出真正可配的 sourceFileName / sourceFilePath（仅 PDF 会用到）。
 * 字段为 NULL 时沿用几何句柄记住的源文档（moz_eval_file 求值的那个文件）。
 */
typedef struct moz_export_options {
  const char *source_file_name;  /* PDF 标题用的源文件名；NULL = 用几何句柄的文档名 */
  const char *source_file_path;  /* PDF 用的源文件路径；NULL = 用几何句柄的文档路径 */
} moz_export_options;

void moz_export_options_default(moz_export_options *opts);

/* 带导出选项的版本；opts 为 NULL 时与 moz_export / moz_export_bytes 等价 */
int moz_export_ex(const moz_geom *g, const char *format, const char *outfile,
                  const moz_export_options *opts, char **err);
int moz_export_bytes_ex(const moz_geom *g, const char *format, const moz_export_options *opts,
                        unsigned char **out, size_t *out_len, char **err);

/* --- 逐面颜色 ---
 * *out 为 4 字节/面（RGBA，0..255）的缓冲（moz_bytes_free 释放），回调顺序与
 * moz_export_bytes(g, "binstl") 写出的三角面一一对应（仍建议调用方校验面数一致）。
 * 颜色来自 CSG 链上的 color()；未着色的对象使用当前配色方案的材质色。
 */
int moz_geom_face_colors(const moz_geom *g, unsigned char **out, size_t *out_len, char **err);

/* 同上，但先切到指定配色方案（colorscheme 为 NULL/"" 时等价 moz_geom_face_colors）。
   未着色的对象取该配色的材质色，因此这条路径能让调用方按配色取逐面颜色。 */
int moz_geom_face_colors_ex(const moz_geom *g, const char *colorscheme,
                            unsigned char **out, size_t *out_len, char **err);

/* --- 三角化网格 ---
 * 直接给出三角面顶点，省去调用方解析 STL 字节。
 * *out 为 malloc 缓冲（moz_bytes_free 释放），每 9 个 float 一个三角面（3 个顶点，
 * 世界坐标，float32，与 binstl 同精度），*count 为三角面数。顺序与
 * moz_export_bytes(g, "binstl") 及 moz_geom_face_colors 完全一致。
 */
int moz_geom_triangles(const moz_geom *g, float **out, size_t *count, char **err);

/* --- 渲染选项 --- */
enum moz_render_mode {
  MOZ_RENDER_OPENCSG = 0,        /* 默认：preview 路径，保留 color()（等同 GUI F5） */
  MOZ_RENDER_THROWNTOGETHER = 1, /* preview 路径的另一种渲染器 */
  MOZ_RENDER_CGAL = 2            /* 上游 --render=cgal：几何渲染，无 color() */
};

enum moz_projection { MOZ_PROJECTION_PERSPECTIVE = 0, MOZ_PROJECTION_ORTHOGONAL = 1 };

typedef struct moz_render_options {
  unsigned int width;        /* 0 -> RenderSettings::img_width */
  unsigned int height;       /* 0 -> RenderSettings::img_height */
  int renderer;              /* 见 enum moz_render_mode */
  int show_faces;            /* 1 = 显示面（默认 1） */
  int show_edges;
  int show_axes;
  int show_scales;
  int show_crosshairs;
  const char *colorscheme;   /* NULL / "" = 沿用当前配色方案 */

  /* --- 相机覆盖 ---
   * has_camera 非 0 时忽略模型里的 $vpr/$vpt/$vpd/$vpf，改用下面的值；为 0 时按模型
   * 的 $vp* 或 viewall + autocenter 自动取景（与上游一致）。
   * vpr 是旋转角（度）、vpt 是目标点、vpd 是相机距离、vpf 是视场角（度，<=0 表示不改）。
   */
  int has_camera;
  double vpr[3];
  double vpt[3];
  double vpd;
  double vpf;
  int projection;            /* 见 enum moz_projection；独立于 has_camera，默认透视 */
} moz_render_options;

/* 用上游默认值填充 opts（建议 C 调用方先调用它，再覆盖需要的字段） */
void moz_render_options_default(moz_render_options *opts);

/* --- PNG 渲染 ---
 * 相机遵循模型里的 $vpr / $vpt / $vpd（与上游 camera.updateView 一致），
 * 未设置时按 viewall + autocenter 取景。
 * moz_render_png_bytes 的 *out 为 malloc 缓冲（moz_bytes_free 释放）。
 */
int moz_render_png(const moz_geom *g, const char *outfile, const moz_render_options *opts, char **err);
int moz_render_png_bytes(const moz_geom *g, const moz_render_options *opts,
                         unsigned char **out, size_t *out_len, char **err);

/* --- 文本 dump（无需几何求值） ---
 * format ∈ csg / ast / term / echo。返回 malloc 字符串（moz_str_free 释放）。
 * echo 返回本次解析 + 实例化产生的 echo() 文本（上游 -o x.echo 的输出）。
 */
char *moz_dump(const char *source, const char *docname, const char *format,
               const char *const *assignments, int n_assignments, char **err);
char *moz_dump_file(const char *path, const char *format,
                    const char *const *assignments, int n_assignments, char **err);

/* --- 动画帧 ---
 * 对应上游 `--animate N`：逐帧把 $t = frame / fps 传给模型（等价 -D "$t=..."），
 * 每帧解析 + 实例化 + 几何求值一次，然后回调。回调里拿到的是**临时句柄**，
 * 仅在本次回调期间有效，回调返回后立即被释放——不要保存它。
 * 回调返回值非 0 时提前中止（moz_eval_animation 返回已完成的帧数）。
 * frames <= 0 视为错误；fps <= 0 视为 1（与上游一致）。
 */
typedef int (*moz_frame_callback)(void *user, int frame, const moz_geom *geom);

int moz_eval_animation(const char *source, const char *const *assignments, int n_assignments,
                       int frames, double fps, moz_frame_callback callback, void *user, char **err);
int moz_eval_animation_file(const char *path, const char *const *assignments, int n_assignments,
                            int frames, double fps, moz_frame_callback callback, void *user, char **err);

/* --- 库搜索路径 ---
 * 对应上游用法 `use <lib/foo.scad>` / `import` 的库目录搜索列表
 * （上游启动时由 OPENSCADPATH + 用户库目录 + 资源 libraries 目录组成）。
 * moz_add_library_path 把目录追加进列表（相对路径会绝对化）。
 */
void moz_add_library_path(const char *path);

/* 返回当前库搜索路径，多条用路径分隔符连接（malloc 字符串，moz_str_free 释放） */
char *moz_get_library_paths(void);

/* --- 内存管理 --- */
void moz_geom_free(moz_geom *g);
void moz_str_free(char *s);
void moz_bytes_free(unsigned char *p);

#ifdef __cplusplus
}
#endif

#endif /* MOZ_OPENSCAD_API_H */