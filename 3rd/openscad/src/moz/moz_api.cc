/*
 * moz_api.cc — OpenSCAD 2021.01 核心的 C ABI 实现
 *
 * 复用 OpenSCAD 的 headless（OPENSCAD_NOGUI）调用链：
 *   parse() -> instantiateWithFileContext() -> GeometryEvaluator -> exportFileByName()
 * 参考命令行模式 src/openscad.cc 的 cmdline()/do_export()。
 *
 * 线程安全：内部静态状态（parser 全局、buildins、字体缓存）非线程安全，
 * 所有入口持有全局互斥量，串行化执行；工作目录在求值期间临时切换并恢复。
 */
#include "moz_api.h"

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <boost/filesystem.hpp>

#include "builtin.h"
#include "builtincontext.h"
#include "cgal.h"
#include "CGAL_Nef_polyhedron.h"
#include "CSGTreeEvaluator.h"
#include "comment.h"
#include "context.h"
#include "evalcontext.h"
#include "export.h"
#include "FileModule.h"
#include "Geometry.h"
#include "GeometryEvaluator.h"
#include "modcontext.h"
#include "ModuleInstantiation.h"
#include "node.h"
#include "openscad.h"
#include "parsersettings.h"
#include "PlatformUtils.h"
#include "printutils.h"
#include "stackcheck.h"
#include "Tree.h"
#include "value.h"

namespace fs = boost::filesystem;

static std::mutex g_moz_mutex;
static std::string g_moz_log;
std::string commandline_commands;

static void moz_log_handler(const Message &msg, void *)
{
  if (msg.group == message_group::Error || msg.group == message_group::Warning) {
    g_moz_log += msg.msg;
    g_moz_log += "\n";
  }
}

static void moz_set_err(char **err, const char *fmt, ...)
{
  if (!err) return;
  va_list ap;
  va_start(ap, fmt);
  char buf[2048];
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  *err = strdup(buf);
}

static void moz_ensure_init()
{
  static const bool inited = []() {
    StackCheck::inst();
    PlatformUtils::registerApplicationPath("");
#ifdef ENABLE_CGAL
    CGAL::set_error_behaviour(CGAL::ABORT);
#endif
    Builtins::instance()->initialize();
    parser_init();
    return true;
  }();
  (void)inited;
}

struct moz_geom {
  std::shared_ptr<const Geometry> geom;  // 求值后的几何（空几何时为 CGAL_Nef_polyhedron 空对象）
  AbstractNode *node_tree;               // 实例化出的节点树（free 时递归释放）
  FileModule *root_module;               // 解析出的模块树（free 时释放）
  std::string docpath;
  int dimension;                         // 2 / 3 / 0（空）
};

static std::string moz_read_file(const std::string &path)
{
  std::ifstream ifs(path.c_str(), std::ios::binary);
  if (!ifs.is_open()) return std::string();
  return std::string((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
}

/* 解析 + 实例化 + 几何求值 */
static moz_geom *moz_do_eval(const std::string &text, const std::string &docname,
                             const char *const *assignments, int n_assignments, char **err)
{
  g_moz_log.clear();
  set_output_handler(moz_log_handler, nullptr, nullptr);

  std::string cmdline;
  for (int i = 0; i < n_assignments; ++i) {
    cmdline += assignments[i];
    cmdline += ";\n";
  }
  std::string full = text;
  if (!cmdline.empty()) full += "\n\x03\n" + cmdline;

  // 与 do_export 一致：切换到文档目录，保证 import/use 相对路径正确；结束后恢复
  const fs::path original = fs::current_path();
  fs::path docparent;
  if (!docname.empty() && docname != "<stdin>") {
    docparent = fs::absolute(fs::path(docname)).parent_path();
    if (fs::is_directory(docparent)) fs::current_path(docparent);
  }

  FileModule *root_module = nullptr;
  if (!parse(root_module, full, docname, docname, false)) {
    delete root_module;
    root_module = nullptr;
  }
  if (!root_module) {
    moz_set_err(err, "Can't parse input: %s", g_moz_log.c_str());
    fs::current_path(original);
    return nullptr;
  }
  CommentParser::collectParameters(full.c_str(), root_module);
  root_module->handleDependencies();

  moz_geom *g = new moz_geom();
  g->node_tree = nullptr;
  g->root_module = root_module;
  g->docpath = docparent.string();

  Tree tree;
  tree.setDocumentPath(g->docpath);

  ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
  top_ctx->set_variable("$preview", Value(false));

  ModuleInstantiation root_inst("group");
  ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
  AbstractNode *absolute_root_node = root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);
  if (!absolute_root_node) {
    moz_set_err(err, "Failed to instantiate root module: %s", g_moz_log.c_str());
    delete g;  // 内部包含 root_module，一并释放
    fs::current_path(original);
    return nullptr;
  }

  const AbstractNode *root_node = nullptr;
  const Location *nextLocation = nullptr;
  root_node = find_root_tag(absolute_root_node, &nextLocation);
  if (!root_node) root_node = absolute_root_node;
  tree.setRoot(root_node);

  GeometryEvaluator geomevaluator(tree);
  g->geom = geomevaluator.evaluateGeometry(*tree.root(), true);
  if (!g->geom) g->geom.reset(new CGAL_Nef_polyhedron());

  g->node_tree = absolute_root_node;
  g->dimension = (!g->geom || g->geom->isEmpty()) ? 0 : static_cast<int>(g->geom->getDimension());

  fs::current_path(original);
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
  const std::string text = moz_read_file(path);
  if (text.empty()) {
    moz_set_err(err, "Can't open input file '%s'", path);
    return nullptr;
  }
  return moz_do_eval(text, std::string(path), assignments, n_assignments, err);
}

extern "C" int moz_geom_dimension(const moz_geom *g)
{
  if (!g) return -1;
  return g->dimension;
}

extern "C" void moz_geom_free(moz_geom *g)
{
  if (!g) return;
  delete g->node_tree;    // AbstractNode 析构递归释放整棵节点树
  delete g->root_module;  // 模块树
  delete g;
}

extern "C" void moz_str_free(char *s) { free(s); }
extern "C" void moz_bytes_free(unsigned char *p) { free(p); }

/* 导出实现：out 为 NULL 时写文件（outfile），否则导出到内存缓冲 */
static int moz_export_impl(const moz_geom *g, const char *format, const char *outfile,
                           unsigned char **out, size_t *out_len, char **err)
{
  if (!g) {
    moz_set_err(err, "null geometry handle");
    return -1;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  g_moz_log.clear();

  const std::string sfmt = format ? format : "";
  ExportFileFormatOptions opts;
  const auto it = opts.exportFileFormats.find(sfmt);
  if (it == opts.exportFileFormats.end()) {
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
    if (g->dimension == 3) {
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
  exportInfo.sourceFilePath = g->docpath;
  exportInfo.sourceFileName = outfile ? fs::path(outfile).filename().string() : "";
  exportInfo.useStdOut = false;

  if (fmt == FileFormat::PNG) {
    // PNG 走渲染路径而非 exportFile（exportFile 的 switch 不覆盖 PNG）
    ViewOptions options;
    options.renderer = RenderType::CGAL;
    Camera camera;
    camera.viewall = true;
    camera.autocenter = true;
    camera.pixel_width = 800;
    camera.pixel_height = 600;
    if (out) {
      std::ostringstream oss(std::ios::out | std::ios::binary);
      if (!export_png(g->geom, options, camera, oss)) {
        moz_set_err(err, "PNG rendering failed: %s", g_moz_log.c_str());
        return -5;
      }
      const std::string &s = oss.str();
      auto *buf = static_cast<unsigned char *>(malloc(s.size() ? s.size() : 1));
      if (!s.empty()) memcpy(buf, s.data(), s.size());
      *out = buf;
      *out_len = s.size();
    } else {
      std::ofstream f(outfile, std::ios::out | std::ios::binary | std::ios::trunc);
      if (!f.is_open()) {
        moz_set_err(err, "Can't open file '%s' for export", outfile);
        return -6;
      }
      if (!export_png(g->geom, options, camera, f)) {
        moz_set_err(err, "PNG rendering failed: %s", g_moz_log.c_str());
        return -5;
      }
    }
    return 0;
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

static int moz_render_png_impl(const moz_geom *g, unsigned int width, unsigned int height,
                               const char *outfile, unsigned char **out, size_t *out_len, char **err)
{
  if (!g) {
    moz_set_err(err, "null geometry handle");
    return -1;
  }
  std::lock_guard<std::mutex> lock(g_moz_mutex);
  g_moz_log.clear();

  ViewOptions options;
  options.renderer = RenderType::CGAL;
  Camera camera;
  camera.viewall = true;
  camera.autocenter = true;
  camera.pixel_width = width;
  camera.pixel_height = height;

  if (out) {
    std::ostringstream oss(std::ios::out | std::ios::binary);
    if (!export_png(g->geom, options, camera, oss)) {
      moz_set_err(err, "PNG rendering failed: %s", g_moz_log.c_str());
      return -5;
    }
    const std::string &s = oss.str();
    auto *buf = static_cast<unsigned char *>(malloc(s.size() ? s.size() : 1));
    if (!s.empty()) memcpy(buf, s.data(), s.size());
    *out = buf;
    *out_len = s.size();
  } else {
    std::ofstream f(outfile, std::ios::out | std::ios::binary | std::ios::trunc);
    if (!f.is_open()) {
      moz_set_err(err, "Can't open file '%s' for export", outfile);
      return -6;
    }
    if (!export_png(g->geom, options, camera, f)) {
      moz_set_err(err, "PNG rendering failed: %s", g_moz_log.c_str());
      return -5;
    }
  }
  return 0;
}

extern "C" int moz_render_png(const moz_geom *g, const char *outfile,
                              unsigned int width, unsigned int height, char **err)
{
  if (!outfile) {
    moz_set_err(err, "null outfile");
    return -6;
  }
  return moz_render_png_impl(g, width, height, outfile, nullptr, nullptr, err);
}

extern "C" int moz_render_png_bytes(const moz_geom *g, unsigned int width, unsigned int height,
                                    unsigned char **out, size_t *out_len, char **err)
{
  if (!out || !out_len) {
    moz_set_err(err, "null out/out_len");
    return -7;
  }
  *out = nullptr;
  *out_len = 0;
  return moz_render_png_impl(g, width, height, nullptr, out, out_len, err);
}

/* 文本 dump：csg / ast / term / echo（不需要几何求值） */
static char *moz_dump_impl(const std::string &text, const std::string &docname, const char *format,
                           const char *const *assignments, int n_assignments, char **err)
{
  g_moz_log.clear();
  set_output_handler(moz_log_handler, nullptr, nullptr);

  std::string cmdline;
  for (int i = 0; i < n_assignments; ++i) {
    cmdline += assignments[i];
    cmdline += ";\n";
  }
  std::string full = text;
  if (!cmdline.empty()) full += "\n\x03\n" + cmdline;

  const fs::path original = fs::current_path();
  if (!docname.empty() && docname != "<stdin>") {
    const fs::path docparent = fs::absolute(fs::path(docname)).parent_path();
    if (fs::is_directory(docparent)) fs::current_path(docparent);
  }

  FileModule *root_module = nullptr;
  if (!parse(root_module, full, docname, docname, false)) {
    delete root_module;
    root_module = nullptr;
  }
  if (!root_module) {
    moz_set_err(err, "Can't parse input: %s", g_moz_log.c_str());
    fs::current_path(original);
    return nullptr;
  }
  CommentParser::collectParameters(full.c_str(), root_module);
  root_module->handleDependencies();

  std::string result;
  AbstractNode *absolute_root_node = nullptr;
  const std::string sfmt = format ? format : "csg";

  if (sfmt == "ast") {
    result = root_module->dump("");
  } else {
    Tree tree;
    tree.setDocumentPath(docname);
    ContextHandle<BuiltinContext> top_ctx{Context::create<BuiltinContext>()};
    top_ctx->set_variable("$preview", Value(false));
    ModuleInstantiation root_inst("group");
    ContextHandle<FileContext> filectx{Context::create<FileContext>(top_ctx.ctx)};
    absolute_root_node = root_module->instantiateWithFileContext(filectx.ctx, &root_inst, nullptr);

    const AbstractNode *root_node = nullptr;
    const Location *nextLocation = nullptr;
    root_node = find_root_tag(absolute_root_node, &nextLocation);
    if (!root_node) root_node = absolute_root_node;
    tree.setRoot(root_node);

    if (sfmt == "csg") {
      result = tree.getString(*root_node, "\t") + "\n";
    } else if (sfmt == "term") {
      CSGTreeEvaluator csg(tree);
      const shared_ptr<CSGNode> root_raw_term = csg.buildCSGTree(*root_node);
      if (!root_raw_term || root_raw_term->isEmptySet()) {
        result = "No top-level CSG object\n";
      } else {
        result = root_raw_term->dump() + "\n";
      }
    } else if (sfmt == "echo") {
      result = "";  // echo 副作用写入 stdout，此处不捕获
    } else {
      moz_set_err(err, "unknown dump format '%s' (csg|ast|term|echo)", format);
      delete absolute_root_node;
      delete root_module;
      fs::current_path(original);
      return nullptr;
    }
  }

  delete absolute_root_node;
  delete root_module;
  fs::current_path(original);

  char *out = strdup(result.c_str());
  return out;
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
  const std::string text = moz_read_file(path);
  if (text.empty()) {
    moz_set_err(err, "Can't open input file '%s'", path);
    return nullptr;
  }
  return moz_dump_impl(text, std::string(path), format, assignments, n_assignments, err);
}