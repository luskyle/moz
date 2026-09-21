import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

def build():
    body = moz.union(moz.cube([30, 30, 30], center=True), moz.translate([0, 0, -25], moz.cube([15, 15, 50], center=True)))
    holes = moz.union(moz.cube([50, 10, 10], center=True), moz.cube([10, 50, 10], center=True), moz.cube([10, 10, 50], center=True))
    return moz.intersection(moz.difference(body, holes), moz.translate([0, 0, 5], moz.cylinder(h=50, r1=20, r2=5, center=True)))

if __name__ == "__main__":
    build().show(title="moz - Old/example002")
