"""examples/Old/example007.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))
DXF = DATA / "example007.dxf"


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
    """render(convexity = N)：F6 下只透传几何，convexity 不影响形状，这里照原样保留。"""
    child_src = child if isinstance(child, str) else child.source
    options = ", ".join(f"{name} = {_fmt(value)}" for name, value in params.items())
    return moz.Shape(f"render({options}) {child_src}")


def cutout():
    return moz.intersection(
        moz.rotate(90, [1, 0, 0],
            moz.translate([0, 0, -50],
                moz.linear_extrude(moz.import_shape(str(DXF), layer="cutout1"),
                                   height=100, convexity=1))),
        moz.rotate(90, [0, 0, 1],
            moz.rotate(90, [1, 0, 0],
                moz.translate([0, 0, -50],
                    moz.linear_extrude(moz.import_shape(str(DXF), layer="cutout2"),
                                       height=100, convexity=2)))),
    )


def clip():
    return moz.difference(
        # rotate_extrude(convexity = 3, $fn = 0, $fa = 12, $fs = 2)
        moz.rotate_extrude(moz.import_shape(str(DXF), layer="dorn"),
                           convexity=3, fn=0, fa=12, fs=2),
        # for (r = [0, 90]) rotate(r, [0, 0, 1]) cutout();
        # for 循环在原文件里是一个 group，作为 difference 的单个子对象参与运算。
        moz.union(*[moz.rotate(r, [0, 0, 1], cutout()) for r in (0, 90)]),
    )


def cutview():
    """原文件的 cutview()（原文件里被注释掉、未调用）。# 高亮只影响预览，几何等同普通对象。"""
    window = moz.rotate(20, [0, 0, 1],
        moz.rotate(-20, [0, 1, 0],
            moz.translate([18, 0, 0], moz.cube(30, center=True))))

    return moz.difference(
        moz.difference(moz.translate([0, 0, -10], clip()), window),
        render(moz.intersection(moz.translate([0, 0, -10], clip()), window), convexity=5),
    )


def build():
    # 原文件末尾实际生效的是 translate([0, 0, -10]) clip();（cutview() 被注释掉了）。
    return moz.translate([0, 0, -10], clip())


if __name__ == "__main__":
    build().show(title="moz - Old/example007")