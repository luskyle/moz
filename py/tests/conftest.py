"""pytest 配置：把 py/ 加进 sys.path，并在几何库不可用时跳过测试。"""

import sys
from pathlib import Path

import pytest

PY_ROOT = Path(__file__).resolve().parents[1]   # py/
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))


@pytest.fixture(scope="session")
def moz():
    """导入 moz_openscad；libmozopenscad.so 缺失/不可用时跳过整个测试。"""
    mod = pytest.importorskip("moz_openscad")
    try:
        mod.eval_text("cube(1);").close()
    except mod.OpenSCADError as exc:   # 还没构建库
        pytest.skip(f"libmozopenscad.so 不可用: {str(exc).strip().splitlines()[0][:120]}")
    return mod