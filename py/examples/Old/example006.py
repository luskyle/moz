import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def rounded_cube(size, radius, center=False):
    values = [size, size, size] if isinstance(size, (int, float)) else size
    points = []
    for x in (radius, values[0] - radius):
        for y in (radius, values[1] - radius):
            for z in (radius, values[2] - radius):
                points.append(moz.translate([x, y, z], moz.sphere(r=radius)))
    result = moz.hull(*points)
    return moz.translate([-values[0] / 2, -values[1] / 2, -values[2] / 2], result) if center else result

def build():
    body = rounded_cube(100, 10, center=True)
    groups = [([0, 0], [[0, 0]]), ([90, 0], [[-20, -20], [20, 20]]), ([180, 0], [[-20, -25], [-20, 0], [-20, 25], [20, -25], [20, 0], [20, 25]]), ([270, 0], [[0, 0], [-25, -25], [25, -25], [-25, 25], [25, 25]]), ([0, 90], [[-25, -25], [0, 0], [25, 25]]), ([0, -90], [[-25, -25], [25, -25], [-25, 25], [25, 25]])]
    cuts = []
    for angles, positions in groups:
        cuts.extend([moz.rotate(angles[0], [0, 0, 1], moz.rotate(angles[1], [1, 0, 0], moz.translate([0, -50, 0], moz.translate([x, 0, z], moz.sphere(10))))) for x, z in positions])
    return moz.difference(body, moz.union(*cuts))

if __name__ == "__main__":
    build().show(title="moz - Old/example006")
