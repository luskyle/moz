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

/* 剖面线：把各边界环摊平成点表 + 环的前缀和下标 */
void flatten_hatch(const DRW_Hatch &data, std::vector<double> &points, std::vector<int> &offsets,
                   int *curves, int *splines) {
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
        case DRW::SPLINE:
          if (splines) *splines += 1;
          break;
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
  std::string current_block;            /* "" 表示模型空间 */
  std::unordered_map<int, std::string> block_by_handle;
  int open_block_index = -1;

  void warn(const std::string &text) { warnings.push_back(text); }
  void ignore(const std::string &what) { ignored[what] += 1; }
  void flush_ignored() {
    for (const auto &kv : ignored) {
      warn("忽略 " + std::to_string(kv.second) + " 个" + kv.first);
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
  void addBlock(const DRW_Block &data) override {
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
    if (data->nfit > 0) f.ignore("样条的拟合点（fit points，我们没有取）");
    finish(e);
  }

  void addKnot(const DRW_Entity &data) override { (void)data; }

  void addInsert(const DRW_Insert &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_INSERT, data);
    set_point(e.p1, data.basePoint);
    e.name = f.pool.str(data.name);
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
    f.ignore("LEADER（未取顶点）");
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
    int curves = 0, splines = 0;
    flatten_hatch(*data, points, offsets, &curves, &splines);
    if (curves > 0) {
      f.warn("剖面线边界含 " + std::to_string(curves) + " 段曲线，已按 " +
             std::to_string(kHatchParts) + " 段采样（仅为显示）");
    }
    if (splines > 0) {
      f.warn("剖面线边界含 " + std::to_string(splines) + " 条样条，未展开（已跳过）");
    }
    e.npoints = static_cast<int>(points.size() / 2);
    e.points = f.pool.arr(points);
    e.nloops = static_cast<int>(offsets.size());
    e.loop_offsets = f.pool.iarr(offsets);
    finish(e);
  }

  void addViewport(const DRW_Viewport &data) override {
    moz_cad_entity &e = begin(MOZ_CAD_VIEWPORT, data);
    set_point(e.p1, data.basePoint);
    finish(e);
  }

  void addImage(const DRW_Image *data) override {
    if (!data) return;
    moz_cad_entity &e = begin(MOZ_CAD_IMAGE, *data);
    set_point(e.p1, data->basePoint);
    set_point(e.p2, data->secPoint);
    f.ignore("IMAGE（未取图片路径）");
    finish(e);
  }

  void linkImage(const DRW_ImageDef *data) override { (void)data; }
  void addComment(const char *comment) override { (void)comment; }
  void addPlotSettings(const DRW_PlotSettings *data) override { (void)data; }

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

  void dim_common(moz_cad_entity &e, const DRW_Dimension &data) {
    e.dimtype = data.type;
    std::string text = data.getText();
    if (!text.empty() && text != "<>") {
      e.text = f.pool.str(text);
      e.flags |= MOZ_CAD_FLAG_HAS_TEXT;
    }
    e.name = f.pool.str(data.getStyle());
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