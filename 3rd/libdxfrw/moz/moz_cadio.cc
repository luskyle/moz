/*
 * moz_cadio.cc — libdxfrw → C ABI（见 moz_cadio.h）
 *
 * 一个 DRW_Interface 收集器：把 libdxfrw 的回调收成稳定的 POD 记录数组。
 * 不做离散化（除了剖面线边界，那是显示用的近似，且会记告警），几何语义留给 Python 侧。
 *
 * 读取参数与 LibreCAD 一致：`read(iface, true)`——把带 extrusion 的实体换算到平面
 * （见 3rd/librecad/librecad/src/lib/filters/rs_filterdxfrw.cpp:175/194）。
 */
#include "moz_cadio.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <set>
#include <utility>
#include <string>
#include <unordered_map>
#include <vector>

#include "drw_base.h"
#include "drw_entities.h"
#include "drw_header.h"
#include "drw_interface.h"
#include "drw_objects.h"
#include "libdwgr.h"
#include "libdxfrw.h"

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kDegToRad = kPi / 180.0;
/* 剖面线边界的曲线采样段数：只影响显示（填充本身我们不求值） */
constexpr int kHatchParts = 16;
/* 螺旋（HELIX）每圈采 48 段，总段数封顶（避免圈数很大时点数爆炸） */
constexpr int kHelixPartsPerTurn = 48;
constexpr int kHelixMaxParts = 2048;
/* 剖面线边界的样条段采样段数上限（段数 = max(16, 8×控制点数)，与 py/moz_cadio.py 的
   spline_points 口径一致） */
constexpr int kSplineMaxParts = 2048;

/* DRW::Version → "AC1015" 这样的串（Python 侧要用它判断 DWG 覆盖面） */
std::string version_name(DRW::Version v) {
  switch (v) {
    case DRW::MC00: return "MC0.0";
    case DRW::AC12: return "AC1.2";
    case DRW::AC14: return "AC1.4";
    case DRW::AC150: return "AC1.50";
    case DRW::AC210: return "AC2.10";
    case DRW::AC1002: return "AC1002";
    case DRW::AC1003: return "AC1003";
    case DRW::AC1004: return "AC1004";
    case DRW::AC1006: return "AC1006";
    case DRW::AC1009: return "AC1009";
    case DRW::AC1012: return "AC1012";
    case DRW::AC1014: return "AC1014";
    case DRW::AC1015: return "AC1015";
    case DRW::AC1018: return "AC1018";
    case DRW::AC1021: return "AC1021";
    case DRW::AC1024: return "AC1024";
    case DRW::AC1027: return "AC1027";
    case DRW::AC1032: return "AC1032";
    default: return "UNKNOWN";
  }
}

/* DWG 支持面（与上游 src/libdwgr.cpp 的 createReaderForVersion 一致）：
 * R1.40–2018+；明确不支持的都是古董版本（R2.5 之前的几个，上游没有可验证的样本） */
constexpr const char *kDwgSupported[] = {"AC14",   "AC210",  "AC1003", "AC1004", "AC1006",
                                         "AC1009", "AC1012", "AC1014", "AC1015", "AC1018",
                                         "AC1021", "AC1024", "AC1027", "AC1032"};
/* 所有 DWG 版本串（用来判别"这是不是 DWG"，含不支持的版本） */
constexpr const char *kDwgAll[] = {"MC0.0", "AC1.2", "AC1.4", "AC1.50", "AC2.10", "AC1002",
                                   "AC1003", "AC1004", "AC1006", "AC1009", "AC1012", "AC1014",
                                   "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"};

std::string sniff_dwg_version(const char *path) {
  std::FILE *fp = std::fopen(path, "rb");
  if (!fp) return "";
  char head[7] = {0};
  size_t got = std::fread(head, 1, 6, fp);
  std::fclose(fp);
  if (got < 5) return "";
  head[got] = '\0';
  for (const char *v : kDwgAll) {
    if (std::strcmp(head, v) == 0) return v;
  }
  return "";
}

bool dwg_version_supported(const std::string &v) {
  for (const char *s : kDwgSupported) {
    if (v == s) return true;
  }
  return false;
}

std::string error_name(DRW::error e) {
  switch (e) {
    case DRW::BAD_NONE: return "BAD_NONE";
    case DRW::BAD_UNKNOWN: return "BAD_UNKNOWN";
    case DRW::BAD_OPEN: return "BAD_OPEN";
    case DRW::BAD_VERSION: return "BAD_VERSION";
    case DRW::BAD_READ_METADATA: return "BAD_READ_METADATA";
    case DRW::BAD_READ_FILE_HEADER: return "BAD_READ_FILE_HEADER";
    case DRW::BAD_READ_HEADER: return "BAD_READ_HEADER";
    case DRW::BAD_READ_HANDLES: return "BAD_READ_HANDLES";
    case DRW::BAD_READ_CLASSES: return "BAD_READ_CLASSES";
    case DRW::BAD_READ_TABLES: return "BAD_READ_TABLES";
    case DRW::BAD_READ_BLOCKS: return "BAD_READ_BLOCKS";
    case DRW::BAD_READ_ENTITIES: return "BAD_READ_ENTITIES";
    case DRW::BAD_READ_OBJECTS: return "BAD_READ_OBJECTS";
    case DRW::BAD_READ_SECTION: return "BAD_READ_SECTION";
    case DRW::BAD_CODE_PARSED: return "BAD_CODE_PARSED";
  }
  return "UNKNOWN";
}

/* 借出的字符串/数组都放这里：deque 的元素地址稳定，句柄释放前一直有效 */
struct Pool {
  std::deque<std::string> strings;
  std::deque<std::vector<double>> doubles;
  std::deque<std::vector<int>> ints;

  const char *str(const std::string &s) {
    strings.push_back(s);
    return strings.back().c_str();
  }
  const char *opt(const std::string &s) { return s.empty() ? nullptr : str(s); }
  const char *optional(const char *s) { return (s && *s) ? str(s) : nullptr; }
  const double *arr(const std::vector<double> &v) {
    if (v.empty()) return nullptr;
    doubles.push_back(v);
    return doubles.back().data();
  }
  const int *iarr(const std::vector<int> &v) {
    if (v.empty()) return nullptr;
    ints.push_back(v);
    return ints.back().data();
  }
};

void set_point(double *dst, const DRW_Coord &c) {
  dst[0] = c.x;
  dst[1] = c.y;
  dst[2] = c.z;
}

void push_point(std::vector<double> &out, double x, double y) {
  out.push_back(x);
  out.push_back(y);
}

/* 圆弧采样（仅剖面线边界用） */
void sample_arc(std::vector<double> &out, const DRW_Coord &c, double r, double a0, double a1,
                int ccw) {
  double span = a1 - a0;
  if (ccw) {
    while (span <= 0.0) span += 2.0 * kPi;
  } else {
    while (span >= 0.0) span -= 2.0 * kPi;
  }
  for (int i = 0; i <= kHatchParts; ++i) {
    double a = a0 + span * static_cast<double>(i) / kHatchParts;
    push_point(out, c.x + r * std::cos(a), c.y + r * std::sin(a));
  }
}

/* 椭圆（弧）采样：中心 + 长轴向量 + 短/长比 + 起止**参数**角 */
void sample_ellipse(std::vector<double> &out, const DRW_Coord &center, const DRW_Coord &major_end,
                    double ratio, double t0, double t1, int ccw) {
  double mx = major_end.x - center.x;
  double my = major_end.y - center.y;
  double nx = -my * ratio;
  double ny = mx * ratio;
  double span = t1 - t0;
  if (ccw) {
    while (span <= 0.0) span += 2.0 * kPi;
  } else {
    while (span >= 0.0) span -= 2.0 * kPi;
  }
  for (int i = 0; i <= kHatchParts; ++i) {
    double t = t0 + span * static_cast<double>(i) / kHatchParts;
    push_point(out, center.x + mx * std::cos(t) + nx * std::sin(t),
               center.y + my * std::cos(t) + ny * std::sin(t));
  }
}

/* 多段线的 bulge 弧（bulge = tan(圆心角/4)，正数逆时针）——剖面线边界用 */
void sample_bulge(std::vector<double> &out, double x1, double y1, double x2, double y2,
                  double bulge) {
  double dx = x2 - x1;
  double dy = y2 - y1;
  double chord = std::hypot(dx, dy);
  if (bulge == 0.0 || chord <= 0.0) {
    push_point(out, x1, y1);
    return;
  }
  double theta = 4.0 * std::atan(bulge);          /* 带符号的圆心角 */
  double radius = chord / (2.0 * std::sin(theta / 2.0));
  /* 圆心：弦中点沿左法向偏移（tan(θ/2) → 0 时退化成直线） */
  double tangent = std::tan(theta / 2.0);
  double cx = (x1 + x2) / 2.0;
  double cy = (y1 + y2) / 2.0;
  if (std::fabs(tangent) > 1e-12) {
    double offset = (chord / 2.0) / tangent;
    cx += -dy / chord * offset;
    cy += dx / chord * offset;
  }
  double start = std::atan2(y1 - cy, x1 - cx);
  for (int i = 0; i <= kHatchParts; ++i) {
    double a = start + theta * static_cast<double>(i) / kHatchParts;
    push_point(out, cx + radius * std::cos(a), cy + radius * std::sin(a));
  }
}

/* 样条边界（剖面线环里）：有理 de Boor 求值采样成折线
   ——与 SPLINE 实体的采样同一个算法（py/moz_cadio.py 的 spline_points/_de_boor），
   保证"样条实体"和"剖面线边界里的样条"两条路径画出来同一条曲线。
   节点向量不合法时退回控制多边形（跟 Python 侧一致）。 */
void sample_spline_boundary(const DRW_Spline &spline, std::vector<double> &out) {
  const size_t count = spline.controllist.size();
  if (count == 0) {
    /* 只有拟合点（实测有这种图）：拟合点就在曲线上，直接连 */
    for (const auto &p : spline.fitlist) {
      if (p) push_point(out, p->x, p->y);
    }
    return;
  }
  if (count < 2) {
    if (spline.controllist[0]) push_point(out, spline.controllist[0]->x,
                                          spline.controllist[0]->y);
    return;
  }
  int degree = spline.degree;
  if (degree < 1) degree = 3;
  if (degree > static_cast<int>(count) - 1) degree = static_cast<int>(count) - 1;
  const std::vector<double> &knots = spline.knotslist;
  const bool rational = (spline.flags & 4) && spline.weightlist.size() == count;
  if (knots.size() != count + static_cast<size_t>(degree) + 1) {
    for (const auto &p : spline.controllist) {
      if (p) push_point(out, p->x, p->y);
    }
    return;                                 /* 节点数不合法：控制多边形 */
  }
  const double low = knots[degree];
  const double high = knots[count];
  if (!(high > low)) {
    for (const auto &p : spline.controllist) {
      if (p) push_point(out, p->x, p->y);
    }
    return;
  }
  int parts = std::max(16, 8 * static_cast<int>(count));
  if (parts > kSplineMaxParts) parts = kSplineMaxParts;
  /* 齐次坐标 (w*x, w*y, w)，非有理时 w=1 */
  std::vector<double> homo;
  homo.reserve(count * 3);
  for (size_t i = 0; i < count; ++i) {
    const double x = spline.controllist[i] ? spline.controllist[i]->x : 0.0;
    const double y = spline.controllist[i] ? spline.controllist[i]->y : 0.0;
    const double w = rational ? spline.weightlist[i] : 1.0;
    homo.push_back(w * x);
    homo.push_back(w * y);
    homo.push_back(w);
  }
  for (int i = 0; i <= parts; ++i) {
    const double u = low + (high - low) * static_cast<double>(i) / parts;
    int index = degree;                              /* 找 u 所在节点区间 */
    if (u >= knots[count]) {
      index = static_cast<int>(count) - 1;
    } else if (u > knots[degree]) {
      while (index < static_cast<int>(count) - 1 && u >= knots[index + 1]) ++index;
    }
    /* de Boor：先对控制点做凸组合，最后投影 */
    std::vector<double> work((static_cast<size_t>(degree) + 1) * 3);
    for (int k = 0; k <= degree; ++k) {
      const size_t j = static_cast<size_t>(index - degree + k);
      work[3 * k] = homo[3 * j];
      work[3 * k + 1] = homo[3 * j + 1];
      work[3 * k + 2] = homo[3 * j + 2];
    }
    for (int level = 1; level <= degree; ++level) {
      for (int k = degree; k >= level; --k) {
        const size_t j = static_cast<size_t>(index - degree + k);
        const double denominator =
            knots[j + static_cast<size_t>(degree) - level + 1] - knots[j];
        const double alpha = (denominator == 0.0) ? 0.0 : (u - knots[j]) / denominator;
        for (int axis = 0; axis < 3; ++axis) {
          work[3 * k + axis] = (1.0 - alpha) * work[3 * (k - 1) + axis]
                               + alpha * work[3 * k + axis];
        }
      }
    }
    double x = work[3 * degree];
    double y = work[3 * degree + 1];
    const double w = work[3 * degree + 2];
    if (w != 0.0) {
      x /= w;
      y /= w;
    }
    push_point(out, x, y);
  }
}

/* 剖面线：把各边界环摊平成点表 + 环的前缀和下标 */
void flatten_hatch(const DRW_Hatch &data, std::vector<double> &points, std::vector<int> &offsets,
                   int *curves) {
  for (const auto &loop : data.looplist) {
    if (!loop) continue;
    for (const auto &sub : loop->objlist) {
      if (!sub) continue;
      switch (sub->eType) {
        case DRW::LINE: {
          const auto *line = static_cast<const DRW_Line *>(sub.get());
          push_point(points, line->basePoint.x, line->basePoint.y);
          push_point(points, line->secPoint.x, line->secPoint.y);
          break;
        }
        case DRW::ARC: {
          const auto *arc = static_cast<const DRW_Arc *>(sub.get());
          sample_arc(points, arc->basePoint, arc->radious, arc->staangle, arc->endangle,
                     arc->isccw);
          if (curves) *curves += 1;
          break;
        }
        case DRW::ELLIPSE: {
          const auto *el = static_cast<const DRW_Ellipse *>(sub.get());
          sample_ellipse(points, el->basePoint, el->secPoint, el->ratio, el->staparam,
                         el->endparam, el->isccw);
          if (curves) *curves += 1;
          break;
        }
        case DRW::LWPOLYLINE: {
          const auto *pl = static_cast<const DRW_LWPolyline *>(sub.get());
          for (size_t i = 0; i < pl->vertlist.size(); ++i) {
            const auto &v = pl->vertlist[i];
            if (!v) continue;
            const auto &next = i + 1 < pl->vertlist.size() ? pl->vertlist[i + 1] : nullptr;
            if (v->bulge == 0.0 || !next) {
              push_point(points, v->x, v->y);
              continue;
            }
            sample_bulge(points, v->x, v->y, next->x, next->y, v->bulge);
            if (curves) *curves += 1;
          }
          break;
        }
        case DRW::SPLINE: {
          const auto *spline = static_cast<const DRW_Spline *>(sub.get());
          sample_spline_boundary(*spline, points);
          if (curves) *curves += 1;
          break;
        }
        default:
          break;
      }
    }
    offsets.push_back(static_cast<int>(points.size() / 2));
  }
}

}  // namespace

/* 句柄：一个读进来的图纸 */
struct moz_cad_file {
  Pool pool;
  /* 块记录句柄 → 块实体名。
   * 为什么要这张表：DWG 里块参照的名字是"块记录句柄"查表得来的，而上游是在**实体到达时**
   * 查的——同一张图里实测有块参照拿到被截断的占位名（"*T"/"*U"），而按句柄查块实体得到的是
   * 真名（"*T9"，上游自己也注释说块实体的名字更准）。所以读完整张图后再按这张表解析一遍。 */
  std::unordered_map<int, std::string> block_entity_names;
  /* 读的时候先记账，读完再解析：块记录/块实体的到达顺序在 DWG 里不保证 */
  std::vector<std::pair<size_t, int>> pending_insert_names;   /* (实体下标, 块记录句柄) */
  /* MLINESTYLE：按名字和按句柄都能查（DWG 里实体的 styleName 常常没被解析出来，
     只有句柄；DXF 里反过来） */
  std::map<std::string, std::vector<double>> mline_offsets;
  std::map<int, std::vector<double>> mline_offsets_by_handle;
  /* 多线：样式没到之前先把每个顶点的偏移方向留着，读完再展开成 N 条平行线 */
  struct MLinePending {
    size_t index;
    std::string style;
    int handle;
    std::vector<double> miter;      /* 每顶点一个方向（已归一化；(x,y) 交错） */
  };
  std::vector<MLinePending> pending_mlines;
  /* 外部参照的文件名：IMAGE/UNDERLAY 实体先到，它们的定义对象后到（上游注释也这么说） */
  std::unordered_map<int, std::string> image_names;      /* IMAGEDEF 句柄 → 文件名 */
  std::unordered_map<int, std::string> underlay_names;   /* UNDERLAYDEFINITION 句柄 → 文件名 */
  std::vector<std::pair<size_t, int>> pending_image_names;      /* (实体下标, 句柄) */
  std::vector<std::pair<size_t, int>> pending_underlay_names;   /* (实体下标, 句柄) */
  std::string format;
  std::string version;
  int insunits = 0;
  double extmin[3] = {0.0, 0.0, 0.0};
  double extmax[3] = {0.0, 0.0, 0.0};
  bool has_extents = false;
  std::vector<moz_cad_entity> entities;
  std::vector<moz_cad_layer> layers;
  std::vector<moz_cad_block> blocks;
  std::deque<std::string> warnings;
  std::map<std::string, int> ignored;   /* 忽略计数（有序，告警可复现） */
  std::map<std::string, int> recurring; /* "来说明"类告警的计数：一张图 71 个剖面线的采样通知
                                           合成一行（现状下这些消息只会按图去重，不会真有详情） */
  std::string current_block;            /* "" 表示模型空间 */
  std::unordered_map<int, std::string> block_by_handle;
  int open_block_index = -1;

  void warn(const std::string &text) { warnings.push_back(text); }
  void ignore(const std::string &what) { ignored[what] += 1; }
  void repeat(const std::string &what) { recurring[what] += 1; }
  /* "*T"/"*U" 这种两字符匿名占位名（真名是 "*T9"/"*U19"） */
  static bool truncated_name(const char *name) {
    return name != nullptr && name[0] == '*' && name[1] != '\0' && name[2] == '\0';
  }
  /* 读完后统一解析：按块记录句柄把块实体的真名补回到块参照上 */
  void resolve_pending() {
    for (const auto &item : pending_insert_names) {
      if (item.first >= entities.size()) continue;
      const auto it = block_entity_names.find(item.second);
      if (it == block_entity_names.end() || it->second.empty()) continue;
      const char *current = entities[item.first].name;
      if (current != nullptr && !truncated_name(current)) continue;   /* 上游已经给对了 */
      entities[item.first].name = pool.str(it->second);
    }
    resolve_names(pending_image_names, image_names);
    resolve_names(pending_underlay_names, underlay_names);
    for (const MLinePending &pending : pending_mlines) {
      if (pending.index >= entities.size()) continue;
      std::vector<double> style_offsets;
      if (!mline_style_offsets(pending.handle, pending.style, style_offsets)) {
        warn("多线：样式 \"" + (pending.style.empty() ? std::string("(无名)") : pending.style) +
             "\" 没找到，文件里也没有它的 MLINESTYLE（只画了基线）");
        continue;
      }
      expand_mline(entities[pending.index], pending.miter, style_offsets, false);
    }
  }

  /* 外部参照的名字：定义对象到了就补到实体上（没到就保持 NULL，调用方看得到） */
  void resolve_names(const std::vector<std::pair<size_t, int>> &pending,
                     const std::unordered_map<int, std::string> &names) {
    for (const auto &item : pending) {
      if (item.first >= entities.size()) continue;
      const auto it = names.find(item.second);
      if (it == names.end() || it->second.empty()) continue;
      entities[item.first].name = pool.str(it->second);
    }
  }

  /* 把多线的基线 + 每顶点偏移方向展开成 N 条平行线。
     `offsets` 有两种来源、量纲不同（实测的区别）：
       - 顶点里的段参数（segParms 的第一个值）：**已经乘过 scale 了** → scaled=true
         （实测 scale 1.5 的实体给出 ±0.75，scale 2.131 的给出 0 与 −2.131）
       - MLINESTYLE 的元素偏移：是样式单位 → 还要乘实体的 scale → scaled=false */
  void expand_mline(moz_cad_entity &e, const std::vector<double> &miter,
                    const std::vector<double> &offsets, bool scaled) {
    const size_t nverts = static_cast<size_t>(e.npoints);
    if (nverts == 0 || miter.size() < nverts * 2 || offsets.empty()) return;
    const double scale = scaled ? 1.0 : ((e.height != 0.0) ? e.height : 1.0);
    std::vector<double> points;
    std::vector<int> offsets_out;
    for (double offset : offsets) {
      for (size_t i = 0; i < nverts; ++i) {
        push_point(points, e.points[i * 2] + miter[i * 2] * offset * scale,
                   e.points[i * 2 + 1] + miter[i * 2 + 1] * offset * scale);
      }
      offsets_out.push_back(static_cast<int>(points.size() / 2));
    }
    e.points = pool.arr(points);
    e.npoints = static_cast<int>(points.size() / 2);
    e.loop_offsets = pool.iarr(offsets_out);
    e.nloops = static_cast<int>(offsets_out.size());
  }

  /* 样式的元素偏移：DWG 里实体的 styleName 常常没被上游解析出来（只有句柄），
     所以按句柄查，查不到再按名字 */
  bool mline_style_offsets(int handle, const std::string &style,
                           std::vector<double> &out) const {
    auto by_handle = mline_offsets_by_handle.find(handle);
    if (by_handle != mline_offsets_by_handle.end() && !by_handle->second.empty()) {
      out = by_handle->second;
      return true;
    }
    auto by_name = mline_offsets.find(style);
    if (by_name != mline_offsets.end() && !by_name->second.empty()) {
      out = by_name->second;
      return true;
    }
    return false;
  }

  /* 螺旋的折线采样：轴基点 + 半径*(cos t*u + sin t*v) + 轴单位向量*(turnHeight*t/2π)。
     u 由"起点 − 轴基点"去掉轴分量得到，v = 轴 × u。2D 模型丢 z（垂直轴的螺旋在 xy
     上就是一个圆，斜轴的是"弹簧"投影）。 */
  void helix_points(moz_cad_entity &e, const DRW_Helix &data) {
    std::vector<double> points;
    const double radius = data.radius;
    double ax = data.axisVector.x;
    double ay = data.axisVector.y;
    double az = data.axisVector.z;
    double alen = std::sqrt(ax * ax + ay * ay + az * az);
    if (!(alen > 1e-12)) {
      ax = 0.0;
      ay = 0.0;
      az = 1.0;
      alen = 1.0;
    }
    ax /= alen;
    ay /= alen;
    az /= alen;
    /* 起点方向（去掉轴分量后归一化） */
    double ux = data.startPt.x - data.axisBasePt.x;
    double uy = data.startPt.y - data.axisBasePt.y;
    double uz = data.startPt.z - data.axisBasePt.z;
    const double along = ux * ax + uy * ay + uz * az;
    ux -= along * ax;
    uy -= along * ay;
    uz -= along * az;
    double ulen = std::sqrt(ux * ux + uy * uy + uz * uz);
    if (!(ulen > 1e-12)) {
      /* 起点落在轴上：随便取一个垂直方向 */
      ux = (std::fabs(ax) < 0.9) ? 1.0 : 0.0;
      uy = (std::fabs(ax) < 0.9) ? 0.0 : 1.0;
      uz = 0.0;
      const double dot = ux * ax + uy * ay + uz * az;
      ux -= dot * ax;
      uy -= dot * ay;
      uz -= dot * az;
      ulen = std::sqrt(ux * ux + uy * uy + uz * uz);
    }
    ux /= ulen;
    uy /= ulen;
    uz /= ulen;
    const double vx = ay * uz - az * uy;
    const double vy = az * ux - ax * uz;
    const double turns = (data.turns > 0.0) ? data.turns : 1.0;
    int parts = static_cast<int>(kHelixPartsPerTurn * turns);
    if (parts < 8) parts = 8;
    if (parts > kHelixMaxParts) parts = kHelixMaxParts;
    const double direction = data.handedness ? 1.0 : -1.0;
    for (int i = 0; i <= parts; ++i) {
      const double t = direction * 2.0 * kPi * turns * static_cast<double>(i) / parts;
      const double c = std::cos(t);
      const double s = std::sin(t);
      points.push_back(data.axisBasePt.x + radius * (c * ux + s * vx));
      points.push_back(data.axisBasePt.y + radius * (c * uy + s * vy));
    }
    e.points = pool.arr(points);
    e.npoints = static_cast<int>(points.size() / 2);
    if (e.npoints == 0 || !(radius > 0.0)) warn("螺旋：半径是 0，没有可画的几何");
  }

  void flush_ignored() {
    for (const auto &kv : ignored) {
      warn("忽略 " + std::to_string(kv.second) + " 个" + kv.first);
    }
    for (const auto &kv : recurring) {
      warn(std::to_string(kv.second) + " 个" + kv.first);
    }
  }
};

namespace {

/* 回调收集器：DRW_Interface 的所有纯虚都要实现（写侧那几个留空） */
class Collector : public DRW_Interface {
 public:
  explicit Collector(moz_cad_file &file) : f(file) {}

  /* --- 表 --- */
  void addHeader(const DRW_Header *data) override {
    if (!data) return;
    auto get_int = [&](const char *key, int *out) {
      auto it = data->vars.find(key);
      if (it == data->vars.end() || !it->second) return false;
      const DRW_Variant *v = it->second;
      if (v->type() == DRW_Variant::INTEGER) {
        *out = static_cast<int>(v->content.i);
        return true;
      }
      if (v->type() == DRW_Variant::DOUBLE) {
        *out = static_cast<int>(v->content.d);
        return true;
      }
      return false;
    };
    auto get_coord = [&](const char *key, double *out) {
      auto it = data->vars.find(key);
      if (it == data->vars.end() || !it->second) return false;
      const DRW_Variant *v = it->second;
      if (v->type() != DRW_Variant::COORD || !v->content.v) return false;
      out[0] = v->content.v->x;
      out[1] = v->content.v->y;
      out[2] = v->content.v->z;
      return true;
    };
    get_int("$INSUNITS", &f.insunits);
    /* DXF 用 ±1e20 表示"范围未设置"，照抄会得到荒唐的包围盒 */
    if (get_coord("$EXTMIN", f.extmin) && get_coord("$EXTMAX", f.extmax)) {
      f.has_extents = std::fabs(f.extmin[0]) < 1e19 && std::fabs(f.extmin[1]) < 1e19 &&
                      std::fabs(f.extmax[0]) < 1e19 && std::fabs(f.extmax[1]) < 1e19;
    }
  }

  void addLType(const DRW_LType &data) override { (void)data; }
  void addDimStyle(const DRW_Dimstyle &data) override { (void)data; }
  void addVport(const DRW_Vport &data) override { (void)data; }
  void addTextStyle(const DRW_Textstyle &data) override { (void)data; }
  void addAppId(const DRW_AppId &data) override { (void)data; }

  void addLayer(const DRW_Layer &data) override {
    moz_cad_layer layer{};
    layer.name = f.pool.str(data.name.empty() ? "0" : data.name);
    layer.color24 = data.color24;
    layer.aci = data.color < 0 ? -data.color : data.color;   /* 关图层用负色号表示 */
    layer.linetype = f.pool.optional(data.lineType.c_str());
    layer.lineweight = DRW_LW_Conv::lineWidth2dxfInt(data.lWeight);
    unsigned int flags = 0;
    if (data.color < 0) flags |= 1;              /* off */
    if (data.flags & 1) flags |= 2;              /* frozen */
    if (data.flags & 4) flags |= 4;              /* locked */
    layer.flags = flags;
    f.layers.push_back(layer);
  }

  /* --- 块 --- */
  /* addBlockRecord 不实现：上游只在 DXF 通路上调它（dxfrw 的块记录表），而 DXF 的块参照
     自带 group 2 的块名；DWG 通路根本不给这张表，所以收下来也解析不出东西。 */

  void addBlock(const DRW_Block &data) override {
    if (data.parentHandle != DRW::NoHandle && !data.name.empty()) {
      f.block_entity_names[static_cast<int>(data.parentHandle)] = data.name;
    }
    moz_cad_block block{};
    block.name = f.pool.str(data.name);
    block.base_point[0] = data.basePoint.x;
    block.base_point[1] = data.basePoint.y;
    block.base_point[2] = data.basePoint.z;
    block.first_entity = static_cast<int>(f.entities.size());
    block.entity_count = 0;
    f.blocks.push_back(block);
    f.open_block_index = static_cast<int>(f.blocks.size()) - 1;
    f.block_by_handle[static_cast<int>(data.handle)] = data.name;
    f.current_block = block_scope(data.name);
  }

  void setBlock(const int handle) override {
    auto it = f.block_by_handle.find(handle);
    if (it == f.block_by_handle.end()) {
      f.ignore("未能定位归属的 DWG 实体（setBlock 找不到块）");
      f.current_block.clear();
      return;
    }
    f.current_block = block_scope(it->second);
  }

  void endBlock() override {
    if (f.open_block_index >= 0) {
      f.blocks[static_cast<size_t>(f.open_block_index)].entity_count =
          static_cast<int>(f.entities.size()) -
          f.blocks[static_cast<size_t>(f.open_block_index)].first_entity;
      f.open_block_index = -1;
    }
    f.current_block.clear();
  }

  /* --- 图元 --- */
  void addPoint(const DRW_Point &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_POINT, data);
    set_point(e.p1, data.basePoint);
    finish(e);
  }

  void addLine(const DRW_Line &data) override { add_line_kind(MOZ_CAD_LINE, data); }
  void addRay(const DRW_Ray &data) override { add_line_kind(MOZ_CAD_RAY, data); }
  void addXline(const DRW_Xline &data) override { add_line_kind(MOZ_CAD_XLINE, data); }

  void addCircle(const DRW_Circle &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_CIRCLE, data);
    set_point(e.p1, data.basePoint);
    e.radius = data.radious;
    finish(e);
  }

  void addArc(const DRW_Arc &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_ARC, data);
    set_point(e.p1, data.basePoint);
    e.radius = data.radious;
    e.start_angle = data.staangle;
    e.end_angle = data.endangle;
    if (!data.isccw) e.flags |= MOZ_CAD_FLAG_REVERSED;
    finish(e);
  }

  void addEllipse(const DRW_Ellipse &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_ELLIPSE, data);
    set_point(e.p1, data.basePoint);
    set_point(e.p2, data.secPoint);
    double mx = data.secPoint.x - data.basePoint.x;
    double my = data.secPoint.y - data.basePoint.y;
    e.p3[0] = data.basePoint.x - my * data.ratio;
    e.p3[1] = data.basePoint.y + mx * data.ratio;
    e.ratio = data.ratio;
    e.start_angle = data.staparam;
    e.end_angle = data.endparam;
    if (!data.isccw) e.flags |= MOZ_CAD_FLAG_REVERSED;
    finish(e);
  }

  void addLWPolyline(const DRW_LWPolyline &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_LWPOLYLINE, data);
    std::vector<double> points;
    std::vector<double> bulges;
    points.reserve(data.vertlist.size() * 2);
    bulges.reserve(data.vertlist.size());
    for (const auto &v : data.vertlist) {
      if (!v) continue;
      push_point(points, v->x, v->y);
      bulges.push_back(v->bulge);
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.bulges = f.pool.arr(bulges);
    e.elevation = data.elevation;
    if (data.flags & 1) e.flags |= MOZ_CAD_FLAG_CLOSED;
    finish(e);
  }

  void addPolyline(const DRW_Polyline &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_POLYLINE, data);
    std::vector<double> points;
    std::vector<double> bulges;
    for (const auto &v : data.vertlist) {
      if (!v) continue;
      push_point(points, v->basePoint.x, v->basePoint.y);
      bulges.push_back(v->bulge);
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.bulges = f.pool.arr(bulges);
    if (data.flags & 1) e.flags |= MOZ_CAD_FLAG_CLOSED;
    if (data.flags & (8 | 16 | 64)) e.flags |= MOZ_CAD_FLAG_MESH;
    finish(e);
  }

  void addSpline(const DRW_Spline *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_SPLINE, *data);
    std::vector<double> points;
    for (const auto &c : data->controllist) {
      if (!c) continue;
      push_point(points, c->x, c->y);
    }
    if (points.empty() && !data->fitlist.empty()) {
      /* 只有拟合点（实测有这种图：控制点一个都没给）：拟合点在曲线上，按它连折线是合理近似 */
      for (const auto &c : data->fitlist) {
        if (!c) continue;
        push_point(points, c->x, c->y);
      }
      e.flags |= MOZ_CAD_FLAG_FIT_POINTS;
      f.warn("样条只有拟合点（没有控制点），按拟合点连折线近似");
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.knots = f.pool.arr(data->knotslist);
    e.nknots = static_cast<int>(data->knotslist.size());
    e.weights = f.pool.arr(data->weightlist);
    e.nweights = static_cast<int>(data->weightlist.size());
    e.degree = data->degree;
    if (data->flags & 1) e.flags |= MOZ_CAD_FLAG_CLOSED;
    if (data->flags & 2) e.flags |= MOZ_CAD_FLAG_PERIODIC;
    if (data->flags & 4) e.flags |= MOZ_CAD_FLAG_RATIONAL;
    if (data->nfit > 0 && !(e.flags & MOZ_CAD_FLAG_FIT_POINTS)) {
      f.ignore("样条的拟合点（fit points，我们没有取）");   // 有控制点时拟合点只是参考
    }
    finish(e);
  }

  void addKnot(const DRW_Entity &data) override { (void)data; }

  void addInsert(const DRW_Insert &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_INSERT, data);
    set_point(e.p1, data.basePoint);
    e.name = f.pool.str(data.name);
    if (data.blockRecH.ref != 0) {
      /* 按块记录句柄查块实体的真名：命中就立刻用（块实体的名字比上游查表得到的更可靠），
         没命中就记账，读完再解析（块表/块实体的到达顺序在 DWG 里不保证） */
      auto it = f.block_entity_names.find(static_cast<int>(data.blockRecH.ref));
      if (it != f.block_entity_names.end() && !it->second.empty()) {
        e.name = f.pool.str(it->second);
      } else {
        f.pending_insert_names.emplace_back(f.entities.size() - 1,
                                           static_cast<int>(data.blockRecH.ref));
      }
    }
    e.rotation = data.angle;                 /* 类里就是弧度 */
    e.xscale = data.xscale;
    e.yscale = data.yscale;
    e.zscale = data.zscale;
    e.colcount = data.colcount;
    e.rowcount = data.rowcount;
    e.colspace = data.colspace;
    e.rowspace = data.rowspace;
    finish(e);
  }

  void addTrace(const DRW_Trace &data) override { add_filled(MOZ_CAD_TRACE, data); }
  void addSolid(const DRW_Solid &data) override { add_filled(MOZ_CAD_SOLID, data); }
  void add3dFace(const DRW_3Dface &data) override { add_filled(MOZ_CAD_3DFACE, data); }

  void addText(const DRW_Text &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_TEXT, data);
    set_point(e.p1, data.basePoint);
    set_point(e.p2, data.secPoint);
    e.text = f.pool.str(data.text);
    e.name = f.pool.str(data.style);
    e.height = data.height;
    e.rotation = data.angle * kDegToRad;     /* 类里是度 */
    e.widthscale = data.widthscale;
    e.oblique = data.oblique * kDegToRad;
    e.align_h = static_cast<int>(data.alignH);
    e.align_v = static_cast<int>(data.alignV);
    finish(e);
  }

  void addMText(const DRW_MText &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_MTEXT, data);
    set_point(e.p1, data.basePoint);
    set_point(e.p2, data.secPoint);
    e.text = f.pool.str(data.text);
    e.name = f.pool.str(data.style);
    e.height = data.height;
    e.rotation = data.angle * kDegToRad;
    e.widthscale = data.widthscale;
    e.align_h = static_cast<int>(data.alignH);
    e.align_v = static_cast<int>(data.alignV);
    finish(e);
  }

  /* --- 标注：都用 dimtype 区分，p1/p2/p3 按子类含义填 --- */
  void addDimAlign(const DRW_DimAligned *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getDimPoint());
    set_point(e.p2, data->getDef1Point());
    set_point(e.p3, data->getDef2Point());
    dim_common(e, *data);
    finish(e);
  }

  void addDimLinear(const DRW_DimLinear *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getDimPoint());
    set_point(e.p2, data->getDef1Point());
    set_point(e.p3, data->getDef2Point());
    e.rotation = data->getAngle();
    dim_common(e, *data);
    finish(e);
  }

  void addDimRadial(const DRW_DimRadial *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getCenterPoint());
    set_point(e.p2, data->getDiameterPoint());
    e.radius = data->getLeaderLength();
    dim_common(e, *data);
    finish(e);
  }

  void addDimDiametric(const DRW_DimDiametric *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getDiameter1Point());
    set_point(e.p2, data->getDiameter2Point());
    e.radius = data->getLeaderLength();
    dim_common(e, *data);
    finish(e);
  }

  /* 角标注：code 10 = 第二条线的第二点，13/14 = 第一条线的两点，15 = 第二条线首点，16 = 标注点 */
  void addDimAngular(const DRW_DimAngular *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getSecondLine2());
    set_point(e.p2, data->getFirstLine1());
    set_point(e.p3, data->getFirstLine2());
    dim_common(e, *data);
    finish(e);
  }

  void addDimAngular3P(const DRW_DimAngular3p *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getDimPoint());
    set_point(e.p2, data->getFirstLine());
    set_point(e.p3, data->getSecondLine());
    dim_common(e, *data);
    finish(e);
  }

  void addDimOrdinate(const DRW_DimOrdinate *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_DIMENSION, *data);
    set_point(e.p1, data->getOriginPoint());
    set_point(e.p2, data->getFirstLine());
    set_point(e.p3, data->getSecondLine());
    dim_common(e, *data);
    finish(e);
  }

  void addLeader(const DRW_Leader *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_LEADER, *data);
    /* 引线的折点（上游给了 vertexlist，公开字段）——以前整条丢掉，现在按折点画 */
    std::vector<double> points;
    for (const auto &v : data->vertexlist) {
      if (!v) continue;
      push_point(points, v->x, v->y);
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.name = f.pool.str(data->style);
    if (e.npoints == 0) f.ignore("LEADER（没有顶点）");
    finish(e);
  }

  void addHatch(const DRW_Hatch *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_HATCH, *data);
    set_point(e.p1, data->basePoint);
    e.name = f.pool.str(data->name);
    if (data->solid) e.flags |= MOZ_CAD_FLAG_SOLID;
    std::vector<double> points;
    std::vector<int> offsets;
    int curves = 0;
    flatten_hatch(*data, points, offsets, &curves);
    /* 采样/跳过是"仅为显示"的说明，不应该每个剖面线来一条——一张图几十个剖面线就
       刷屏了（实测 api-cw750-details.dxf 71 条同声）。合成一行带计数。
       弧/椭圆/多段线 bulge/样条边界都会采样（样条与 SPLINE 实体同一算法）；
       "没画出来"的事另有自己的告警（如"剖面线没有边界环"）。 */
    if (curves > 0) {
      f.repeat("剖面线边界含曲线段（已采样近似，仅为显示）");
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.nloops = static_cast<int>(offsets.size());
    e.loop_offsets = f.pool.iarr(offsets);
    if (e.nloops == 0) {
      /* 实测有这情况：MPOLYGON 形态的实体填充（边界在 ACIS/MPOLYGON 数据里，我们不解），
         不能默默画个空的 */
      f.warn("剖面线没有边界环（图案 " + std::string(data->name) + "，可能是 MPOLYGON 形态）");
    }
    finish(e);
  }

  void addViewport(const DRW_Viewport &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_VIEWPORT, data);
    set_point(e.p1, data.basePoint);
    finish(e);
  }

  /* 图片/遮罩的裁剪边界：边界点是**像素坐标**，映射到 WCS 是 base + u*px + v*py
     （u/v 是"一像素"的向量，DXF 组码 11/12）。找不到边界就什么都不给。 */
  void clip_to_world(moz_cad_entity &e, const DRW_Image &data) {
    std::vector<double> points;
    for (const DRW_Coord &c : data.clipPath) {
      push_point(points, data.basePoint.x + data.secPoint.x * c.x + data.vVector.x * c.y,
                 data.basePoint.y + data.secPoint.y * c.x + data.vVector.y * c.y);
    }
    if (points.size() >= 6) push_point(points, points[0], points[1]);   /* 闭合成环 */
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.loop_offsets = (e.npoints > 0) ? f.pool.iarr({e.npoints}) : nullptr;
    e.nloops = (e.npoints > 0) ? 1 : 0;
  }

  void addImage(const DRW_Image *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_IMAGE, *data);
    set_point(e.p1, data->basePoint);
    set_point(e.p2, data->secPoint);
    /* 整幅边框（以前只画了一条边）：像素尺寸 × 一像素的 u/v 向量 */
    if (data->sizeu != 0.0 && data->sizev != 0.0) {
      std::vector<double> points;
      const double ux = data->secPoint.x * data->sizeu;
      const double uy = data->secPoint.y * data->sizeu;
      const double vx = data->vVector.x * data->sizev;
      const double vy = data->vVector.y * data->sizev;
      push_point(points, data->basePoint.x, data->basePoint.y);
      push_point(points, data->basePoint.x + ux, data->basePoint.y + uy);
      push_point(points, data->basePoint.x + ux + vx, data->basePoint.y + uy + vy);
      push_point(points, data->basePoint.x + vx, data->basePoint.y + vy);
      push_point(points, data->basePoint.x, data->basePoint.y);
      e.npoints = static_cast<int>(points.size() / 2);
      e.points = f.pool.arr(points);
      e.loop_offsets = f.pool.iarr({e.npoints});
      e.nloops = 1;
    } else {
      f.warn("图片：上游没给像素尺寸（sizeu/sizev 是 0），只画了一条边");
    }
    e.flags |= MOZ_CAD_FLAG_APPROX;      /* 只有边框，没有载入像素 */
    const size_t index = f.entities.size() - 1;
    if (data->ref != 0) {
      const int handle = static_cast<int>(data->ref);
      auto it = f.image_names.find(handle);
      if (it != f.image_names.end()) {
        e.name = f.pool.opt(it->second);
      } else {
        f.pending_image_names.emplace_back(index, handle);
      }
    }
    finish(e);
  }

  void linkImage(const DRW_ImageDef *data) override {
    if (!data || data->handle == DRW::NoHandle) return;
    f.image_names[static_cast<int>(data->handle)] = data->name;
  }
  void addComment(const char *comment) override { (void)comment; }
  void addPlotSettings(const DRW_PlotSettings *data) override { (void)data; }

  /* WIPEOUT：只有裁剪边界有意义（跟 IMAGE 共用实现）。边界点是**像素坐标**，
     映射到 WCS 是 base + u向量*px + v向量*py（u/v 是"一像素"的向量，DXF 组码 11/12）。 */
  void addWipeout(const DRW_Wipeout *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_WIPEOUT, *data);
    clip_to_world(e, *data);
    if (e.npoints < 3) {
      f.warn("遮罩：上游没给可用的裁剪边界（DWG 里边界在 image-clip 块，可能没读到）");
    } else {
      e.flags |= MOZ_CAD_FLAG_APPROX;      /* 画的是裁剪边界，遮罩效果（填充）没有 */
    }
    finish(e);
  }

  /* 底图参照（PDF/DGN/DWF）：外部文件不渲染，按上游 LibreCAD 的做法画**裁剪边界**占位；
     连裁剪边界都没有时画个十字标记（至少知道这里有个参照） */
  void addUnderlay(const DRW_Underlay *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_UNDERLAY, *data);
    set_point(e.p1, data->position);
    e.rotation = data->rotation;
    e.xscale = data->scale.x;
    e.yscale = data->scale.y;
    e.flags |= MOZ_CAD_FLAG_APPROX;
    std::vector<double> points;
    std::vector<int> offsets;
    const std::vector<DRW_Coord> &boundary = data->clipBoundary.empty()
                                                 ? data->inverseClipBoundary
                                                 : data->clipBoundary;
    if (!boundary.empty()) {
      for (const DRW_Coord &c : boundary) push_point(points, c.x, c.y);
      push_point(points, points[0], points[1]);           /* 闭合成环 */
      offsets.push_back(static_cast<int>(points.size() / 2));
    } else if (data->extPoint.x != 0.0 || data->extPoint.y != 0.0) {
      /* 没有裁剪边界：至少把参照的范围框画出来（extPoint 是相对插入点的范围） */
      push_point(points, data->position.x, data->position.y);
      push_point(points, data->position.x + data->extPoint.x, data->position.y);
      push_point(points, data->position.x + data->extPoint.x,
                 data->position.y + data->extPoint.y);
      push_point(points, data->position.x, data->position.y + data->extPoint.y);
      push_point(points, data->position.x, data->position.y);
      offsets.push_back(static_cast<int>(points.size() / 2));
    } else {
      double half = 0.5 * std::fabs(data->scale.x != 0.0 ? data->scale.x : 1.0);
      if (!(half > 1e-9)) half = 0.5;
      push_point(points, data->position.x - half, data->position.y);
      push_point(points, data->position.x + half, data->position.y);
      offsets.push_back(static_cast<int>(points.size() / 2));
      push_point(points, data->position.x, data->position.y - half);
      push_point(points, data->position.x, data->position.y + half);
      offsets.push_back(static_cast<int>(points.size() / 2));
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.loop_offsets = f.pool.iarr(offsets);
    e.nloops = static_cast<int>(offsets.size());
    const size_t index = f.entities.size() - 1;
    if (data->definitionHandle != 0) {
      const int handle = static_cast<int>(data->definitionHandle);
      auto it = f.underlay_names.find(handle);
      if (it != f.underlay_names.end()) {
        e.name = f.pool.opt(it->second);
      } else {
        f.pending_underlay_names.emplace_back(index, handle);
      }
    }
    finish(e);
  }

  void linkUnderlay(const DRW_UnderlayDefinition *data) override {
    if (!data || data->handle == DRW::NoHandle) return;
    f.underlay_names[static_cast<int>(data->handle)] = data->filename;
  }

  /* 形（SHAPE）：字形在外部 .shx 文件里（上游只存元数据，不解释字形），
     所以只能按插入点/比例画个占位标记——至少位置看得见 */
  void addShape(const DRW_Shape &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_SHAPE, data);
    set_point(e.p1, data.m_insertionPoint);
    e.name = f.pool.opt(data.m_styleName);
    e.height = data.m_scale;
    e.rotation = data.m_rotation;             /* 类里是度 */
    e.widthscale = data.m_widthFactor;
    double half = std::fabs(data.m_scale) * 0.5;
    if (!(half > 1e-9)) half = 0.5;           /* 比例没给就画个固定大小的小方块 */
    const double ca = std::cos(e.rotation);
    const double sa = std::sin(e.rotation);
    std::vector<double> points;
    for (int corner = 0; corner <= 4; ++corner) {
      const int c = corner % 4;
      const double sx = (c == 1 || c == 2) ? half : -half;
      const double sy = (c >= 2) ? half : -half;
      push_point(points, data.m_insertionPoint.x + sx * ca - sy * sa,
                 data.m_insertionPoint.y + sx * sa + sy * ca);
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.flags |= MOZ_CAD_FLAG_APPROX;
    finish(e);
  }

  /* 细分网格（MESH）：按**去重后的边**画线框（边优先，没有就按面拆边） */
  void addMesh(const DRW_Mesh &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_MESH, data);
    const int nverts = static_cast<int>(data.vertices.size());
    std::set<std::pair<int, int>> seen;
    std::vector<std::pair<int, int>> edges;
    auto add_edge = [&](int a, int b) {
      if (a < 0 || b < 0 || a >= nverts || b >= nverts || a == b) return;
      const bool ordered = a < b;
      const std::pair<int, int> key = ordered ? std::make_pair(a, b) : std::make_pair(b, a);
      if (seen.insert(key).second) edges.push_back(key);
    };
    for (const auto &edge : data.edges) add_edge(edge.first, edge.second);
    for (const auto &face : data.faces) {
      for (size_t i = 0; i < face.size(); ++i) {
        add_edge(face[i], face[(i + 1) % face.size()]);
      }
    }
    std::vector<double> points;
    std::vector<int> offsets;
    for (const auto &edge : edges) {
      push_point(points, data.vertices[static_cast<size_t>(edge.first)].x,
                 data.vertices[static_cast<size_t>(edge.first)].y);
      push_point(points, data.vertices[static_cast<size_t>(edge.second)].x,
                 data.vertices[static_cast<size_t>(edge.second)].y);
      offsets.push_back(static_cast<int>(points.size() / 2));
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.nloops = static_cast<int>(offsets.size());
    e.loop_offsets = f.pool.iarr(offsets);
    if (offsets.empty()) f.warn("网格：上游给的顶点/面里没有可画的边");
    finish(e);
  }

  /* 多重引线（MLEADER）：引线折线 + 文字或块内容 */
  void addMLeader(const DRW_MLeader *data) override {
    if (!data) return;
    const DRW_MLeaderAnnotContext &ctx = data->context;
    moz_cad_entity &e = begin(MOZ_CAD_MLEADER, *data);
    std::vector<double> points;
    std::vector<int> offsets;
    for (const DRW_MLeaderRoot &root : ctx.roots) {
      for (const DRW_MLeaderLeaderLine &line : root.leaderLines) {
        if (line.points.size() < 2) continue;
        for (const DRW_Coord &p : line.points) push_point(points, p.x, p.y);
        offsets.push_back(static_cast<int>(points.size() / 2));
      }
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.nloops = static_cast<int>(offsets.size());
    e.loop_offsets = f.pool.iarr(offsets);
    e.height = ctx.textHeight;
    if (ctx.hasTextContents) {
      e.text = f.pool.opt(ctx.textLabel);
      e.flags |= MOZ_CAD_FLAG_HAS_TEXT;
      set_point(e.p1, ctx.textLocation);
      e.rotation = ctx.textRotation;
    } else if (ctx.hasContentsBlock && ctx.blockTableRecordHandle.ref != 0) {
      /* 内容块的句柄是 BLOCK_RECORD：跟块参照一样按"块实体名"解（顺序不定 → 记账） */
      const int handle = static_cast<int>(ctx.blockTableRecordHandle.ref);
      auto it = f.block_entity_names.find(handle);
      if (it != f.block_entity_names.end() && !it->second.empty()) {
        e.name = f.pool.str(it->second);
      } else {
        f.pending_insert_names.emplace_back(f.entities.size() - 1, handle);
      }
      set_point(e.p1, ctx.blockLocation);
      e.rotation = ctx.blockRotation;
    }
    if (e.npoints == 0 && e.text == nullptr && !ctx.hasContentsBlock) {
      f.warn("多重引线：上游没给引线顶点，也没有文字/块内容");
    }
    finish(e);
  }

  /* 多线（MLINE）：N 条平行线。每条的偏移来自 MLINESTYLE 的 elements，
     方向是该顶点的 miterDir（垂直方向）。样式后到就先记账，读完再展开。 */
  void addMLineStyle(const DRW_MLineStyle &data) override {
    std::vector<double> offsets;
    for (const DRW_MLineElement &element : data.elements) offsets.push_back(element.offset);
    f.mline_offsets[data.name] = offsets;
    if (data.handle != DRW::NoHandle) {
      f.mline_offsets_by_handle[static_cast<int>(data.handle)] = offsets;
    }
  }

  void addMLine(const DRW_MLine *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_MLINE, *data);
    e.name = f.pool.opt(data->styleName);
    e.height = data->scale;                  /* 偏移要乘这个尺度 */
    std::vector<double> base;
    std::vector<double> miter;
    for (const DRW_MLineVertex &v : data->vertlist) {
      push_point(base, v.position.x, v.position.y);
      double mx = v.miterDir.x;
      double my = v.miterDir.y;
      const double len = std::hypot(mx, my);
      if (len > 0.0) {
        mx /= len;
        my /= len;
      }
      push_point(miter, mx, my);
    }
    e.npoints = static_cast<int>(base.size() / 2);
    e.points = f.pool.arr(base);
    const size_t index = f.entities.size() - 1;
    const int handle = static_cast<int>(data->styleHandle);
    /* 每条平行线的偏移：优先取**顶点里的段参数**（实体自带、已按 scale 折算过），
       其次查 MLINESTYLE（样式单位，还得乘 scale）；都没有就先记账，读完再看样式到没到 */
    std::vector<double> vertex_offsets;
    for (const DRW_MLineVertex &v : data->vertlist) {
      if (v.segParms.empty()) continue;
      for (const std::vector<double> &parms : v.segParms) {
        vertex_offsets.push_back(parms.empty() ? 0.0 : parms[0]);
      }
      break;
    }
    std::vector<double> style_offsets;
    if (!vertex_offsets.empty()) {
      f.expand_mline(e, miter, vertex_offsets, true);
    } else if (f.mline_style_offsets(handle, data->styleName, style_offsets)) {
      f.expand_mline(e, miter, style_offsets, false);
    } else {
      f.pending_mlines.push_back({index, data->styleName, handle, std::move(miter)});
    }
    if (e.npoints == 0) f.warn("多线：上游没给基线顶点");
    finish(e);
  }

  /* --- 上游会派发、我们还没画的实体 ---
     这些回调在 DRW_Interface 里**有默认空实现**，所以不覆盖就不会报错、实体直接消失；
     上游确实会派发它们（DXF: libdxfrw.cpp:10079 addMLine / 10855 addHelix；
     DWG: dwgreader.cpp:9904 / 10257）。所以至少把数量说出来，不静默画空。 */
  void addHelix(const DRW_Helix *data) override {
    /* 螺旋：上游给了轴基点/起点/轴向量/半径/圈数/螺距，可以采样成折线 */
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_HELIX, *data);
    set_point(e.p1, data->axisBasePt);
    set_point(e.p2, data->startPt);
    set_point(e.p3, data->axisVector);
    e.radius = data->radius;
    e.height = data->turns;
    e.ratio = data->turnHeight;
    e.flags |= MOZ_CAD_FLAG_APPROX;      /* 3D 实体的 2D 投影（z 分量丢了） */
    f.helix_points(e, *data);
    finish(e);
  }
  void addSurface(const DRW_Surface *data) override { (void)data; f.ignore("SURFACE（曲面）"); }
  void addProxyEntity(const DRW_ProxyEntity &data) override {
    (void)data;
    f.ignore("代理实体（上游不解其几何）");
  }
  /* ATTDEF（属性定义）不报：它在块定义里、插入时由 ATTRIB 顶替，本来就不该画出来 */

  /* --- 写侧（我们只读；这些纯虚必须实现） --- */
  void writeHeader(DRW_Header &data) override { (void)data; }
  void writeBlocks() override {}
  void writeBlockRecords() override {}
  void writeEntities() override {}
  void writeLTypes() override {}
  void writeLayers() override {}
  void writeTextstyles() override {}
  void writeVports() override {}
  void writeDimstyles() override {}
  void writeObjects() override {}
  void writeAppId() override {}

 private:
  moz_cad_file &f;

  /* 模型空间/图纸空间的块名归一成 ""（DWG 里模型空间也是一个块） */
  static std::string block_scope(const std::string &name) {
    if (name.rfind("*Model_Space", 0) == 0 || name.rfind("*Paper_Space", 0) == 0) return "";
    return name;
  }

  moz_cad_entity &begin(int kind, const DRW_Entity &src) {
    f.entities.push_back(moz_cad_entity{});
    moz_cad_entity &e = f.entities.back();
    e.kind = kind;
    e.aci = src.color;
    e.color24 = src.color24;
    e.space = (src.space == DRW::PaperSpace) ? 1 : 0;
    e.visible = src.visible ? 1 : 0;
    e.layer = f.pool.str(src.layer.empty() ? "0" : src.layer);
    e.linetype = (src.lineType.empty() || src.lineType == "BYLAYER") ? nullptr
                                                                   : f.pool.str(src.lineType);
    e.owner = f.pool.str(f.current_block);
    e.ltscale = src.ltypeScale;
    return e;
  }

  void finish(const moz_cad_entity &e) { (void)e; }

  void add_line_kind(int kind, const DRW_Line &data) {
    moz_cad_entity &e = begin(kind, data);
    set_point(e.p1, data.basePoint);
    set_point(e.p2, data.secPoint);
    finish(e);
  }

  void add_filled(int kind, const DRW_Trace &data) {
    moz_cad_entity &e = begin(kind, data);
    set_point(e.p1, data.basePoint);
    set_point(e.p2, data.secPoint);
    set_point(e.p3, data.thirdPoint);
    e.p3[2] = 0;
    finish(e);
  }

  /* 标注：dimtype + 文字覆盖（group 1）+ **匿名块名**（group 2）。
   * 块名是画标注的必需品——标注的线/箭头/文字都在那个块里（块内容也在 entities 里，用 owner 归组）；
   * 样式名（group 3）这里不暴露：最终几何已经由块固定了。 */
  void dim_common(moz_cad_entity &e, const DRW_Dimension &data) {
    e.dimtype = data.type;
    std::string text = data.getText();
    if (!text.empty() && text != "<>") {
      e.text = f.pool.str(text);
      e.flags |= MOZ_CAD_FLAG_HAS_TEXT;
    }
    /* 上游的 getName() 不是 const 成员（只是返回一个拷贝），而回调给的是 const 指针——
       去掉 const 是安全的，这个方法不改任何状态。
       DWG 里这个名字**永远是空的**：上游 DRW_Dimension::parseDwg 把块句柄置成空句柄后
       再没填过（实测：块句柄恒为 0），所以标注的匿名块名拿不到，只能由绘制侧按
       "文件里没被引用的 *D 块"补（见 py/moz_cadio.py 的 iter_draw）。 */
    e.name = f.pool.str(const_cast<DRW_Dimension &>(data).getName());
  }
};

void set_err(char **err, const std::string &text) {
  if (!err) return;
  char *copy = static_cast<char *>(std::malloc(text.size() + 1));
  if (!copy) return;
  std::memcpy(copy, text.c_str(), text.size() + 1);
  *err = copy;
}

}  // namespace

extern "C" {

moz_cad_file *moz_cad_read(const char *path, char **err) {
  if (err) *err = nullptr;
  if (!path || !*path) {
    set_err(err, "路径为空");
    return nullptr;
  }
  std::string dwg_version = sniff_dwg_version(path);
  bool is_dwg = !dwg_version.empty();
  moz_cad_file *f = new moz_cad_file();
  f->format = is_dwg ? "dwg" : "dxf";
  f->version = dwg_version;

  Collector collector(*f);
  std::string failure;
  if (is_dwg) {
    dwgR reader(path);
    bool ok = reader.read(&collector, true);
    f->version = version_name(reader.getVersion());
    if (f->version == "UNKNOWN") f->version = dwg_version;
    if (!ok) {
      std::string why = error_name(reader.getError());
      failure = "DWG 解析失败（版本 " + f->version + "：" + why + "）";
      if (why == "BAD_VERSION" || !dwg_version_supported(f->version)) {
        failure += "——这个版本没有可用的读取器（上游只支持 R1.40–2018+：AC14/AC210/AC1003/"
                   "AC1004/AC1006/AC1009/AC1012/AC1014/AC1015/AC1018/AC1021/AC1024/AC1027/"
                   "AC1032）；R2.5 及更早的几个古董版本没有解析器";
      }
    }
  } else {
    dxfRW reader(path);
    bool ok = reader.read(&collector, true);
    f->version = version_name(reader.getVersion());
    if (!ok) {
      failure = "DXF 解析失败（版本 " + f->version + "：" + error_name(reader.getError()) + "）";
      f->version = "UNKNOWN";   /* 读失败时的版本号不可信 */
    }
  }
  if (!failure.empty()) {
    delete f;
    set_err(err, failure);
    return nullptr;
  }
  f->resolve_pending();       /* 块记录/块实体名都到齐了，再把块参照的名字解析一遍 */
  f->flush_ignored();
  return f;
}

void moz_cad_free(moz_cad_file *f) { delete f; }

const char *moz_cad_format(const moz_cad_file *f) {
  return f ? f->format.c_str() : nullptr;
}

const char *moz_cad_version(const moz_cad_file *f) {
  return f ? f->version.c_str() : nullptr;
}

int moz_cad_insunits(const moz_cad_file *f) { return f ? f->insunits : 0; }

int moz_cad_extents(const moz_cad_file *f, double *min_xyz, double *max_xyz) {
  if (!f || !f->has_extents) return 0;
  if (min_xyz) {
    min_xyz[0] = f->extmin[0];
    min_xyz[1] = f->extmin[1];
    min_xyz[2] = f->extmin[2];
  }
  if (max_xyz) {
    max_xyz[0] = f->extmax[0];
    max_xyz[1] = f->extmax[1];
    max_xyz[2] = f->extmax[2];
  }
  return 1;
}

int moz_cad_entity_count(const moz_cad_file *f) {
  return f ? static_cast<int>(f->entities.size()) : 0;
}

const moz_cad_entity *moz_cad_entity_at(const moz_cad_file *f, int index) {
  if (!f || index < 0 || index >= static_cast<int>(f->entities.size())) return nullptr;
  return &f->entities[static_cast<size_t>(index)];
}

int moz_cad_layer_count(const moz_cad_file *f) {
  return f ? static_cast<int>(f->layers.size()) : 0;
}

const moz_cad_layer *moz_cad_layer_at(const moz_cad_file *f, int index) {
  if (!f || index < 0 || index >= static_cast<int>(f->layers.size())) return nullptr;
  return &f->layers[static_cast<size_t>(index)];
}

int moz_cad_block_count(const moz_cad_file *f) {
  return f ? static_cast<int>(f->blocks.size()) : 0;
}

const moz_cad_block *moz_cad_block_at(const moz_cad_file *f, int index) {
  if (!f || index < 0 || index >= static_cast<int>(f->blocks.size())) return nullptr;
  return &f->blocks[static_cast<size_t>(index)];
}

int moz_cad_warning_count(const moz_cad_file *f) {
  return f ? static_cast<int>(f->warnings.size()) : 0;
}

const char *moz_cad_warning_at(const moz_cad_file *f, int index) {
  if (!f || index < 0 || index >= static_cast<int>(f->warnings.size())) return nullptr;
  return f->warnings[static_cast<size_t>(index)].c_str();
}

void moz_str_free(char *s) { std::free(s); }

}  // extern "C"