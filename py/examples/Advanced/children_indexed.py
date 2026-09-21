import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def align_in_grid_and_add_text(children):
	count = len(children)
	if count == 0:
		return moz.linear_extrude(moz.text("Nothing...", 6, halign="center"), height=1, center=True)
	label = "one object" if count == 1 else f"{count} objects "
	items = [moz.linear_extrude(moz.text(label, 6, halign="center"), height=1, center=True)]
	for y in range(count):
		for x in range(count):
			items.append(moz.translate([15 * (x - (count - 1) / 2), 20 * y + 40, 0], moz.scale(1 + x / count, children[y])))
	return moz.union(*items)

def build():
	return moz.union(
		moz.color(moz.translate([-100, -20, 0], align_in_grid_and_add_text([])), "red"),
		moz.color(moz.translate([-50, -20, 0], align_in_grid_and_add_text([moz.cube(5, center=True)])), "yellow"),
		moz.color(moz.translate([0, -20, 0], align_in_grid_and_add_text([moz.cube(5, center=True), moz.sphere(4)])), "cyan"),
		moz.color(moz.translate([50, -20, 0], align_in_grid_and_add_text([moz.cube(5, center=True), moz.sphere(4), moz.cylinder(r=4, h=5)])), "green"),
	)

if __name__ == "__main__":
	build().show(title="moz - Advanced/children_indexed")
