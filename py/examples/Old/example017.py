"""examples/Old/example017.scad 的忠实 Python 移植（mode = "assembled"）。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


mode = "assembled"  # ["parts", "exploded", "assembled"]

thickness = 6
locklen1 = 15
locklen2 = 10
boltlen = 15
midhole = 10
inner1_to_inner2 = 50
total_height = 80


def shape_tripod():
    x1 = 0
    x2 = x1 + thickness
    x3 = x2 + locklen1
    x4 = x3 + thickness
    x5 = x4 + inner1_to_inner2
    x6 = x5 - thickness
    x7 = x6 - locklen2
    x8 = x7 - thickness
    x9 = x8 - thickness
    x10 = x9 - thickness

    y1 = 0
    y2 = y1 + thickness
    y3 = y2 + thickness
    y4 = y3 + thickness
    y5 = y3 + total_height - 3 * thickness
    y6 = y5 + thickness

    return moz.union(
        moz.difference(
            moz.polygon([
                [x1, y2], [x2, y2],
                [x2, y1], [x3, y1], [x3, y2],
                [x4, y2], [x4, y1], [x5, y1],
                [x5 + thickness, y3], [x5, y4],
                [x5, y5],
                [x6, y5], [x6, y6], [x7, y6], [x7, y5], [x8, y5],
                [x8, y6], [x9, y5],
                [x9, y4], [x10, y3],
                [x2, y3],
            ]),
            moz.translate([x10, y4], moz.circle(thickness)),
            moz.translate([x5 + thickness, y4], moz.circle(thickness)),
        ),
        moz.translate([x5, y1], moz.square([boltlen - thickness, thickness * 2])),
        moz.translate([x5 + boltlen - thickness, y2], moz.circle(thickness)),
        moz.translate([x2, y2], moz.intersection(
            moz.circle(thickness),
            moz.translate([-thickness * 2, 0], moz.square(thickness * 2)),
        )),
        moz.translate([x8, y5], moz.intersection(
            moz.circle(thickness),
            moz.translate([-thickness * 2, 0], moz.square(thickness * 2)),
        )),
    )


def shape_inner_disc():
    # for 循环在原文件里是一个 group，作为 difference 的单个子对象参与运算。
    return moz.difference(
        moz.circle(midhole + boltlen + 2 * thickness + locklen2),
        moz.union(*[moz.rotate(alpha,
            moz.translate([0, midhole + boltlen + thickness + locklen2 / 2],
                           moz.square([thickness, locklen2], True)))
            for alpha in (0, 120, 240)]),
        moz.circle(midhole + boltlen),
    )


def shape_outer_disc():
    # for 循环在原文件里是一个 group，作为 difference 的单个子对象参与运算。
    return moz.difference(
        moz.circle(midhole + boltlen + inner1_to_inner2 + 2 * thickness + locklen1),
        moz.union(*[moz.rotate(alpha,
            moz.translate([0, midhole + boltlen + inner1_to_inner2 + thickness + locklen1 / 2],
                           moz.square([thickness, locklen1], True)))
            for alpha in (0, 120, 240)]),
        moz.circle(midhole + boltlen + inner1_to_inner2),
    )


def parts():
    tripod_x_off = locklen1 - locklen2 + inner1_to_inner2
    tripod_y_off = max(midhole + boltlen + inner1_to_inner2 + 4 * thickness + locklen1, total_height)

    return moz.union(
        shape_inner_disc(),
        shape_outer_disc(),
        # for 循环在原文件里是一个 group，在模块体里是 union 的单个子对象。
        moz.union(*[moz.scale(s, moz.translate([tripod_x_off, -tripod_y_off], shape_tripod()))
                    for s in ([1, 1], [-1, 1], [1, -1])]),
    )


def exploded():
    return moz.union(
        moz.translate([0, 0, total_height + 2 * thickness],
            moz.linear_extrude(shape_inner_disc(), height=thickness, convexity=4)),
        moz.linear_extrude(shape_outer_disc(), height=thickness, convexity=4),
        moz.color(
            moz.union(*[moz.rotate(alpha,
                moz.translate([0, thickness * 2 + locklen1 + inner1_to_inner2 + boltlen + midhole, 1.5 * thickness],
                    moz.rotate([90, 0, -90],
                        moz.linear_extrude(shape_tripod(), height=thickness, convexity=10, center=True))))
                for alpha in (0, 120, 240)]),
            [0.7, 0.7, 1]),
    )


def bottle():
    r = boltlen + midhole
    h = total_height - thickness * 2

    return moz.rotate_extrude(moz.union(
        moz.square([r, h]),
        moz.translate([0, h], moz.intersection(
            moz.square([r, r]),
            moz.scale([1, 0.7], moz.circle(r)),
        )),
        moz.translate([0, h + r], moz.intersection(
            moz.translate([0, -r / 2], moz.square([r / 2, r])),
            moz.circle(r / 2),
        )),
    ), angle=360)


def assembled():
    return moz.union(
        moz.translate([0, 0, total_height - thickness],
            moz.linear_extrude(shape_inner_disc(), height=thickness, convexity=4)),
        moz.linear_extrude(shape_outer_disc(), height=thickness, convexity=4),
        moz.color(
            moz.union(*[moz.rotate(alpha,
                moz.translate([0, thickness * 2 + locklen1 + inner1_to_inner2 + boltlen + midhole, 0],
                    moz.rotate([90, 0, -90],
                        moz.linear_extrude(shape_tripod(), height=thickness, convexity=10, center=True))))
                for alpha in (0, 120, 240)]),
            [0.7, 0.7, 1]),
        # 原文件里还有一个 % translate([0, 0, thickness*2]) bottle(); 它是 % 背景对象，
        # 不参与 F6 导出，因此不放进 build() 的返回值。
    )


def build():
    if mode == "parts":
        return parts()
    if mode == "exploded":
        return exploded()
    return assembled()


if __name__ == "__main__":
    build().show(title="moz - Old/example017")