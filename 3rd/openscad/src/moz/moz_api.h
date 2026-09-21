/*
 * moz_api.h — C ABI 封装 OpenSCAD 2021.01 核心（解析 / 求值 / 导出 / 渲染）
 *
 * 编译进 libmozopenscad.so，供 moz 项目的 Python 绑定（moz_openscad）调用。
 * 所有函数都是进程独立的：错误信息通过 err 返回（malloc，需 moz_str_free 释放）。
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
 */
moz_geom *moz_eval_text(const char *source, const char *const *assignments, int n_assignments, char **err);
moz_geom *moz_eval_file(const char *path, const char *const *assignments, int n_assignments, char **err);

/* 几何维度：2 / 3；空几何返回 0；无效句柄返回 -1 */
int moz_geom_dimension(const moz_geom *g);

/* --- 导出 ---
 * format ∈ stl(ascii) / binstl / asciistl / off / amf / 3mf / dxf / svg / pdf / nef3 / nefdbg
 * 3D 格式要求 3D 几何，2D 格式（dxf/svg/pdf）要求 2D 几何。
 * moz_export_bytes 的 *out 为 malloc 缓冲（moz_bytes_free 释放）。
 * 成功返回 0，失败返回负值并填充 err。
 */
int moz_export(const moz_geom *g, const char *format, const char *outfile, char **err);
int moz_export_bytes(const moz_geom *g, const char *format, unsigned char **out, size_t *out_len, char **err);

/* --- PNG 渲染（CGAL 渲染路径） --- */
int moz_render_png(const moz_geom *g, const char *outfile, unsigned int width, unsigned int height, char **err);
int moz_render_png_bytes(const moz_geom *g, unsigned int width, unsigned int height, unsigned char **out, size_t *out_len, char **err);

/* --- 文本 dump（无需几何求值） ---
 * format ∈ csg / ast / term / echo。返回 malloc 字符串（moz_str_free 释放）。
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