"""OpenSCAD examples/Advanced/module_recursion.scad 的 Python 版本。

原文件用递归模块生成随机分叉树。为了每次输出一致，它用 rands() 加固定种子 18
预先取 1000 个随机数；这里同样通过 moz.vector 拿到引擎自己算出的那 1000 个数
（全精度，不是 echo 的 6 位有效数字），所以生成的是同一棵树。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 递归层数
LEVELS = 10
# 第一段长度
LENGTH = 100
# 第一段粗细
THICKNESS = 5

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

RCOUNT = 1000
# 固定种子 18 的随机数表，由引擎求得（改种子即可得到不同的树）
RANDOM = moz.vector(f"rands(0, 1, {RCOUNT}, 18)")


def rnd(s, e, r):
    return RANDOM[r % RCOUNT] * (e - s) + s


def mt(x, y):
    """4x4 平移矩阵。"""
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, 0], [0, 0, 0, 1]]


def mr(a):
    """绕 Z 轴旋转 a 度的 4x4 矩阵。"""
    return [[moz.cos_deg(a), -moz.sin_deg(a), 0, 0],
            [moz.sin_deg(a), moz.cos_deg(a), 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]]


def mul4(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def tree(length, thickness, count, m=None, r=1):
    m = IDENTITY if m is None else m
    parts = [
        moz.color(moz.multmatrix(m, moz.square([thickness, length])),
                  [0, 1 - (0.8 / LEVELS * count), 0]),
    ]
    if count > 0:
        base = mul4(m, mt(0, length))
        parts.append(tree(rnd(0.6, 0.8, r) * length, 0.8 * thickness, count - 1,
                          mul4(base, mr(rnd(20, 35, r + 1))), 8 * r))
        parts.append(tree(rnd(0.6, 0.8, r + 1) * length, 0.8 * thickness, count - 1,
                          mul4(base, mr(-rnd(20, 35, r + 3))), 8 * r + 4))
    return moz.union(*parts)


def build():
    return tree(LENGTH, THICKNESS, LEVELS)


if __name__ == "__main__":
    build().show(title="moz - Advanced/module_recursion")