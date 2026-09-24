# DXF 回归语料

`py/verify_dxf.py` 的输入。**只用于开发期回归**（不进 wheel、不进运行时数据），目标是让
"图纸 → 模型"（P1）永远能在**现成的真实图纸**上被验证，而不是只跑我造的样例。

| 子目录 | 来源 | 许可 | 为什么收集它 |
| --- | --- | --- | --- |
| `librecad/` | [LibreCAD/LibreCAD](https://github.com/LibreCAD/LibreCAD) 的 `librecad/src/lib/filters/tests/testdata/dxf/`、`support/library/mechanical/`、`support/library/elektro/antenna*`、`res/dxf/` | GPLv2 | 前一组是 **LibreCAD 自己的 DXF 解析器测试集**（big5/hkscs 编码、R2007 的 classes/EED 二进制、块记录预览等脏活）；后两组是**真实零件/电气符号轮廓**（多数不闭合、图层名随意）——最接近"别人给的图" |
| `dxf-viewer/` | [vagran/dxf-viewer](https://github.com/vagran/dxf-viewer) 的 `test/fixtures/` | MIT | 块（含递归/实例化/摊平）、标注（对齐/箭头/颜色）、圆与圆弧等**专项**样例 |
| `three-dxf/` | [gdsestimating/three-dxf](https://github.com/gdsestimating/three-dxf) 的 `sample/` | MIT | 一个常规的整图样例 |
| `freecad-library/` | [FreeCAD/FreeCAD-library](https://github.com/FreeCAD/FreeCAD-library) | LGPL-2.1 | 真实机械件轮廓（例如 MIT Vent 呼吸机零件），图纸规模与命名都"像真的" |
| `local/` | 本项目 robot 仓库里的 `imu_to_dxl-板框-45x22-R2.dxf`（作者自己的图） | 作者自有 | **真实工程图**：45×22 R2 板框，用来验证"图名与几何一致" |
| `kicad/` | [KiCad](https://gitlab.com/kicad/code/kicad) 的 `qa/data/common/import_gfx/`、`common/import_gfx/examples/`、`qa/data/pcbnew/` | GPLv3 | PCB 板框（1 外 + 135 孔的轮廓）、Fusion360 导出的样条、椭圆、大坐标 |
| `openscad/` | 上游 OpenSCAD 的 `testdata/scad/misc/dim-all.dxf`（`3rd/openscad/testdata/` 里也有同一份） | GPLv2 | 标注专项：8 个标注，用来盯"标注 → 参数"这条通道；放这里是为了让语料目录自身能独立解释它 |

另外两组语料**已经在本仓库里**，`py/verify_dxf.py` 会一并扫：

- `3rd/openscad/testdata/**/*.dxf` —— vendored 的 OpenSCAD 测试集（圆/圆弧/椭圆含旋转与反向、
  LWPOLYLINE 与 bulge、INSERT 块、凹多边形、多孔、自交、重叠、缺单位、缺图层名…），
  许可见 [docs/third-party.md](../../docs/third-party.md)；
- `py/moz_data/drawings/*.dxf` —— 本项目的 P1 验收样例（由 `scripts/make_dxf_samples.py`
  字节级可复现地生成），随包分发。

## 怎么更新

```bash
python3 scripts/fetch_dxf_corpus.py            # 抓公开来源（已存在的不覆盖）
python3 scripts/fetch_dxf_corpus.py --dry-run  # 只看会抓什么
PYTHONPATH=py python3 py/verify_dxf.py         # 跑一遍回归
```

`local/`、`kicad/` 这两组来自本机，脚本不会自动抓；换机器时从原项目/上游原样拷过来即可
（文件内容就是唯一事实，没有额外转换）。

## 已知边界

- **互相交叉/重叠的线**不做平面细分（引擎 `import()` 也不做）：成环顺序不同时面积可能与原生相差
  ~10%，报告里会给出 `crossing_node` / `duplicate` 计数；
- **圆弧离散口径**与引擎不同（我们按弦高容差、引擎按 `$fn`）：带圆弧的图纸体积差 0.1~0.2%；
- **DWG** 不在这里：需要 ODA 转换器或 LibreDWG 先转 DXF（P4 的活，见
  [docs/2d-to-3d.md](../../docs/2d-to-3d.md)）。