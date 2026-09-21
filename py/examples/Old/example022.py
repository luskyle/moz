"""examples/Old/example022.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def rounded_box(size, radius, sidesonly):
    """module roundedBox(size, radius, sidesonly)：size 是 [w, h, d]。"""
    rot = [[0, 0, 0], [90, 0, 90], [90, 90, 0]]

    if sidesonly:
        # for (x = [...], y = [...]) 是一个 group，在模块体里是 union 的单个子对象。
        return moz.union(
            moz.cube([size[0] - 2 * radius, size[1], size[2]], True),
            moz.cube([size[0], size[1] - 2 * radius, size[2]], True),
            moz.union(*[
                moz.translate([x, y, 0], moz.cylinder(r=radius, h=size[2], center=True))
                for x in (radius - size[0] / 2, -radius + size[0] / 2)
                for y in (radius - size[1] / 2, -radius + size[1] / 2)
            ]),
        )

    parts = [
        moz.cube([size[0], size[1] - radius * 2, size[2] - radius * 2], center=True),
        moz.cube([size[0] - radius * 2, size[1], size[2] - radius * 2], center=True),
        moz.cube([size[0] - radius * 2, size[1] - radius * 2, size[2]], center=True),
    ]

    # for (axis = [0:2]) { for (x = [...], y = [...]) ... }
    axis_parts = []
    for axis in range(3):
        axis_parts.append(moz.union(*[
            moz.rotate(rot[axis],
                moz.translate([x, y, 0],
                    moz.cylinder(h=size[(axis + 2) % 3] - 2 * radius, r=radius, center=True)))
            for x in (radius - size[axis] / 2, -radius + size[axis] / 2)
            for y in (radius - size[(axis + 1) % 3] / 2, -radius + size[(axis + 1) % 3] / 2)
        ]))
    parts.append(moz.union(*axis_parts))

    # for (x = [...], y = [...], z = [...]) translate([x,y,z]) sphere(radius);
    parts.append(moz.union(*[
        moz.translate([x, y, z], moz.sphere(radius))
        for x in (radius - size[0] / 2, -radius + size[0] / 2)
        for y in (radius - size[1] / 2, -radius + size[1] / 2)
        for z in (radius - size[2] / 2, -radius + size[2] / 2)
    ]))

    return moz.union(*parts)


def build():
    return moz.union(
        moz.translate([-15, 0, 0], rounded_box([20, 30, 40], 5, True)),
        moz.translate([15, 0, 0], rounded_box([20, 30, 40], 5, False)),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example022")