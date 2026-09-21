import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def f(x):
	return 0.5 * x + 1


def g(x):
	return [5 * x + 20, f(x) * f(x) - 50, 0]

def build():
	cubes = []
	for a in range(-100, 101, 5):
		cubes.append(moz.translate([a, f(a), 0], moz.cube(2, center=True)))

	spheres = []
	for a in range(-200, 201, 10):
		spheres.append(moz.translate(g(a / 8), moz.sphere(1)))

	return moz.union(
		moz.color(moz.union(*cubes), "red"),
		moz.color(moz.union(*spheres), "green"),
	)

if __name__ == "__main__":
	build().show(title="moz - Functions/functions")
