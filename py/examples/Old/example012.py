import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))


def build():
    stl = str(DATA / "example012.stl")

    return moz.difference(
        moz.sphere(20),
        moz.translate([-2.92, 0.5, +20], moz.rotate([180, 0, 180], moz.import_shape(stl, convexity=5))),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example012")