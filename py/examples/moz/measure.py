"""moz 专有示例：几何测量（Geometry.measure）与导出选项、库搜索路径。

不是上游示例的翻译（上游没有对应的 .scad），不在 verify_examples 比对范围内。

用法::

	PYTHONPATH=py python3 py/examples/moz/measure.py            # 打印测量并预览
	PYTHONPATH=py python3 py/examples/moz/measure.py --no-show  # 只打印（无窗口）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # py/ 进 sys.path
import moz_openscad as moz


def build():
	"""带中心通孔的支架：外框 40×30×12，中心一个 Φ10 通孔。"""
	body = moz.cube([40, 30, 12], center=True)
	hole = moz.cylinder(h=20, r=5, center=True, fn=64)
	return moz.difference(body, hole)


def main(show=True):
	shape = build()
	m = shape.measure

	print("--- Geometry.measure ---")
	print(f"dimension = {m.dimension}   is_empty = {m.is_empty}")
	print(f"bbox      = min {m.bbox[0]}  max {m.bbox[1]}")
	print(f"volume    = {m.volume:.6f}       (期望 40*30*12 - π*5²*12 ≈ {40*30*12 - 3.141592653589793*25*12:.4f})")
	print(f"area      = {m.area:.6f}")
	print(f"facets    = {m.facets}        vertices = {m.vertices}")
	print(f"centroid  = {m.centroid}")

	# 导出选项：只有 PDF 会用到源文档名/路径（OpenSCAD 2021.01 没有别的导出开关）。
	# 下面用 3mf 演示参数可传（对 3mf 无影响），换成 pdf 时才会体现。
	out = Path("/tmp/moz_measure.stl")
	shape.export("binstl", str(out))
	shape.export_bytes("3mf", source_file_name="bracket.scad", source_file_path=str(out))
	print(f"\nexported: {out}")

	# 库搜索路径运行时接口（use <...> / import 的搜索列表）
	print("\n--- library paths ---")
	print("tail before:", moz.library_paths()[-1:])
	moz.add_library_path("/tmp/moz_example_lib")
	print("tail after :", moz.library_paths()[-1:])

	if show:
		shape.show(title="moz - measure")


if __name__ == "__main__":
	main(show="--no-show" not in sys.argv)