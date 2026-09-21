import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def example004():
    return moz.difference(moz.cube(30, center=True), moz.sphere(20))

def build():
    return example004()

if __name__ == "__main__":
    build().show(title="moz - Old/example004")
