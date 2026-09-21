import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def build():
    # intersection_for(i = [...]) → intersection() 展开各次迭代。
    angles = [
        [0, 0, 0],
        [10, 20, 300],
        [200, 40, 57],
        [20, 88, 57],
    ]
    return moz.intersection(*[moz.rotate(i, moz.cube([100, 20, 20], center=True)) for i in angles])


if __name__ == "__main__":
    build().show(title="moz - Old/example014")