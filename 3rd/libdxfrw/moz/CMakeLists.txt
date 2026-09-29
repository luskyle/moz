# moz: 上游 libdxfrw（DXF/DWG 解析核心）封装成共享库 + C ABI（见 moz_cadio.h / moz_cadio.cc）
#
# 源清单与 3rd/libdxfrw/libdxfrw_sources.cmake（上游自己的清单）一致：36 个 .cpp。
# 纯 C++、**不依赖 Qt、不依赖 zlib**（DWG 解压自带），也不需要几何内核。
#
# 为什么不用 LibreCAD 树里那份 libdxfrw：那是 0.5.11 时代的拷贝，实测读不了 AC1018+
# 的真实 DWG（BAD_READ_BLOCKS / BAD_READ_FILE_HEADER），且在 AC1014 上少读 41 个实体；
# 上游 2.0.0 多了 dwgreaderR11/R1_40/32，覆盖面 R1.40–2018+。详见 docs/third-party.md。
#
# 构建：bash scripts/build_moz_cadio.sh
cmake_minimum_required(VERSION 3.16)
project(moz_cadio CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(LIBDXFRW "${CMAKE_CURRENT_SOURCE_DIR}/../src")
set(DXFRW_SOURCES
  ${LIBDXFRW}/intern/drw_dbg.cpp
  ${LIBDXFRW}/intern/drw_textcodec.cpp
  ${LIBDXFRW}/intern/dwgbuffer.cpp
  ${LIBDXFRW}/intern/dwgobjectframe.cpp
  ${LIBDXFRW}/intern/dwgbufferw.cpp
  ${LIBDXFRW}/intern/dwgwriter15.cpp
  ${LIBDXFRW}/intern/dwgwriter18.cpp
  ${LIBDXFRW}/intern/dwgwriter21.cpp
  ${LIBDXFRW}/intern/dwgwriter24.cpp
  ${LIBDXFRW}/intern/dwgwriter27.cpp
  ${LIBDXFRW}/intern/dwgwriter32.cpp
  ${LIBDXFRW}/intern/dwgreader.cpp
  ${LIBDXFRW}/intern/dwgreaderR1_40.cpp
  ${LIBDXFRW}/intern/dwgreaderR11.cpp
  ${LIBDXFRW}/intern/dwgreader15.cpp
  ${LIBDXFRW}/intern/dwgreader18.cpp
  ${LIBDXFRW}/intern/dwgreader21.cpp
  ${LIBDXFRW}/intern/dwgreader24.cpp
  ${LIBDXFRW}/intern/dwgreader27.cpp
  ${LIBDXFRW}/intern/dwgreader32.cpp
  ${LIBDXFRW}/intern/dwgutil.cpp
  ${LIBDXFRW}/intern/proxygraphicdecoder.cpp
  ${LIBDXFRW}/intern/dxfreader.cpp
  ${LIBDXFRW}/intern/dxfwriter.cpp
  ${LIBDXFRW}/intern/dwg_dxf_output_transaction.cpp
  ${LIBDXFRW}/intern/dwgwriterlayoutvalidation.cpp
  ${LIBDXFRW}/intern/rscodec.cpp
  ${LIBDXFRW}/drw_acis.cpp
  ${LIBDXFRW}/drw_base.cpp
  ${LIBDXFRW}/drw_classes.cpp
  ${LIBDXFRW}/drw_datastorage.cpp
  ${LIBDXFRW}/drw_entities.cpp
  ${LIBDXFRW}/drw_header.cpp
  ${LIBDXFRW}/drw_objects.cpp
  ${LIBDXFRW}/libdwgr.cpp
  ${LIBDXFRW}/libdxfrw.cpp
)

add_library(mozcadio SHARED ${DXFRW_SOURCES} ${CMAKE_CURRENT_SOURCE_DIR}/moz_cadio.cc)
target_include_directories(mozcadio PRIVATE ${LIBDXFRW} ${LIBDXFRW}/intern)
set_target_properties(mozcadio PROPERTIES
  OUTPUT_NAME cadio_moz
  # Windows/MSVC 的 DLL 不会像 .so/.dylib 那样默认导出符号：moz_cadio.py 用 ctypes
  # 按名找 moz_cad_* C ABI 函数，不导出会 AttributeError: function not found。
  # 该属性让 MSVC 生成 .def 导出全部符号（extern "C" 名原样导出）；非 Windows 无副作用。
  WINDOWS_EXPORT_ALL_SYMBOLS ON)