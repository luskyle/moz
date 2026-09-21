"""examples/Old/example020.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def screw(type=2, r1=15, r2=20, n=7, h=100, t=8):
    holes = []
    for i in range(n):
        if type == 1:
            holes.append(moz.rotate(i * 360 / n, moz.polygon([
                [2 * r2, 0],
                [r2, 0],
                [r1 * moz.cos_deg(180 / n), r1 * moz.sin_deg(180 / n)],
                [r2 * moz.cos_deg(360 / n), r2 * moz.sin_deg(360 / n)],
                [2 * r2 * moz.cos_deg(360 / n), 2 * r2 * moz.sin_deg(360 / n)],
            ])))
        if type == 2:
            holes.append(moz.rotate(i * 360 / n, moz.polygon([
                [2 * r2, 0],
                [r2, 0],
                [r1 * moz.cos_deg(90 / n), r1 * moz.sin_deg(90 / n)],
                [r1 * moz.cos_deg(180 / n), r1 * moz.sin_deg(180 / n)],
                [r2 * moz.cos_deg(270 / n), r2 * moz.sin_deg(270 / n)],
                [2 * r2 * moz.cos_deg(270 / n), 2 * r2 * moz.sin_deg(270 / n)],
            ])))

    return moz.linear_extrude(
        # for (i = [0:n-1]) { if (type == 1) ...; if (type == 2) ...; } 是一个 group，
        # 作为 difference 的单个子对象参与运算。
        moz.difference(moz.circle(r2), moz.union(*holes)),
        height=h, twist=360 * t / n, convexity=t,
    )


def nut(type=2, r1=16, r2=21, r3=30, s=6, n=7, h=100 / 5, t=8 / 5):
    return moz.difference(
        # cylinder($fn = s, r = r3, h = h)
        moz.cylinder(fn=s, r=r3, h=h),
        moz.translate([0, 0, -h / 2], screw(type, r1, r2, n, h * 2, t * 2)),
    )


def spring(r1=100, r2=10, h=100, hr=12):
    stepsize = 1 / 16

    def segment(i1, i2):
        alpha1 = i1 * 360 * r2 / hr
        alpha2 = i2 * 360 * r2 / hr
        len1 = moz.sin_deg(moz.acos_deg(i1 * 2 - 1)) * r2
        len2 = moz.sin_deg(moz.acos_deg(i2 * 2 - 1)) * r2
        parts = []
        if len1 < 0.01:
            parts.append(moz.polygon([
                [moz.cos_deg(alpha1) * r1, moz.sin_deg(alpha1) * r1],
                [moz.cos_deg(alpha2) * (r1 - len2), moz.sin_deg(alpha2) * (r1 - len2)],
                [moz.cos_deg(alpha2) * (r1 + len2), moz.sin_deg(alpha2) * (r1 + len2)],
            ]))
        if len2 < 0.01:
            parts.append(moz.polygon([
                [moz.cos_deg(alpha1) * (r1 + len1), moz.sin_deg(alpha1) * (r1 + len1)],
                [moz.cos_deg(alpha1) * (r1 - len1), moz.sin_deg(alpha1) * (r1 - len1)],
                [moz.cos_deg(alpha2) * r1, moz.sin_deg(alpha2) * r1],
            ]))
        if len1 >= 0.01 and len2 >= 0.01:
            parts.append(moz.polygon([
                [moz.cos_deg(alpha1) * (r1 + len1), moz.sin_deg(alpha1) * (r1 + len1)],
                [moz.cos_deg(alpha1) * (r1 - len1), moz.sin_deg(alpha1) * (r1 - len1)],
                [moz.cos_deg(alpha2) * (r1 - len2), moz.sin_deg(alpha2) * (r1 - len2)],
                [moz.cos_deg(alpha2) * (r1 + len2), moz.sin_deg(alpha2) * (r1 + len2)],
            ]))
        return moz.union(*parts)

    # for (i = [stepsize : stepsize : 1+stepsize/2])：按 i += stepsize 累加，用 while 复刻。
    segments = []
    i = stepsize
    while i <= 1 + stepsize / 2:
        segments.append(segment(i - stepsize, min(i, 1)))
        i += stepsize

    return moz.linear_extrude(moz.union(*segments), height=100, twist=180 * h / hr,
                              convexity=5, fn=(hr / r2) / stepsize)


def build():
    return moz.union(
        moz.translate([-30, 0, 0], screw()),
        moz.translate([30, 0, 0], nut()),
        spring(),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example020")