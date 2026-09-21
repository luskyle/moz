"""OpenSCAD examples/Functions/echo.scad 的 Python 版本。

原文件用 echo() 演示在表达式里调试递归函数：它**不产生任何几何**，只是在控制台
打印中间值。Python 版用 print() 打印同样的中间值，build() 返回空几何——与原文件
求值出来的结果（空）一致。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def f1(x, y):
    print("f1:", x, y)
    return 0.5 * x * x + 4 * y + 1


def f2(x):
    y = x ** 3
    print("f2:", y)
    return y


def result(x):
    print("f3:", x)
    return x


def f3(x):
    return result(x * x - 5)


def f4(x):
    print("f4:", x)
    y = 1 if x == 1 else x * f4(x - 1)
    print("f4:", y)
    return y


def build():
    r1 = f1(3, 5)
    r2 = f2(4)
    r3 = f3(5)
    r4 = f4(5)
    print("results:", r1, r2, r3, r4)
    # 原文件没有任何几何语句
    return moz.Shape("")


if __name__ == "__main__":
    build().show(title="moz - Functions/echo")