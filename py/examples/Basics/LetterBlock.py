import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

def build():
	letter, size = "M", 30
	block = moz.translate([0, 0, size / 4], moz.cube([size, size, size / 2], center=True))
	cutout = moz.translate(
		[0, 0, size / 6],
		moz.linear_extrude(
			moz.text(letter, size=size * 22 / 30, font="Bitstream Vera Sans", halign="center", valign="center"),
			height=size,
		),
	)
	return moz.difference(block, cutout)

if __name__ == "__main__":
	build().show(title="moz - Basics/LetterBlock")
