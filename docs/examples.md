# 示例

`py/examples/` 下 48 个示例，分类与文件名**完全对应**上游
`3rd/openscad/examples/`（也就是 GUI 示例库里的那份 `examples.json`）：

| 分类 | 数量 | 依赖外部数据的示例 |
| --- | --- | --- |
| `Basics/` | 9 | `projection.stl`（stl 导入） |
| `Functions/` | 5 | 无（`echo` 只打印、不产生几何） |
| `Advanced/` | 8 | `surface_image.png`（高度图） |
| `Parametric/` | 2 | `sign.json`、`candleStand.json`（参数集） |
| `Old/` | 24 | `example007/008/009/013/015.dxf`、`example010.dat`、`example012/016.stl`，以及 `MCAD/fonts.scad`（仅 023） |

另有 `moz/` 分类（**不是**上游示例的翻译，上游没有对应 `.scad`，因此**不在**
`py/verify_examples.py` 的比对范围内）：放 moz 在 OpenSCAD 之上新增能力的示例。

| 文件 | 演示 |
| --- | --- |
| `moz/measure.py` | `Geometry.measure`（包围盒/体积/表面积/面数/顶点数/质心）、导出选项、`add_library_path`/`library_paths` |
| `moz/animation.py` | **在窗口里播放动画**（`moz.show_animation`）+ `--export` 用 `moz.eval_animation` 逐帧导出；含 `$t` 用法陷阱的说明 |

`measure.py` 支持 `--no-show`（不弹窗口，只打印）；`animation.py` 默认播放，`--no-show --export`
则只导出。便于无显示环境跑。

## 文件约定

```python
"""examples/Basics/CSG.scad 的 Python 版本。"""     # 文件头说明对应哪个 .scad

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # py/ 进 sys.path
import moz_openscad as moz


def build():                     # 唯一必须暴露的入口，返回 Shape
    ...


if __name__ == "__main__":
    build().show(title="moz - Basics/CSG")
```

- `build()` 不接受必填参数；原 `.scad` 里可调的（`Old/example017.scad` 的 `mode`、
  `Parametric/*` 的参数集、`Advanced/animation.scad` 的 `$t`）做成**可选参数**：
  `build(mode="assembled")` / `build(parameter_set="small")` / `build(t=0.0)`。
- 同目录的 `.py` 之间可以互相 import（例如 `Basics/logo_and_text.py` 复用 `Basics/logo.py`
  的 `logo()`，对应原文件的 `use <logo.scad>`）。

## 引用外部数据文件

原 `.scad` 里的相对文件名（`import(file = "example009.dxf")`）是相对**它自己所在目录**解析的；
Python 版构造源码时没有文档目录，写相对名会**静默变成空几何**。所以统一写绝对路径，并且
**指向原始示例目录里的同一份文件**（不拷贝数据）：

```python
ROOT = Path(__file__).resolve().parents[3]              # 仓库根
DXF  = ROOT / "3rd" / "openscad" / "examples" / "Old" / "example009.dxf"
moz.import_shape(str(DXF), layer="body")
```

`parents[2]` 是 `py/`，`parents[3]` 才是仓库根——写错一位就会得到空几何。

参数集同理：

```python
PARAMETER_FILE = ROOT / "3rd" / "openscad" / "examples" / "Parametric" / "sign.json"
def parameter_sets(): ...          # json.load(...)["parameterSets"]
def build(parameter_set=None, **overrides): ...
```

## 三种「原文件里有、Python 里要特殊处理」的写法

| 原写法 | Python 里怎么处理 |
| --- | --- |
| `%对象;`（背景修饰符） | **不放进 `build()` 的返回值**：它在 F6/导出里被排除（本地预览才显示）。在代码注释里写明原语句 |
| `#对象;`（高亮） | 只影响预览，几何上等同普通对象，照常包含 |
| `render(convexity = N) ...` | 在 F6 下只透传几何，但会在 CSG 树里产生节点（影响导出顺序），所以**照原样保留**：示例里用局部 `render()` 文本助手发出去 |

## 跑示例

```bash
PYTHONPATH=py python3 py/examples/Basics/CSG.py           # 打开预览器（窗口里可旋转/缩放）
PYTHONPATH=py python3 py/examples/Old/example017.py       # 默认 mode="assembled"
PYTHONPATH=py python3 -c "
import importlib.util, sys; sys.path.insert(0,'py')
spec = importlib.util.spec_from_file_location('m','py/examples/Advanced/animation.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.build(t=0.25).export('binstl','/tmp/anim.stl')"          # 取动画第 0.25 帧
```

## 校验示例

```bash
PYTHONPATH=py python3 py/verify_examples.py                # 全部 48 个
PYTHONPATH=py python3 py/verify_examples.py Old            # 只跑一个分类
PYTHONPATH=py python3 py/verify_examples.py Old/example023 Advanced/GEB   # 点名若干
```

判据与当前结果见 [verification.md](verification.md)。

## 与上游示例的差别（有意为之）

- **不做「等价简化」**：布尔的嵌套层级、参数写法、`for`/`if` 的位置都尽量照原样，
  因为 CGAL 的布尔顺序会影响导出面序。示例里偶尔能看到为此写下的注释。
- `%` 背景对象不参与几何（见上），所以 Python 版看不到它们。
- 顶层 `py/examples/basic_*.py` / `function_*.py` 这批「手写直构造」版本已经删除，
  统一由分类目录下的 48 个文件承担；近似几何库 `_direct.py` 也一并删除。

## 把一个新 `.scad` 迁移成 Python 示例的清单

1. 先把原文件逐行读一遍，标出：外部文件、`$fn/$fa/$fs` 的出现位置与作用范围、
   `%`/`#`/`render()` 修饰符、递归/`for`/`if`、以及**位置参数**（`offset(10)`、`cylinder(50,2)`）。
2. 用 `moz.*` 原语照结构翻译，**不要合并或重排**布尔层级。
3. `$fn/$fa/$fs`：具名参数优先；对应顶层/模块级赋值的用 `moz.settings(...)`。
4. 自己算坐标/角度的地方一律用 `moz.sin_deg/cos_deg/acos_deg/atan2_deg`；浮点 `for` 用 `while` 累加复刻。
5. 运行 `PYTHONPATH=py python3 py/verify_examples.py <分类>/<名字>`，直到 `[OK]`。
   如果停在「几何不一致」，看它给出的体积/表面积/包围盒差异，再回到 [scad-semantics.md](scad-semantics.md) 逐条对照。