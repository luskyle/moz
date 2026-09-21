# moz 文档

项目目标与设计理念（为什么自然语言不适合直接定义几何、为什么盯着 2D 工程图）见仓库根目录的 [README](../README.md)。
这里放实现层面的文档。

## 文档地图

| 我想…… | 看这个 |
| --- | --- |
| 先跑起来看效果 | [快速开始](#快速开始) |
| 重建 `libmozopenscad.so` | [build.md](build.md) |
| 用 Python 建模 | [python-api.md](python-api.md) |
| 直接调 C ABI | [c-api.md](c-api.md) |
| 搞懂三层是怎么搭起来的 | [architecture.md](architecture.md) |
| 确认「Python 版和原生 .scad 是不是同一个东西」 | [verification.md](verification.md) |
| 翻译 SCAD 几何时别踩坑 | [scad-semantics.md](scad-semantics.md) |
| 跑/看/写示例 | [examples.md](examples.md) |
| 用预览器看模型 | [viewer.md](viewer.md) |
| 知道现在还不能做什么 | [limitations.md](limitations.md) |
| 下一步要加/优化什么 | [roadmap.md](roadmap.md) |
| 第三方组件与许可 | [third-party.md](third-party.md) |

## 快速开始

前置：Python ≥ 3.10、`numpy`、`PySide6`（预览器用）、以及一个已经构建好的几何库。

```bash
# 1) 构建几何库（首次约 3~5 分钟；改过 C++ 后增量约 30 秒）
JOBS=$(nproc) bash scripts/build_moz_openscad.sh

# 2) 直接用 Python 建模并导出
PYTHONPATH=py python3 -c "
import moz_openscad as moz
shape = moz.difference(moz.cube(20, center=True), moz.sphere(12))
shape.export('binstl', '/tmp/out.stl')
print('dimension =', shape.dimension, '| empty =', shape.is_empty)
"

# 3) 跑某个示例（示例暴露 build()，返回一个 Shape）
PYTHONPATH=py python3 py/examples/Basics/CSG.py          # 会打开预览器窗口

# 4) 校验示例与原生 .scad 是否同一个几何
PYTHONPATH=py python3 py/verify_examples.py Basics/CSG

# 5) 跑单元测试（pytest；不需要显示器的用例也可跑）
python3 -m pytest                     # 在仓库根目录执行
python3 -m pytest -v                  # 看每个用例名
python3 -m pytest py/tests/test_measure.py::test_cube_measure   # 单个用例
```

`py/verify_examples.py` 的判定标准见 [verification.md](verification.md)（当前 48 个示例全部通过）。
单元测试在 `py/tests/`，覆盖测量、导出、取值、动画、库路径、网格颜色、`Shape` 缓存与 viewer 逻辑。

测试的前置：

- 需要 `pytest`（`pip install pytest`；或 `pip install -e ".[test]"`）。**用你装了依赖的那个解释器**跑，
  否则会出现"没反应/全 skip"——例如只有 `pytest` 没装、或 `numpy`/`PySide6` 缺失时 viewer 用例会被 skip。
- 还没构建 `libmozopenscad.so` 时，整个测试集会 **skip**（不会报错）。build 见 [build.md](build.md)。
- 在仓库根目录跑即可（`pyproject.toml` 里已设 `testpaths = ["py/tests"]`，无需设 `PYTHONPATH`）。