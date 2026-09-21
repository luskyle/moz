import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def outline(child, wall=1):
	return moz.difference(moz.offset(child, wall / 2), moz.offset(child, -wall / 2))

def build():
	foot = moz.linear_extrude(moz.offset(moz.square(50, center=True), 10), height=20, scale=0.5)
	rim = moz.translate([0, 0, 20], moz.linear_extrude(outline(moz.circle(15), 2), height=20))
	# 原文件在这里设了 $fn = 40；末尾的 %cylinder / %sphere 是背景对象，不参与 F6 导出
	return moz.settings(moz.union(foot, rim), fn=40)

if __name__ == "__main__":
	build().show(title="moz - Advanced/offset")
