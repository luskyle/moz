/*
 * moz_cadio.h — C ABI 封装 libdxfrw（DXF/DWG → 裸图元）
 *
 * 编译进 libmozcadio.so，供 moz 项目的 Python 绑定（moz_cadio）调用。
 * libdxfrw 是**上游 2.0.0**（vendored 在 `3rd/libdxfrw/`，commit 25a2f8d，见 docs/third-party.md）——
 * 纯 C++、不依赖 Qt 与 zlib；本文件只暴露 POD 数据，不暴露任何 C++ 类型。
 *
 * 约定（读取时已统一，不要在下游再猜）：
 *   - 坐标一律是 `read(iface, /*ext* / true)` 之后的坐标（与 LibreCAD 一致：把带 extrusion
 *     的实体换算到平面，等同 `rs_filterdxfrw.cpp:175/194` 的调用）；
 *   - **角度一律是弧度**（libdxfrw 里 `DRW_Text::angle` 是度、`DRW_Insert::angle` 是弧度，
 *     这里统一成弧度）；
 *   - `aci` 用 DXF 约定：0 = BYBLOCK，256 = BYLAYER，其余是 ACI 号；
 *   - 所有 `const char*` / `const double*` 都是**借用指针**，生命周期到 `moz_cad_free()` 为止。
 *
 * 与 moz_api.h 的分工：那个是几何内核（OpenSCAD），这个是图纸读取（DXF/DWG）。
 */
#ifndef MOZ_CADIO_H
#define MOZ_CADIO_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct moz_cad_file moz_cad_file;

/* --- 图元种类 ---
 * 与 DRW::ETYPE 对应，但只列我们能表达清楚的；其余进 MOZ_CAD_UNKNOWN 并计一条告警。
 */
enum moz_cad_kind {
  MOZ_CAD_UNKNOWN = 0,
  MOZ_CAD_POINT,
  MOZ_CAD_LINE,
  MOZ_CAD_RAY,        /* 有起点、单方向无限 */
  MOZ_CAD_XLINE,      /* 双向无限（构造线） */
  MOZ_CAD_CIRCLE,
  MOZ_CAD_ARC,
  MOZ_CAD_ELLIPSE,    /* 含椭圆弧（看 scalars 的起止参数角） */
  MOZ_CAD_LWPOLYLINE, /* 轻量多段线（2D + bulge） */
  MOZ_CAD_POLYLINE,   /* 老多段线（含 3D/网格，见 flags） */
  MOZ_CAD_SPLINE,
  MOZ_CAD_INSERT,     /* 块参照（展开与否由调用方决定） */
  MOZ_CAD_TEXT,
  MOZ_CAD_MTEXT,
  MOZ_CAD_DIMENSION,  /* 所有标注子类合并，用 dimtype 区分 */
  MOZ_CAD_HATCH,      /* 只给图案名与边界，不做填充求值 */
  MOZ_CAD_SOLID,
  MOZ_CAD_TRACE,
  MOZ_CAD_3DFACE,
  MOZ_CAD_LEADER,
  MOZ_CAD_IMAGE,
  MOZ_CAD_VIEWPORT,
  /* 后加的（追加在尾部，前面那些的值不动） */
  MOZ_CAD_MLEADER,    /* 多重引线：引线折点 + 文字/块内容 */
  MOZ_CAD_MLINE,      /* 多线：N 条平行线（看 loop_offsets） */
  MOZ_CAD_MESH,       /* 细分网格：线框（去重后的边，每条是两个点的环） */
  MOZ_CAD_WIPEOUT,    /* 遮罩：裁剪边界（点已映射到 WCS） */
  MOZ_CAD_UNDERLAY,   /* PDF/DGN/DWF 底图参照：裁剪边界（外部文件不渲染） */
  MOZ_CAD_SHAPE,      /* 形：字形在外部 .shx 里，只给插入点/尺寸（画位置标记） */
  MOZ_CAD_HELIX       /* 螺旋：按轴/半径/圈数/螺距采样的折线（2D 投影，丢掉 z） */
};

/* --- 图元标志位（moz_cad_entity.flags） --- */
enum moz_cad_flags {
  MOZ_CAD_FLAG_CLOSED = 1 << 0,    /* 多段线/样条闭合 */
  MOZ_CAD_FLAG_REVERSED = 1 << 1,  /* 弧/椭圆参数角方向相反（libdxfrw 的 isccw == 0） */
  MOZ_CAD_FLAG_SOLID = 1 << 2,     /* 剖面线：实体填充 */
  MOZ_CAD_FLAG_RATIONAL = 1 << 3,  /* 样条：有理（weightlist 有意义） */
  MOZ_CAD_FLAG_PERIODIC = 1 << 4,  /* 样条：周期 */
  MOZ_CAD_FLAG_MESH = 1 << 5,      /* 多段线：网格/多面网格形态（本层不展开） */
  MOZ_CAD_FLAG_HAS_TEXT = 1 << 6,  /* 标注：有文字覆盖（group 1） */
  MOZ_CAD_FLAG_TITLE = 1 << 7,     /* 文字：TEXTGEN / 特殊形态，仅作记录 */
  MOZ_CAD_FLAG_FIT_POINTS = 1 << 8, /* 样条：points 是**拟合点**（没有控制点时的降级） */
  MOZ_CAD_FLAG_APPROX = 1 << 9     /* 画出来的是**近似/占位**（IMAGE 只有边框没有像素、
                                      UNDERLAY 只有裁剪边界、WIPEOUT 只有边界没有遮罩效果、
                                      SHAPE 只有位置标记——字形在外部 .shx 里） */
};

/* --- 一个图元（POD） ---
 * 字段按 kind 解释，下表列"有意义的"字段（其余为 0 / NULL）：
 *
 *   POINT/LINE        p1 起点，p2 终点（POINT 只用 p1）
 *   RAY/XLINE         p1 起点，p2 方向点
 *   CIRCLE            p1 圆心，radius
 *   ARC               p1 圆心，radius，start_angle/end_angle（弧度），REVERSED
 *   ELLIPSE           p1 中心，p2 长轴向量末端，p3 短轴向量末端，
 *                     ratio（短/长），start_angle/end_angle 是**参数角**（弧度）
 *   LWPOLYLINE        points/bulges（x,y 交错，bulge 每顶点一个），CLOSED，elevation
 *   POLYLINE          同上（3D 网格形态见 MESH，只取顶点）
 *   SPLINE            points 控制点、knots 节点向量、weights 权重（RATIONAL 时），
 *                     degree 次数，CLOSED/PERIODIC；**没有控制点只有拟合点时** points 是拟合点，
 *                     并置 FIT_POINTS 标志（上游只给了拟合点，按它连折线是合理近似）
 *   INSERT            p1 插入点，name 块名，xscale/yscale/zscale，rotation（弧度），
 *                     colcount/rowcount/colspace/rowspace 阵列参数
 *   TEXT/MTEXT        p1 插入点，text 文字串，height 字高，rotation（弧度），
 *                     name 样式名，scalars 的 widthscale/oblique
 *   DIMENSION         dimtype（DXF group 70 原值，&7 得子类），p1 定义点、p2/p3 另两点，
 *                     text 文字覆盖（HAS_TEXT），name 是**匿名块名**（group 2，标注的线/箭头/
 *                     文字都在那个块里；块内容也在 entities 里，用 owner = 该块名归组），
 *                     rotation 文字方向
 *   HATCH             name 图案名，SOLID，points 是所有边界环摊平后的顶点（弧/椭圆/多段线
 *                     bulge 都按 16 段采样，样条跳过并计告警），环的边界看 loop_offsets
 *                     （前缀和，nloops 个）
 *   SOLID/TRACE/3DFACE  p1..p3 顶点
 *   MLEADER           points/loop_offsets 是各条引线折线（每条一段），text/height/rotation
 *                     是文字内容（HAS_TEXT 时有效，p1 = 文字位置）；块内容时 name 是内容块名、
 *                     p1 = 块插入点
 *   MLINE             name 样式名，height 是 scale；**样式查得到**时 points/loop_offsets 是
 *                     N 条平行线（每条一段），查不到时 points 只有基线、nloops = 0
 *   MESH              points/loop_offsets 是线框的边（每条边一段，两个点）
 *   WIPEOUT           points/loop_offsets 是裁剪边界（已映射到 WCS）
 *   UNDERLAY          name 是外部文件名（可能为 NULL = 定义对象没读到），p1 插入点，
 *                     rotation/xscale/yscale，points 是裁剪边界（可为空）
 *   SHAPE             p1 插入点，name 样式名，height 是比例，rotation 旋转；
 *                     字形在外部 .shx 文件里，本层不解释
 *   HELIX             p1 轴基点、p2 起点、p3 轴向量，radius/height(turns)/ratio(turnHeight)，
 *                     points 是采样出来的折线（2D 投影）
 */
typedef struct moz_cad_entity {
  int kind;              /* MOZ_CAD_* */
  int aci;               /* 0 = BYBLOCK，256 = BYLAYER，其余 = ACI 号 */
  int color24;           /* 真彩 0xRRGGBB；-1 = 未设置 */
  int space;             /* 0 = 模型空间，1 = 图纸空间 */
  int visible;           /* 0 = 不可见（DXF group 60） */
  unsigned int flags;    /* MOZ_CAD_FLAG_* 位掩码 */
  int dimtype;           /* 标注原始 dimtype（group 70） */
  int colcount, rowcount;/* INSERT 阵列 */
  int align_h, align_v;  /* TEXT/MTEXT：水平/垂直对齐（DRW_Text 的 HAlign/VAlign 原值） */
  const char *layer;     /* 图层名（借用，永不为 NULL，缺省 "0"） */
  const char *linetype;  /* 线型名（借用，NULL = 跟随图层） */
  const char *name;      /* 块名 / 样式名 / 图案名（借用，可为 NULL） */
  const char *text;      /* 文字串 / 标注文字覆盖（借用，可为 NULL） */
  const char *owner;     /* 所在块名；模型空间是空串 ""（借用，永不为 NULL） */
  double ltscale;        /* 线型比例（group 48） */
  double radius;         /* CIRCLE/ARC */
  double start_angle;    /* ARC/ELLIPSE：起始（参数）角，弧度 */
  double end_angle;      /* ARC/ELLIPSE：终止（参数）角，弧度 */
  double ratio;          /* ELLIPSE：短轴/长轴 */
  double elevation;      /* LWPOLYLINE：高程（group 38） */
  double height;         /* TEXT/MTEXT：字高 */
  double rotation;       /* INSERT/TEXT/MTEXT/DIMENSION：旋转，弧度 */
  double xscale, yscale, zscale;  /* INSERT 缩放 */
  double widthscale, oblique;     /* TEXT：宽度因子 / 倾斜角 */
  double degree;         /* SPLINE：次数 */
  double colspace, rowspace;      /* INSERT 阵列间距 */
  double p1[3], p2[3], p3[3];     /* 主点（见上表） */
  const double *points;  /* 顶点/控制点数组（x,y[,z] 交错；可 NULL） */
  int npoints;
  const double *bulges;  /* LWPOLYLINE/POLYLINE：每顶点 bulge（可 NULL） */
  const double *knots;   int nknots;
  const double *weights; int nweights;
  const int *loop_offsets;  /* HATCH：各边界环在 points 里的结束下标（前缀和），nloops 个 */
  int nloops;
} moz_cad_entity;

/* --- 图层 --- */
typedef struct moz_cad_layer {
  const char *name;      /* 借用 */
  int aci;               /* 0 = BYBLOCK，256 = BYLAYER，其余 = ACI 号 */
  int color24;           /* 真彩；-1 = 未设置 */
  const char *linetype;  /* 借用，可为 NULL */
  unsigned int flags;    /* 1 = 关闭(off)，2 = 冻结(frozen)，4 = 锁定(locked) */
  double lineweight;     /* mm；-1 = 未设置 */
} moz_cad_layer;

/* --- 块定义（块内实体在上面那张全表里，用 owner 归组） --- */
typedef struct moz_cad_block {
  const char *name;      /* 借用 */
  double base_point[3];  /* 块基点 */
  int first_entity;      /* 在全表里的起始下标 */
  int entity_count;
} moz_cad_block;

/* --- 读一个 DXF 或 DWG ---
 * 自动判别格式（DWG 看文件头版本串；二进制 DXF 由 libdxfrw 自己识别）。
 * 成功返回句柄（moz_cad_free 释放），失败返回 NULL 并填充 err（malloc，moz_str_free 释放）。
 */
moz_cad_file *moz_cad_read(const char *path, char **err);

void moz_cad_free(moz_cad_file *f);

/* 实际识别出来的格式："dxf" / "dwg"；无效句柄返回 NULL */
const char *moz_cad_format(const moz_cad_file *f);

/* 版本号串（"AC1009" … "AC1032"）；无效句柄返回 NULL */
const char *moz_cad_version(const moz_cad_file *f);

/* 图纸单位（DXF `$INSUNITS` / DWG 头里的同一项，DRW_Header::Units 原值）：
 * 0 = 未设置，1 = 英寸，4 = 毫米，5 = 厘米，6 = 米 ……；注意它常常是模板默认值而不是真实意图 */
int moz_cad_insunits(const moz_cad_file *f);

/* 图纸范围（DXF `$EXTMIN`/`$EXTMAX`）。已知返回 1 并填充两个 3 元组，未知返回 0 */
int moz_cad_extents(const moz_cad_file *f, double *min_xyz, double *max_xyz);

int moz_cad_entity_count(const moz_cad_file *f);
const moz_cad_entity *moz_cad_entity_at(const moz_cad_file *f, int index);

int moz_cad_layer_count(const moz_cad_file *f);
const moz_cad_layer *moz_cad_layer_at(const moz_cad_file *f, int index);

int moz_cad_block_count(const moz_cad_file *f);
const moz_cad_block *moz_cad_block_at(const moz_cad_file *f, int index);

/* 解析过程中的告警（不支持/可疑的内容，如"DWG 版本 AC1032 不支持"、"剖面线多环"） */
int moz_cad_warning_count(const moz_cad_file *f);
const char *moz_cad_warning_at(const moz_cad_file *f, int index);

/* 释放 moz_cad_read 的错误串（与 moz_api.h 的 moz_str_free 同义，各自 .so 内独立） */
void moz_str_free(char *s);

#ifdef __cplusplus
}
#endif

#endif /* MOZ_CADIO_H */