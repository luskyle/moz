"""Python API version of OpenSCAD examples/Basics/CSG-modules.scad."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moz_openscad as moz


def body():
	return moz.color(moz.sphere(10), "Blue")


def intersector():
	return moz.color(moz.cube(15, center=True), "Red")


def hole_object():
	return moz.color(moz.cylinder(h=20, r=5, center=True), "Lime")


def build():
	intersected = moz.intersection(body(), intersector())
	holes = moz.union(
		moz.rotate([0, 90, 0], hole_object()),
		moz.rotate([90, 0, 0], hole_object()),
		hole_object(),
	)
	return moz.difference(intersected, holes)


def main():
	shape = build()
	print("CSG-modules Python API dimension:", shape.dimension)
	shape.show(title="moz - Basics/CSG-modules")


if __name__ == "__main__":
	main()
