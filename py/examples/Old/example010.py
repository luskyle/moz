import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 数据文件随包分发在 moz_data/examples/Old/ 下（与上游示例目录同名，已复制一份），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(moz.data_path("examples", "Old"))


def build():
    data = str(DATA / "example010.dat")

    return moz.intersection(
        moz.surface(data, center=True, convexity=5),
        moz.rotate(45, [0, 0, 1], moz.surface(data, center=True, convexity=5)),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example010")