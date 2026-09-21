import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import math
import moz_openscad as moz


def make_ring_of(radius, count, child):
	return moz.union(*[
		moz.translate([radius * math.sin(math.radians(angle)), -radius * math.cos(math.radians(angle)), 0], moz.rotate([0, 0, angle], child))
		for angle in [index * 360 / count for index in range(count)]
	])


def something():
	return moz.union(moz.cube(10, center=True), moz.cylinder(r=2, h=12, fn=40), moz.translate([0, 0, 12], moz.rotate([90, 0, 0], moz.linear_extrude(moz.text("SCAD", 8, halign="center"), height=2, center=True))), moz.translate([0, 0, 12], moz.cube([22, 1.6, 0.4], center=True)))

def build():
	cube_ring = make_ring_of(15, 6, moz.cube(8, center=True))
	cut_ring = make_ring_of(30, 12, moz.difference(moz.sphere(5), moz.cylinder(r=2, h=12, center=True)))
	complex_ring = make_ring_of(50, 4, something())
	return moz.union(moz.color(cube_ring, "red"), moz.color(cut_ring, "green"), moz.color(complex_ring, "cyan"))

if __name__ == "__main__":
	build().show(title="moz - Advanced/children")
