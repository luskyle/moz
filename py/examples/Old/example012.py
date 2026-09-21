import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 原 .scad 与本文件用同一个数据文件（3rd/openscad/examples/Old/ 下），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(__file__).resolve().parents[3] / "3rd" / "openscad" / "examples" / "Old"


def build():
    stl = str(DATA / "example012.stl")

    return moz.difference(
        moz.sphere(20),
        moz.translate([-2.92, 0.5, +20], moz.rotate([180, 0, 180], moz.import_shape(stl, convexity=5))),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example012")