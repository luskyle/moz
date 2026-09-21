import sys
from pathlib import Path
import math
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

def build():
    shell = moz.difference(moz.cylinder(h=50, r=100), moz.translate([0, 0, 10], moz.cylinder(h=50, r=80)), moz.translate([100, 0, 35], moz.cube(50, center=True)))
    pillars = []
    for i in range(6):
        angle = 360 * i / 6
        pillars.append(moz.translate([math.sin(math.radians(angle)) * 80, math.cos(math.radians(angle)) * 80, 0], moz.cylinder(h=200, r=10)))
    roof = moz.translate([0, 0, 200], moz.cylinder(h=80, r1=120, r2=0))
    return moz.translate([0, 0, -120], moz.union(shell, *pillars, roof))

if __name__ == "__main__":
    build().show(title="moz - Old/example005")
