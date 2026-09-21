import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def r_from_dia(d):
    return d / 2


def rotcy(rot, radius, height):
    return moz.rotate(90, rot, moz.cylinder(r=radius, h=height, center=True))

def build():
    size, hole = 50, 25
    return moz.difference(moz.sphere(r=r_from_dia(size)), rotcy([0, 0, 0], r_from_dia(hole), r_from_dia(size * 2.5)), rotcy([1, 0, 0], r_from_dia(hole), r_from_dia(size * 2.5)), rotcy([0, 1, 0], r_from_dia(hole), r_from_dia(size * 2.5)))

if __name__ == "__main__":
    build().show(title="moz - Old/example001")
