import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

def build():
	rectangle = moz.square([20, 10], center=True)
	return moz.union(
		moz.color(moz.translate([0, -30, 0], moz.linear_extrude(rectangle, height=20)), "red"),
		moz.color(moz.translate([-30, 0, 0], moz.linear_extrude(rectangle, height=20, scale=0.2)), "green"),
		moz.color(moz.translate([30, 0, 0], moz.linear_extrude(rectangle, height=20, twist=90)), "cyan"),
		moz.color(moz.translate([0, 30, 0], moz.linear_extrude(rectangle, height=40, twist=-360, scale=0, center=True, slices=200)), "gray"),
	)

if __name__ == "__main__":
	build().show(title="moz - Basics/linear_extrude")
