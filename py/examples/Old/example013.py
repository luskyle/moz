"""examples/Old/example013.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))


def build():
    dxf = str(DATA / "example013.dxf")
    profile = moz.import_shape(dxf)

    return moz.intersection(
        moz.linear_extrude(profile, height=100, center=True, convexity=3),
        moz.rotate([0, 90, 0], moz.linear_extrude(profile, height=100, center=True, convexity=3)),
        moz.rotate([90, 0, 0], moz.linear_extrude(profile, height=100, center=True, convexity=3)),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example013")