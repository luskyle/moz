/*
 * moz_api.cc — OpenSCAD 2021.01 核心的 C ABI 实现
 *
 * 复用 OpenSCAD 的 headless（OPENSCAD_NOGUI）调用链，语义严格对齐上游命令行
 * src/openscad.cc：
 *   parse() -> instantiateWithFileContext() -> GeometryEvaluator -> exportFileByName()
 * 渲染（PNG）走上游的 preview 路径（CsgInfo + OpenCSGRenderer/ThrownTogetherRenderer），
 * 这样 color() 才会生效；renderer=CGAL 时才是上游 --render=cgal 的无颜色路径。
 *
 * 线程安全：内部静态状态（parser 全局、buildins、字体缓存）非线程安全，
 * 所有入口持有全局互斥量，串行化执行；工作目录在求值期间临时切换并恢复。
 */
#include "moz_api.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <boost/filesystem.hpp>

#include "builtin.h"
#include "builtincontext.h"
#include "Camera.h"
#include "cgal.h"
#include "CGAL_Nef_polyhedron.h"
#include "cgalutils.h"
#include "colormap.h"
#include "comment.h"
#include "context.h"
#include "CsgInfo.h"
#include "csgnode.h"
#include "evalcontext.h"
#include "export.h"
#include "FileModule.h"
#include "function.h"
#include "Geometry.h"
#include "GeometryEvaluator.h"
#include "modcontext.h"
#include "module.h"
#include "ModuleInstantiation.h"
#include "node.h"
#include "OffscreenView.h"
#include "openscad.h"
#include "parsersettings.h"
#include "PlatformUtils.h"
#include "polyset.h"
#include "polyset-utils.h"
#include "printutils.h"
#include "rendersettings.h"
#include "stackcheck.h"
#include "ThrownTogetherRenderer.h"
#include "Tree.h"
#include "value.h"
#ifdef ENABLE_OPENCSG
#include "OpenCSGRenderer.h"
#endif

namespace fs = boost::filesystem;

static std::mutex g_moz_mutex;

/* 消息接收者：当前正在执行的操作的日志缓冲。moz_log_handler 会写入它。 */
static std::string *g_moz_log_sink = nullptr;

/* 取值通道：注册一个捕获用的内置函数，把表达式结果原样拿到 C++ 侧。
   不能靠 echo() 文本——OpenSCAD 打印数字只保留 6 位有效数字
   （value.cc 的 DC_PRECISION_REQUESTED），参数化模型需要全精度。 */
static std::string g_moz_captured_value;
static bool g_moz_captured = false;
static bool g_moz_captured_undef = false;

/* 数值按 17 位有效数字输出（双精度无损往返），整数值写成整数形式避免噪声 */
static std::string moz_format_number(double d)
{
  if (std::isfinite(d) && d == std::floor(d) && std::abs(d) < 1e15) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%.0f", d);
    return std::string(buf);
  }
  std::ostringstream oss;
  oss.precision(17);
  oss << d;
  return oss.str();
}

static std::string moz_format_value(const Value &v)
{
  switch (v.type()) {
  case Value::Type::NUMBER:
    return moz_format_number(v.toDouble());
  case Value::Type::BOOL:
    return v.toBool() ? "true" : "false";
  case Value::Type::STRING: {
    const std::string s = v.toString();
    std::string out = "\"";
    for (const char c : s) {
      if (c == '"' || c == '\\') out += '\\';
      out += c;
    }
    out += "\"";
    return out;
  }
  case Value::Type::VECTOR: {
    const VectorType &vec = v.toVector();
    std::string out = "[";
    for (size_t i = 0; i < vec.size(); ++i) {
      if (i) out += ", ";
      out += moz_format_value(vec[i]);
    }
    return out + "]";
  }
  default:
    return v.toEchoString();
  }
}

static Value builtin_moz_capture(const std::shared_ptr<Context> ctx, const std::shared_ptr<EvalContext> evalctx)
{
  (void)ctx;
  for (size_t i = 0; i < evalctx->numArgs(); ++i) {
    if (evalctx->getArgName(i) == "value") {
      Value v = evalctx->getArgValue(i);
      g_moz_captured_value = moz_format_value(v);
      g_moz_captured = true;
      g_moz_captured_undef = (v.type() == Value::Type::UNDEFINED);
      return v;
    }
  }
  return Value::undefined.clone();
}

std::string commandline_commands;

static void moz_log_handler(const Message &msg, void *)
{
  if (!g_moz_log_sink) return;
  /* Message::str() 与上游控制台文本一致（含 "ECHO: " / "WARNING: " 前缀） */
  g_moz_log_sink->append(msg.str());
  g_moz_log_sink->push_back('\n');
}

/* 一次操作期间把消息收集到自己的缓冲，避免使用全局状态串味 */
struct moz_log_scope {
  std::string log;
  std::string *previous;
  moz_log_scope()
  {
    this->previous = g_moz_log_sink;
    g_moz_log_sink = &this->log;
    set_output_handler(moz_log_handler, nullptr, nullptr);
  }
  ~moz_log_scope() { g_moz_log_sink = this->previous; }
};

static void moz_set_err(char **err, const char *fmt, ...)
{
  if (!err) return;
  va_list ap;
  va_start(ap, fmt);
  char buf[4096];
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  *err = strdup(buf);
}

/* 失败时把整段消息日志交给调用方：上游把这些打到 stderr，API 调用方只能这样拿到 */
static void moz_set_err_from_log(char **err, const std::string &log, const char *fallback)
{
  if (!err) return;
  if (log.empty()) {
    *err = strdup(fallback);
    return;
  }
  *err = strdup(log.c_str());
}

static void moz_ensure_init()
{
  static const bool inited = []() {
    StackCheck::inst();
    /* 资源目录（color-schemes/locale/fonts 等）靠应用路径向上找 color-schemes 目录定位。
       共享库里没有可用的应用路径，所以允许用 MOZ_OPENSCAD_RESOURCE_DIR 指到
       OpenSCAD 源码/安装目录（Python 绑定会按仓库布局自动填这个变量）。 */
    const char *resource_dir = getenv("MOZ_OPENSCAD_RESOURCE_DIR");
    std::string app_path;
    if (resource_dir && fs::is_directory(fs::path(resource_dir))) app_path = resource_dir;
    PlatformUtils::registerApplicationPath(app_path);
#ifdef ENABLE_CGAL
    CGAL::set_error_behaviour(CGAL::ABORT);
#endif
    Builtins::instance()->initialize();
    /* 注册取值用的内置函数（等同其他 initialize_builtin_* 的注册方式） */
    Builtins::init("moz_capture", new BuiltinFunction(&builtin_moz_capture), {"moz_capture(value)"});
    parser_init();
    return true;
  }();
  (void)inited;
}

struct moz_geom {
  std::shared_ptr<const Geometry> geom;  // 求值后的几何（空几何时为 CGAL_Nef_polyhedron 空对象）
  AbstractNode *node_tree;               // 实例化出的节点树（free 时递归释放）
  const AbstractNode *render_root;       // find_root_tag 选出的渲染根（! 修饰符）
  FileModule *root_module;               // 解析出的模块树（free 时释放）
  std::string docname;                   // 文档绝对路径（<stdin> 表示无文件）
  std::string docpath;                   // 文档父目录（绝对）
  mutable std::string log;               // 累积消息（echo / warning / 日志）
  int dimension;
  bool empty;
};

/* 解析 + 实例化出的中间结果 */
struct moz_parsed {
  FileModule *root_module = nullptr;
  AbstractNode *node_tree = nullptr;
  const AbstractNode *render_root = nullptr;
  std::string docname;
  std::string docpath;
};

static std::string moz_read_file(const std::string &path)
{
  std::ifstream ifs(path.c_str(), std::ios::binary);
  if (!ifs.is_open()) return std::string();
  return std::string((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
}

/* -D 参数：与上游一致，作为 "\x03" 之后的命令行段拼接 */
static std::string moz_cmdline(const char *const *assignments, int n_assignments)
{
  std::string cmdline;
  for (int i = 0; i < n_assignments; ++i) {
    cmdline += assignments[i];
    cmdline += ";\n";
  }
  return cmdline;
}

/* 文档路径统一成绝对路径：上游用 fs::absolute 后再 chdir(fparent)，
   既保证 import()/use 的相对路径解析，又保证输出的相对文件名一致。
   历史 bug：保留相对路径时 chdir 会让同目录 import() 静默变成空几何。 */
static std::string moz_abs_docname(const std::string &path)
{
  if (path.empty() || path == "<stdin>") return path;
  return fs::absolute(fs::path(path)).generic_string();
}

/* 解析 + 实例化节点树。$preview 由 preview 决定（渲染走 preview 语义，导出走 F6 语义） */
static bool moz_parse_and_instantiate(const std::string &text, const std::string &docname,
                                      const char *const *assignments, int n_assignments, bool preview,
                                      moz_parsed &out)
{
  std::string full = text;
  const std::string cmdline = moz_cmdline(assignments, n_assignments);
  if (!cmdline.empty()) full += "\n\x03\n" + cmdline;

  const fs::path original = fs::current_path();
  const std::string abs_doc = moz_abs_docname(docname);
  fs::path docparent;
  if (!abs_doc.empty() && abs_doc != "<stdin>") {
    docparent = fs::path(abs_doc).parent_path();
    if (fs::is_directory(docparent)) fs::current_path(docparent);
  }
  out.docname = abs_doc;
  out.docpath = docparent.string();

  FileModule *root_module = nullptr;
  if (!parse(root_module, full, abs_doc, abs_doc, false)) {
    delete root_module;
    root_module = nullptr;
  }
  if (!root_module) {
    fs::current_path(original);
    return false;
  }
  CommentParser::collectParameters(full.c_str(), root_module);
  root_module->handleDependencies();

  AbstractNode::resetIndexCounter();
  ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
  top_ctx->set_variable("$preview", Value(preview));
  if (!out.docpath.empty()) top_ctx->setDocumentPath(out.docpath);
  ModuleInstantiation root_inst("group");
  ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
  AbstractNode *absolute_root_node = root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);
  fs::current_path(original);

  if (!absolute_root_node) {
    delete root_module;
    return false;
  }

  const Location *nextLocation = nullptr;
  const AbstractNode *root_node = find_root_tag(absolute_root_node, &nextLocation);
  if (!root_node) root_node = absolute_root_node;
  if (nextLocation) {
    LOG(message_group::Warning, *nextLocation, out.docpath, "More than one Root Modifier (!)");
  }

  out.root_module = root_module;
  out.node_tree = absolute_root_node;
  out.render_root = root_node;
  return true;
}

/* 解析 + 实例化 + 几何求值 */
static moz_geom *moz_do_eval(const std::string &text, const std::string &docname,
                             const char *const *assignments, int n_assignments, char **err)
{
  moz_log_scope scope;

  moz_parsed parsed;
  if (!moz_parse_and_instantiate(text, docname, assignments, n_assignments, false, parsed)) {
    moz_set_err_from_log(err, scope.log, "Can't parse input");
    return nullptr;
  }

  Tree tree;
  tree.setDocumentPath(parsed.docpath);
  tree.setRoot(parsed.render_root);

  GeometryEvaluator geomevaluator(tree);
  std::shared_ptr<const Geometry> geom = geomevaluator.evaluateGeometry(*tree.root(), true);
  if (!geom) geom.reset(new CGAL_Nef_polyhedron());

  auto *g = new moz_geom();
  g->geom = geom;
  g->node_tree = parsed.node_tree;
  g->render_root = parsed.render_root;
  g->root_module = parsed.root_module;
  g->docname = parsed.docname;
  g->docpath = parsed.docpath;
  g->dimension = static_cast<int>(geom->getDimension());
  g->empty = geom->isEmpty();
  g->log = scope.log;
  return g;
}

extern "C" moz_geom *moz_eval_text(const char *source, const char *const *assignments,
                                   int n_assignments, char **err)
{
  if (!source) {
    moz_set_err(err, "null source");
    return nullptr;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_ensure_init();
  return moz_do_eval(std::string(source), "<stdin>", assignments, n_assignments, err);
}

extern "C" moz_geom *moz_eval_file(const char *path, const char *const *assignments,
                                   int n_assignments, char **err)
{
  if (!path) {
    moz_set_err(err, "null path");
    return nullptr;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_ensure_init();
  const std::string abs_path = moz_abs_docname(path);
  const std::string text = moz_read_file(abs_path);
  if (text.empty()) {
    moz_set_err(err, "Can't open input file '%s'", path);
    return nullptr;
  }
  return moz_do_eval(text, abs_path, assignments, n_assignments, err);
}

extern "C" int moz_geom_dimension(const moz_geom *g)
{
  if (!g) return -1;
  return g->dimension;
}

extern "C" int moz_geom_is_empty(const moz_geom *g)
{
  if (!g) return 1;
  return g->empty ? 1 : 0;
}

extern "C" char *moz_geom_log(const moz_geom *g, int clear)
{
  if (!g) return nullptr;
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  char *out = strdup(g->log.c_str());
  if (clear) g->log.clear();
  return out;
}

extern "C" char *moz_eval_value(const char *source, const char *expression,
                                const char *const *assignments, int n_assignments, char **err)
{
  if (!expression) {
    moz_set_err(err, "null expression");
    return nullptr;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_ensure_init();

  moz_log_scope scope;
  /* 表达式只能在引擎自身的求值器里算：作为 moz_capture() 的参数写在顶层赋值右侧，
     实例化阶段就会求值，结果由内置函数原样交给 C++ 侧（保留全精度）。 */
  std::string text(source ? source : "");
  text += "\nmoz_capture_result = moz_capture(value = ";
  text += expression;
  text += ");\n";

  g_moz_captured = false;
  g_moz_captured_undef = false;
  moz_parsed parsed;
  if (!moz_parse_and_instantiate(text, "<stdin>", assignments, n_assignments, false, parsed)) {
    moz_set_err_from_log(err, scope.log, "OpenSCAD evaluation failed");
    return nullptr;
  }
  delete parsed.node_tree;
  delete parsed.root_module;

  if (!g_moz_captured) {
    moz_set_err_from_log(err, scope.log, "expression produced no value");
    return nullptr;
  }
  /* 表达式算不出来时 SCAD 会给出 undef（例如未知函数、参数类型不对——上游把这些记成
     WARNING 后继续算）：取值 API 必须把原因交出去，不能只回一个 "undef"。 */
  if (g_moz_captured_undef &&
      (scope.log.find("WARNING") != std::string::npos || scope.log.find("ERROR") != std::string::npos)) {
    moz_set_err_from_log(err, scope.log, "expression evaluated to undef");
    return nullptr;
  }
  const std::string result = g_moz_captured_value;
  g_moz_captured = false;
  g_moz_captured_undef = false;
  return strdup(result.c_str());
}

extern "C" void moz_geom_free(moz_geom *g)
{
  if (!g) return;
  /* 与求值/导出/渲染互斥：节点树释放期间不应有并发访问 */
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  delete g->node_tree;    // AbstractNode 析构递归释放整棵节点树
  delete g->root_module;  // 模块树
  delete g;
}

extern "C" void moz_str_free(char *s) { free(s); }
extern "C" void moz_bytes_free(unsigned char *p) { free(p); }

/* ---------------- 渲染 ---------------- */

extern "C" void moz_render_options_default(moz_render_options *opts)
{
  if (!opts) return;
  opts->width = 0;
  opts->height = 0;
  opts->renderer = MOZ_RENDER_OPENCSG;
  opts->show_faces = 1;
  opts->show_edges = 0;
  opts->show_axes = 0;
  opts->show_scales = 0;
  opts->show_crosshairs = 0;
  opts->colorscheme = nullptr;
}

/* 应用配色方案：与上游 set_render_color_scheme 一致，未知名字产生警告并沿用当前配色 */
static void moz_apply_colorscheme(const char *name)
{
  if (!name || !*name) return;
  const std::string cs(name);
  if (ColorMap::inst()->findColorScheme(cs)) {
    RenderSettings::inst()->colorscheme = cs;
  } else {
    LOG(message_group::Warning, Location::NONE, "", "Unknown color scheme '%1$s', using default '%2$s'.",
        cs, ColorMap::inst()->defaultColorSchemeName());
  }
}

/* 相机：与上游一致，先读模型里的 $vpr/$vpt/$vpd/$vpf（有 $vp* 时上游会关掉
   viewall/autocenter），所以 viewall/autocenter 必须在 updateView 之前设。 */
static void moz_prepare_camera(Camera &camera, const ContextHandle<FileContext> &filectx)
{
  camera.viewall = true;
  camera.autocenter = true;
  camera.updateView(filectx.ctx, true);
}

/* preview 路径：preview 渲染器自己算 bbox，这里按其结果取景 */
static void moz_setup_camera(Camera &camera, const ContextHandle<FileContext> &filectx,
                             const BoundingBox &bbox)
{
  moz_prepare_camera(camera, filectx);
  if (camera.viewall) camera.viewAll(bbox);
}

/* preview 路径渲染：保留 color() / % / # （等同 GUI 的 F5）。
   需要 $preview=true 的节点树，因此这里用已解析的模块树重新实例化一次。 */
static bool moz_render_preview(const moz_geom *g, const moz_render_options &opts, std::ostream &output)
{
  ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
  top_ctx->set_variable("$preview", Value(true));
  if (!g->docpath.empty()) top_ctx->setDocumentPath(g->docpath);
  ModuleInstantiation root_inst("group");
  ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
  AbstractNode *absolute_root_node = g->root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);
  if (!absolute_root_node) {
    LOG(message_group::Error, Location::NONE, "", "Failed to instantiate root module for preview rendering");
    return false;
  }

  const Location *nextLocation = nullptr;
  const AbstractNode *root_node = find_root_tag(absolute_root_node, &nextLocation);
  if (!root_node) root_node = absolute_root_node;

  Tree tree;
  tree.setDocumentPath(g->docpath);
  tree.setRoot(root_node);

  CsgInfo csgInfo;
  csgInfo.compile_products(tree);

  std::unique_ptr<OffscreenView> glview;
  try {
    glview.reset(new OffscreenView(opts.width, opts.height));
  } catch (int error) {
    LOG(message_group::Error, Location::NONE, "", "Can't create OpenGL OffscreenView. Code: %1$d", error);
    delete absolute_root_node;
    return false;
  }

  std::unique_ptr<ThrownTogetherRenderer> thrownTogether;
  bool used_opencsg = false;
#ifdef ENABLE_OPENCSG
  std::unique_ptr<OpenCSGRenderer> openCSG;
#endif
  if (opts.renderer == MOZ_RENDER_OPENCSG) {
#ifdef ENABLE_OPENCSG
    openCSG.reset(new OpenCSGRenderer(csgInfo.root_products, csgInfo.highlights_products,
                                      csgInfo.background_products, &glview->shaderinfo));
    glview->setRenderer(openCSG.get());
    used_opencsg = true;
#else
    LOG(message_group::Warning, Location::NONE, "",
        "This build has no OpenCSG support, falling back to ThrownTogether rendering");
#endif
  }
  if (!used_opencsg) {
    thrownTogether.reset(new ThrownTogetherRenderer(csgInfo.root_products, csgInfo.highlights_products,
                                                    csgInfo.background_products));
    glview->setRenderer(thrownTogether.get());
  }

  glview->setColorScheme(RenderSettings::inst()->colorscheme);
  glview->setShowFaces(opts.show_faces != 0);
  glview->setShowEdges(opts.show_edges != 0);
  glview->setShowAxes(opts.show_axes != 0);
  glview->setShowScaleProportional(opts.show_scales != 0);
  glview->setShowCrosshairs(opts.show_crosshairs != 0);

  Camera camera;
  camera.pixel_width = opts.width;
  camera.pixel_height = opts.height;
  moz_setup_camera(camera, filectx, glview->getRenderer()->getBoundingBox());
  glview->setCamera(camera);
  glview->paintGL();

  const bool ok = glview->save(output);
  delete absolute_root_node;
  return ok;
}

/* CGAL 路径渲染：与上游 --render=cgal 一致，颜色只来自配色方案的材质色 */
static bool moz_render_cgal(const moz_geom *g, const moz_render_options &opts, std::ostream &output)
{
  ViewOptions options;
  options.renderer = RenderType::CGAL;
  options["wireframe"] = opts.show_faces == 0;
  options["edges"] = opts.show_edges != 0;
  options["axes"] = opts.show_axes != 0;
  options["scales"] = opts.show_scales != 0;
  options["crosshairs"] = opts.show_crosshairs != 0;

  /* 相机要读模型里的 $vpr/$vpt/$vpd，所以实例化一次拿 FileContext；
     几何直接用已经求值好的 g->geom ——上游 --render=cgal 渲染的就是它 */
  ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
  top_ctx->set_variable("$preview", Value(false));
  if (!g->docpath.empty()) top_ctx->setDocumentPath(g->docpath);
  ModuleInstantiation root_inst("group");
  ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
  AbstractNode *absolute_root_node = g->root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);

  Camera camera;
  camera.pixel_width = opts.width;
  camera.pixel_height = opts.height;
  moz_prepare_camera(camera, filectx);

  const bool ok = export_png(g->geom, options, camera, output);
  delete absolute_root_node;
  return ok;
}

static int moz_render_impl(const moz_geom *g, const char *outfile, const moz_render_options *requested,
                           unsigned char **out, size_t *out_len, char **err)
{
  if (!g) {
    moz_set_err(err, "null geometry handle");
    return -1;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_log_scope scope;

  moz_render_options opts;
  moz_render_options_default(&opts);
  if (requested) opts = *requested;
  if (opts.width == 0) opts.width = RenderSettings::inst()->img_width;
  if (opts.height == 0) opts.height = RenderSettings::inst()->img_height;
  moz_apply_colorscheme(opts.colorscheme);

  std::ostringstream oss(std::ios::out | std::ios::binary);
  const bool ok = (opts.renderer == MOZ_RENDER_CGAL)
                      ? moz_render_cgal(g, opts, oss)
                      : moz_render_preview(g, opts, oss);
  g->log += scope.log;
  if (!ok) {
    moz_set_err_from_log(err, scope.log, "PNG rendering failed");
    return -5;
  }

  const std::string &s = oss.str();
  if (out) {
    auto *buf = static_cast<unsigned char *>(malloc(s.size() ? s.size() : 1));
    if (!s.empty()) memcpy(buf, s.data(), s.size());
    *out = buf;
    *out_len = s.size();
    return 0;
  }
  std::ofstream f(outfile, std::ios::out | std::ios::binary | std::ios::trunc);
  if (!f.is_open()) {
    moz_set_err(err, "Can't open file '%s' for export", outfile);
    return -6;
  }
  f.write(s.data(), static_cast<std::streamsize>(s.size()));
  return 0;
}

extern "C" int moz_render_png(const moz_geom *g, const char *outfile,
                              const moz_render_options *opts, char **err)
{
  if (!outfile) {
    moz_set_err(err, "null outfile");
    return -6;
  }
  return moz_render_impl(g, outfile, opts, nullptr, nullptr, err);
}

extern "C" int moz_render_png_bytes(const moz_geom *g, const moz_render_options *opts,
                                    unsigned char **out, size_t *out_len, char **err)
{
  if (!out || !out_len) {
    moz_set_err(err, "null out/out_len");
    return -7;
  }
  *out = nullptr;
  *out_len = 0;
  return moz_render_impl(g, nullptr, opts, out, out_len, err);
}

/* ---------------- 导出 ---------------- */

/* 导出实现：out 为 NULL 时写文件（outfile），否则导出到内存缓冲 */
static int moz_export_impl(const moz_geom *g, const char *format, const char *outfile,
                           unsigned char **out, size_t *out_len, char **err)
{
  if (!g) {
    moz_set_err(err, "null geometry handle");
    return -1;
  }

  const std::string sfmt = format ? format : "";
  /* PNG 不是 exportFile 的格式，走上游 `-o x.png` 的渲染路径（含加锁与日志） */
  if (sfmt == "png") {
    moz_render_options opts;
    moz_render_options_default(&opts);
    return moz_render_impl(g, outfile, &opts, out, out_len, err);
  }

  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_log_scope scope;

  ExportFileFormatOptions fmt_options;
  const auto it = fmt_options.exportFileFormats.find(sfmt);
  if (it == fmt_options.exportFileFormats.end()) {
    moz_set_err(err, "unknown export format '%s'", format);
    return -2;
  }
  const FileFormat fmt = it->second;

  switch (fmt) {
  case FileFormat::ASCIISTL:
  case FileFormat::STL:
  case FileFormat::OFF:
  case FileFormat::AMF:
  case FileFormat::_3MF:
  case FileFormat::NEFDBG:
  case FileFormat::NEF3:
    if (g->dimension == 2) {
      moz_set_err(err, "format '%s' requires 3D geometry, got 2D", sfmt.c_str());
      return -3;
    }
    break;
  case FileFormat::DXF:
  case FileFormat::SVG:
  case FileFormat::PDF:
    if (g->dimension == 3 && !g->empty) {
      moz_set_err(err, "format '%s' requires 2D geometry, got 3D", sfmt.c_str());
      return -3;
    }
    break;
  case FileFormat::CSG:
  case FileFormat::AST:
  case FileFormat::TERM:
  case FileFormat::ECHO:
    moz_set_err(err, "format '%s' is text-only, use moz_dump()", sfmt.c_str());
    return -4;
  case FileFormat::PNG:
    break;
  }

  ExportInfo exportInfo;
  exportInfo.format = fmt;
  exportInfo.name2display = outfile ? outfile : "<memory>";
  exportInfo.name2open = outfile ? outfile : "";
  exportInfo.useStdOut = false;
  /* 上游 CLI 不设 sourceFileName/sourceFilePath（只有 PDF 会用到它们，GUI 才设），
     这里按 GUI 语义填源文档，而不是输出文件名 */
  if (!g->docname.empty() && g->docname != "<stdin>") {
    exportInfo.sourceFilePath = g->docname;
    exportInfo.sourceFileName = fs::path(g->docname).filename().string();
  }

  if (out) {
    std::ostringstream oss(std::ios::out | std::ios::binary);
    exportFile(g->geom, oss, exportInfo);
    const std::string &s = oss.str();
    auto *buf = static_cast<unsigned char *>(malloc(s.size() ? s.size() : 1));
    if (!s.empty()) memcpy(buf, s.data(), s.size());
    *out = buf;
    *out_len = s.size();
  } else {
    exportFileByName(g->geom, exportInfo);
  }
  g->log += scope.log;
  return 0;
}

extern "C" int moz_export(const moz_geom *g, const char *format, const char *outfile, char **err)
{
  if (!outfile) {
    moz_set_err(err, "null outfile");
    return -6;
  }
  return moz_export_impl(g, format, outfile, nullptr, nullptr, err);
}

extern "C" int moz_export_bytes(const moz_geom *g, const char *format, unsigned char **out,
                                size_t *out_len, char **err)
{
  if (!out || !out_len) {
    moz_set_err(err, "null out/out_len");
    return -7;
  }
  *out = nullptr;
  *out_len = 0;
  return moz_export_impl(g, format, nullptr, out, out_len, err);
}

/* ---------------- 逐面颜色 ---------------- */

/* 与 export_stl 的遍历顺序保持一致：GeometryList 依次展开，Nef/PolySet 先三角化再逐面输出 */
static void moz_collect_triangles(const std::shared_ptr<const Geometry> &geom,
                                  std::vector<std::array<Vector3d, 3>> &tris)
{
  if (const auto geomlist = dynamic_pointer_cast<const GeometryList>(geom)) {
    for (const auto &item : geomlist->getChildren()) moz_collect_triangles(item.second, tris);
  } else if (const auto N = dynamic_pointer_cast<const CGAL_Nef_polyhedron>(geom)) {
    PolySet ps(3);
    /* 上游约定：createPolySetFromNefPolyhedron3 返回 false 表示成功（见 cgalutils.cc 注释） */
    if (!CGALUtils::createPolySetFromNefPolyhedron3(*(N->p3), ps)) {
      PolySet triangulated(3);
      PolysetUtils::tessellate_faces(ps, triangulated);
      for (const auto &p : triangulated.polygons) {
        if (p.size() == 3) tris.push_back({p[0], p[1], p[2]});
      }
    }
  } else if (const auto ps = dynamic_pointer_cast<const PolySet>(geom)) {
    PolySet triangulated(3);
    PolysetUtils::tessellate_faces(*ps, triangulated);
    for (const auto &p : triangulated.polygons) {
      if (p.size() == 3) tris.push_back({p[0], p[1], p[2]});
    }
  }
}

struct moz_color_leaf {
  std::vector<std::array<Vector3d, 3>> tris;  // 已应用叶节点矩阵的世界坐标三角面
  Color4f color;
  BoundingBox bbox;
};

static bool moz_bbox_contains(const BoundingBox &bbox, const Vector3d &p)
{
  for (int i = 0; i < 3; ++i) {
    if (p[i] < bbox.min()[i] || p[i] > bbox.max()[i]) return false;
  }
  return true;
}

/* 点到三角面的最短距离（用于判断某个面是否贴在某个对象的表面上） */
static double moz_point_tri_distance(const Vector3d &p, const Vector3d &a, const Vector3d &b, const Vector3d &c)
{
  const Vector3d ab = b - a, ac = c - a, ap = p - a;
  const double d1 = ab.dot(ap), d2 = ac.dot(ap);
  if (d1 <= 0.0 && d2 <= 0.0) return (p - a).norm();

  const Vector3d bp = p - b;
  const double d3 = ab.dot(bp), d4 = ac.dot(bp);
  if (d3 >= 0.0 && d4 <= d3) return (p - b).norm();

  const double vc = d1 * d4 - d3 * d2;
  if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) {
    const double v = d1 / (d1 - d3);
    return (p - (a + v * ab)).norm();
  }

  const Vector3d cp = p - c;
  const double d5 = ab.dot(cp), d6 = ac.dot(cp);
  if (d6 >= 0.0 && d5 <= d6) return (p - c).norm();

  const double vb = d5 * d2 - d1 * d6;
  if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) {
    const double w = d2 / (d2 - d6);
    return (p - (a + w * ac)).norm();
  }

  const double va = d3 * d6 - d5 * d4;
  if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) {
    const double w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    return (p - (b + w * (c - b))).norm();
  }

  const double denom = 1.0 / (va + vb + vc);
  const double v = vb * denom, w = vc * denom;
  return (p - (a + ab * v + ac * w)).norm();
}

/* 点是否在三角面片体内部：射线奇偶法。
   不用 CGAL 的 Nef 点定位——Nef_polyhedron_3::contains(Object_handle) 在 5.4 里是
   未实现（CGAL_error_msg），locate() 又依赖可能为空的点定位器（Release 关断言后会崩）。 */
static bool moz_point_in_triangles(const std::vector<std::array<Vector3d, 3>> &tris, const Vector3d &p)
{
  /* 多个射线方向轮换，避开恰好命中边/顶点的退化情形 */
  static const Vector3d directions[3] = {
      Vector3d(0.5773502691896258, 0.5773502691896258, 0.5773502691896258),
      Vector3d(0.2672612419124244, 0.5345224838248488, 0.8017837257372732),
      Vector3d(0.4242640687119285, 0.7071067811865476, 0.5656854249492380),
  };
  const double eps = 1e-9;

  for (const Vector3d &dir : directions) {
    int hits = 0;
    bool degenerate = false;
    for (const auto &tri : tris) {
      const Vector3d &a = tri[0], &b = tri[1], &c = tri[2];
      const Vector3d e1 = b - a, e2 = c - a;
      const Vector3d pv = dir.cross(e2);
      const double det = e1.dot(pv);
      if (std::abs(det) < 1e-14) continue;  // 射线与三角面平行
      const double inv = 1.0 / det;
      const Vector3d tv = p - a;
      const double u = tv.dot(pv) * inv;
      if (u < -eps || u > 1.0 + eps) continue;
      const double q = tv.cross(e1).dot(dir) * inv;
      if (q < -eps || u + q > 1.0 + eps) continue;
      const double t = e2.dot(tv.cross(e1)) * inv;
      if (t <= 0.0) continue;  // 只取射线正方向
      /* 命中点贴边/贴顶点时结果不可靠，换一个方向重试 */
      if (u < 1e-7 || q < 1e-7 || (u + q) > 1.0 - 1e-7) {
        degenerate = true;
        break;
      }
      ++hits;
    }
    if (!degenerate) return (hits % 2) == 1;
  }
  return false;
}

extern "C" int moz_geom_face_colors(const moz_geom *g, unsigned char **out, size_t *out_len, char **err)
{
  if (!g) {
    moz_set_err(err, "null geometry handle");
    return -1;
  }
  if (!out || !out_len) {
    moz_set_err(err, "null out/out_len");
    return -7;
  }
  *out = nullptr;
  *out_len = 0;

  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_log_scope scope;

  /* 最终网格：与 moz_export_bytes(g, "binstl") 同一条三角化路径 */
  std::vector<std::array<Vector3d, 3>> tris;
  moz_collect_triangles(g->geom, tris);
  if (tris.empty()) {
    g->log += scope.log;
    return 0;
  }

  /* CSG 链上的彩色叶子：并集 / 交集对象用于实体表面，差集对象用于切面
     （OpenCSG 预览里被切出来的面取的正是被减对象的颜色） */
  std::vector<moz_color_leaf> positives, negatives;
  {
    ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
    top_ctx->set_variable("$preview", Value(true));
    if (!g->docpath.empty()) top_ctx->setDocumentPath(g->docpath);
    ModuleInstantiation root_inst("group");
    ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
    AbstractNode *absolute_root_node =
        g->root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);
    if (absolute_root_node) {
      const Location *nextLocation = nullptr;
      const AbstractNode *root_node = find_root_tag(absolute_root_node, &nextLocation);
      if (!root_node) root_node = absolute_root_node;
      Tree tree;
      tree.setDocumentPath(g->docpath);
      tree.setRoot(root_node);

      CsgInfo csgInfo;
      csgInfo.compile_products(tree);

      if (csgInfo.root_products) {
        for (const auto &product : csgInfo.root_products->products) {
          const auto collect = [](const std::vector<CSGChainObject> &chain,
                                  std::vector<moz_color_leaf> &target) {
            for (const auto &chainobj : chain) {
              if (chainobj.flags & CSGNode::FLAG_BACKGROUND) continue;
              const auto &leaf = chainobj.leaf;
              if (!leaf || !leaf->geom || leaf->geom->isEmpty()) continue;
              if (leaf->geom->getDimension() != 3) continue;

              moz_color_leaf item;
              moz_collect_triangles(leaf->geom, item.tris);
              if (item.tris.empty()) continue;
              for (auto &tri : item.tris) {
                for (auto &p : tri) p = leaf->matrix * p;
              }
              item.bbox = BoundingBox(item.tris[0][0], item.tris[0][0]);
              for (const auto &tri : item.tris) {
                for (const auto &p : tri) item.bbox.extend(p);
              }
              item.color = leaf->color;
              target.push_back(std::move(item));
            }
          };
          collect(product.intersections, positives);
          collect(product.subtractions, negatives);
        }
      }
      delete absolute_root_node;
    }
  }

  /* 未着色对象使用当前配色方案的材质色，与 preview 渲染一致 */
  const ColorScheme &scheme = ColorMap::inst()->findColorScheme(RenderSettings::inst()->colorscheme)
                                  ? *ColorMap::inst()->findColorScheme(RenderSettings::inst()->colorscheme)
                                  : ColorMap::inst()->defaultColorScheme();
  const Color4f material = ColorMap::getColor(scheme, RenderColor::OPENCSG_FACE_FRONT_COLOR);

  /* 采样尺度取网格对角线的一小段；命中失败时逐级放大重试 */
  Vector3d lo = tris[0][0], hi = tris[0][0];
  for (const auto &tri : tris) {
    for (const auto &p : tri) {
      for (int i = 0; i < 3; ++i) {
        lo[i] = std::min(lo[i], p[i]);
        hi[i] = std::max(hi[i], p[i]);
      }
    }
  }
  const double diag = std::max((hi - lo).norm(), 1e-9);

  /* 面归属：优先“这个面贴在哪个对象的表面上”——与 OpenCSG 预览里各基本体
     各自着色的行为一致（difference 的切面因此取被减对象的颜色）。
     贴不到任何表面时，再退化为“面内一点属于哪个对象”。 */
  auto classify_surface = [&](const std::vector<moz_color_leaf> &leaves, const Vector3d &p,
                              double eps) -> const Color4f * {
    for (const auto &leaf : leaves) {
      BoundingBox padded(leaf.bbox.min() - Vector3d(eps, eps, eps),
                         leaf.bbox.max() + Vector3d(eps, eps, eps));
      if (!moz_bbox_contains(padded, p)) continue;
      for (const auto &tri : leaf.tris) {
        if (moz_point_tri_distance(p, tri[0], tri[1], tri[2]) <= eps) return &leaf.color;
      }
    }
    return nullptr;
  };

  auto classify_inside = [&](const std::vector<moz_color_leaf> &leaves,
                             const Vector3d &sample) -> const Color4f * {
    for (const auto &leaf : leaves) {
      /* 用包围盒先粗筛，避免每个三角面都遍历所有叶子的三角面 */
      if (!moz_bbox_contains(leaf.bbox, sample)) continue;
      if (moz_point_in_triangles(leaf.tris, sample)) return &leaf.color;
    }
    return nullptr;
  };

  auto *buf = static_cast<unsigned char *>(malloc(tris.size() * 4));
  const float scale = 255.0f;
  for (size_t i = 0; i < tris.size(); ++i) {
    const Vector3d &p0 = tris[i][0], &p1 = tris[i][1], &p2 = tris[i][2];
    const Vector3d centroid = (p0 + p1 + p2) / 3.0;
    Vector3d normal = (p1 - p0).cross(p2 - p0);
    const double len = normal.norm();
    const bool has_normal = len > 1e-12;
    if (has_normal) normal = Vector3d(normal / len);

    const Color4f *chosen = nullptr;
    for (int attempt = 0; attempt < 4 && !chosen; ++attempt) {
      const double eps = diag * 1e-5 * std::pow(2.0, static_cast<double>(attempt));
      chosen = classify_surface(negatives, centroid, eps);
      if (!chosen) chosen = classify_surface(positives, centroid, eps);
      if (!chosen && !positives.empty()) {
        if (has_normal) {
          chosen = classify_inside(positives, centroid - eps * normal);
        } else {
          for (const double sign : {1.0, -1.0}) {
            chosen = classify_inside(positives, centroid + sign * eps * Vector3d(0, 0, 1));
            if (chosen) break;
          }
        }
      }
    }

    Color4f c = chosen ? *chosen : material;
    if (!c.isValid()) c = material;
    for (int k = 0; k < 4; ++k) {
      const float value = std::min(std::max(c[k] * scale, 0.0f), 255.0f);
      buf[i * 4 + k] = static_cast<unsigned char>(value);
    }
  }

  *out = buf;
  *out_len = tris.size() * 4;
  g->log += scope.log;
  return 0;
}

/* ---------------- 文本 dump ---------------- */

/* 文本 dump：csg / ast / term / echo（不需要几何求值） */
static char *moz_dump_impl(const std::string &text, const std::string &docname, const char *format,
                           const char *const *assignments, int n_assignments, char **err)
{
  moz_log_scope scope;

  const std::string sfmt = format ? format : "csg";
  moz_parsed parsed;
  if (!moz_parse_and_instantiate(text, docname, assignments, n_assignments, false, parsed)) {
    moz_set_err_from_log(err, scope.log, "Can't parse input");
    return nullptr;
  }

  std::string result;
  if (sfmt == "ast") {
    result = parsed.root_module->dump("");
  } else if (sfmt == "echo") {
    /* 上游的 ECHO 输出格式：只导出 echo() 产生的消息 */
    std::istringstream iss(scope.log);
    std::string line;
    while (std::getline(iss, line)) {
      if (line.compare(0, 6, "ECHO: ") == 0) {
        result += line.substr(6);
        result += "\n";
      }
    }
  } else if (sfmt == "csg" || sfmt == "term") {
    Tree tree;
    tree.setDocumentPath(parsed.docpath);
    tree.setRoot(parsed.render_root);
    if (sfmt == "csg") {
      result = tree.getString(*parsed.render_root, "\t") + "\n";
    } else {
      CSGTreeEvaluator csg(tree);
      const shared_ptr<CSGNode> root_raw_term = csg.buildCSGTree(*parsed.render_root);
      if (!root_raw_term || root_raw_term->isEmptySet()) {
        result = "No top-level CSG object\n";
      } else {
        result = root_raw_term->dump() + "\n";
      }
    }
  } else {
    moz_set_err(err, "unknown dump format '%s' (csg|ast|term|echo)", format);
    delete parsed.node_tree;
    delete parsed.root_module;
    return nullptr;
  }

  delete parsed.node_tree;
  delete parsed.root_module;
  return strdup(result.c_str());
}

extern "C" char *moz_dump(const char *source, const char *docname, const char *format,
                          const char *const *assignments, int n_assignments, char **err)
{
  if (!source) {
    moz_set_err(err, "null source");
    return nullptr;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_ensure_init();
  return moz_dump_impl(std::string(source), docname ? docname : "<stdin>",
                       format, assignments, n_assignments, err);
}

extern "C" char *moz_dump_file(const char *path, const char *format,
                               const char *const *assignments, int n_assignments, char **err)
{
  if (!path) {
    moz_set_err(err, "null path");
    return nullptr;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  moz_ensure_init();
  const std::string abs_path = moz_abs_docname(path);
  const std::string text = moz_read_file(abs_path);
  if (text.empty()) {
    moz_set_err(err, "Can't open input file '%s'", path);
    return nullptr;
  }
  return moz_dump_impl(text, abs_path, format, assignments, n_assignments, err);
}