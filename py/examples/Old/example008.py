"""examples/Old/example008.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))
DXF = DATA / "example008.dxf"


def build():
    return moz.difference(
        moz.intersection(
            moz.translate([-25, -25, -25],
                moz.linear_extrude(moz.import_shape(str(DXF), layer="G"), height=50, convexity=3)),
            moz.rotate(90, [1, 0, 0],
                moz.translate([-25, -125, -25],
                    moz.linear_extrude(moz.import_shape(str(DXF), layer="E"), height=50, convexity=3))),
            moz.rotate(90, [0, 1, 0],
                moz.translate([-125, -125, -25],
                    moz.linear_extrude(moz.import_shape(str(DXF), layer="B"), height=50, convexity=3))),
        ),
        moz.intersection(
            moz.translate([-125, -25, -26],
                moz.linear_extrude(moz.import_shape(str(DXF), layer="X"), height=52, convexity=1)),
            moz.rotate(90, [0, 1, 0],
                moz.translate([-125, -25, -26],
                    moz.linear_extrude(moz.import_shape(str(DXF), layer="X"), height=52, convexity=1))),
        ),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example008")