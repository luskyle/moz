import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def build():
    points = [
        [10, 0, 0],
        [0, 10, 0],
        [-10, 0, 0],
        [0, -10, 0],
        [0, 0, 10],
    ]
    triangles = [
        [0, 1, 2, 3],
        [4, 1, 0],
        [4, 2, 1],
        [4, 3, 2],
        [4, 0, 3],
    ]
    return moz.polyhedron(points, triangles=triangles)


if __name__ == "__main__":
    build().show(title="moz - Old/example011")