"""examples/Old/example016.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))
STL = DATA / "example016.stl"


def _fmt(value):
    """SCAD 字面量：float 用 repr 精确往返，与绑定层的格式化一致。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt(item) for item in value) + "]"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def render(child, **params):
    """render(convexity = N)：F6 下只透传几何，convexity 不影响形状，照原样保留。"""
    child_src = child if isinstance(child, str) else child.source
    options = ", ".join(f"{name} = {_fmt(value)}" for name, value in params.items())
    return moz.Shape(f"render({options}) {child_src}")


def blk1():
    return moz.cube([65, 28, 28], center=True)


def blk2():
    return moz.difference(
        moz.translate([0, 0, 7.5], moz.cube([60, 28, 14], center=True)),
        moz.cube([8, 32, 32], center=True),
    )


def chop():
    return moz.translate([-18, 0, 0], moz.import_shape(str(STL), convexity=12))


def build():
    # for 循环在原文件里是一个 group，作为 difference 的单个子对象参与运算。
    return moz.difference(
        blk1(),
        moz.union(*[moz.rotate(alpha, [1, 0, 0], render(moz.difference(blk2(), chop()), convexity=12))
                    for alpha in (0, 90, 180, 270)]),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example016")