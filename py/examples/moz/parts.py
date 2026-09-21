"""moz 专有示例：多部件装配视图（moz.show_parts）+ 点选测量。

不是上游示例的翻译，不在 verify_examples 比对范围内。

用法::

	python3 py/examples/moz/parts.py            # 打开多部件窗口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # py/ 进 sys.path
import moz_openscad as moz


def build_parts():
	"""返回 {部件名: Shape}：一块底板 + 两根立柱 + 一个顶板。"""
	base = moz.cube([60, 40, 4], center=True)
	post = moz.translate([0, 0, 24], moz.cylinder(h=44, r=4, fn=48))
	return {
		"底板": base,
		"立柱": post,
		"顶板": moz.translate([0, 0, 48], moz.cube([40, 30, 4], center=True)),
	}


def main(show=True):
	parts = build_parts()
	for name, shape in parts.items():
		m = shape.measure
		print(f"{name}: 体积 {m.volume:.1f}  包围盒 {m.bbox[0]} → {m.bbox[1]}")
	if show:
		# 右侧列表可勾选显隐；左键单击部件会在状态栏给出世界坐标、距原点距离与部件名
		moz.show_parts(parts, title="moz - parts")


if __name__ == "__main__":
	main(show="--no-show" not in sys.argv)