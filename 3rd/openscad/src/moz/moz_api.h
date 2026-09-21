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

/* --- 逐面颜色 ---
 * *out 为 4 字节/面（RGBA，0..255）的缓冲（moz_bytes_free 释放），回调顺序与
 * moz_export_bytes(g, "binstl") 写出的三角面一一对应（仍建议调用方校验面数一致）。
 * 颜色来自 CSG 链上的 color()；未着色的对象使用当前配色方案的材质色。
 */
int moz_geom_face_colors(const moz_geom *g, unsigned char **out, size_t *out_len, char **err);

/* --- 渲染选项 --- */
enum moz_render_mode {
  MOZ_RENDER_OPENCSG = 0,        /* 默认：preview 路径，保留 color()（等同 GUI F5） */
  MOZ_RENDER_THROWNTOGETHER = 1, /* preview 路径的另一种渲染器 */
  MOZ_RENDER_CGAL = 2            /* 上游 --render=cgal：几何渲染，无 color() */
};

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

/* --- 内存管理 --- */
void moz_geom_free(moz_geom *g);
void moz_str_free(char *s);
void moz_bytes_free(unsigned char *p);

#ifdef __cplusplus
}
#endif

#endif /* MOZ_OPENSCAD_API_H */