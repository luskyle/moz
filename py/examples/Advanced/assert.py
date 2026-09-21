import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def size(value):
	assert value % 2 == 0, "Size must be an even number"
	return value


def ring(radius=10, count=3, cube_size=6):
	assert radius >= 10, "Parameter r must be >= 10"
	assert 3 <= count <= 20, "Parameter cnt must be between 3 and 20"
	return moz.union(*[
		moz.rotate([0, 0, angle], moz.translate([radius, 0, 0], moz.cube(size(cube_size), center=True)))
		for angle in [index * 360 / count for index in range(count)]
	])

def build():
	return moz.union(moz.color(ring(10, 3, 4), "red"), moz.color(ring(25, 9, 6), "green"), moz.color(ring(40, 20, 8), "blue"))

if __name__ == "__main__":
	build().show(title="moz - Advanced/assert")
