"""Python API version of OpenSCAD examples/Basics/CSG.scad."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moz_openscad as moz


def build():
	joined = moz.union(moz.cube(15, center=True), moz.sphere(10))
	clipped = moz.intersection(moz.cube(15, center=True), moz.sphere(10))
	hollow = moz.difference(moz.cube(15, center=True), moz.sphere(10))
	return moz.union(
		moz.translate([-24, 0, 0], joined),
		clipped,
		moz.translate([24, 0, 0], hollow),
	)


def main():
	shape = build()
	print("CSG Python API dimension:", shape.dimension)
	shape.show(title="moz - Basics/CSG")


if __name__ == "__main__":
	main()
