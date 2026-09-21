"""moz 专有示例：动画。

- 默认在**预览窗口里播放**动画（`moz.show_animation`）。
- `--export` 时另外用 `moz.eval_animation` 逐帧导出 STL（批处理用法）。

对应上游 `--animate N` 的两种用法；不是上游示例的翻译，不在 verify_examples 比对范围内。

用法::

	python3 py/examples/moz/animation.py                 # 窗口里播放
	python3 py/examples/moz/animation.py --export        # 播放 + 导出帧
	python3 py/examples/moz/animation.py --no-show --export   # 只导出（无窗口）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # py/ 进 sys.path
import moz_openscad as moz

OUT = Path("/tmp/moz_animation")
FRAMES = 24
FPS = 12.0

# $t ∈ [0, 1)：绕 Z 轴的十字，顶部一个随 $t 上下摆动的球。
# SCAD 的 sin 以**度**为单位，所以写 sin(360 * $t)。
#
# 注意：$t 必须直接出现在几何表达式里，不能放进顶层赋值——逐帧注入的 `$t=...` 是作为
# -D 追加在源码**之后**的，顶层赋值 `tz = 6 * sin(360 * $t)` 求值时还看不到它
# （会一直用默认的 $t=0，所有帧完全相同）。见 docs/scad-semantics.md §9。
SOURCE = """
union() {
	cube([8, 2, 2], center = true);
	cube([2, 8, 2], center = true);
	translate([0, 0, 6 * sin(360 * $t)]) sphere(r = 2, $fn = 32);
}
"""


def build(t=0.0):
	"""取动画的某一帧（t ∈ [0, 1)），返回 Shape（可直接 .show()/.measure）。"""
	return moz.Shape(SOURCE, **{"$t": t})


def export_frames(out_dir=None, frames=FRAMES):
	"""用 moz.eval_animation 逐帧导出 STL（批处理演示，无窗口）。

	eval_animation 逐帧设 $t = frame / fps，所以这里把 fps 取成 frames 才能得到 t ∈ [0, 1)。
	"""
	out = Path(out_dir) if out_dir else OUT
	out.mkdir(parents=True, exist_ok=True)

	def render_frame(frame, geometry):
		m = geometry.measure
		path = out / f"frame{frame:03d}.stl"
		geometry.export("binstl", str(path))
		print(f"frame {frame}: bbox_z = [{m.bbox_min[2]:.3f}, {m.bbox_max[2]:.3f}]"
		      f"  t = {frame / frames:.3f}  -> {path.name}")

	done = moz.eval_animation(SOURCE, frames, frames, callback=render_frame)
	print(f"\nexported {done}/{frames} frames to {out}")


def main(show=True, export=False, frames=FRAMES, fps=FPS):
	if export:
		export_frames(frames=frames)
	if show:
		# 在窗口里播放：frame_fn(i) 取第 i 帧，t = i / frames
		moz.show_animation(lambda i: build(i / frames), frames=frames, fps=fps,
		                   title="moz - animation")


if __name__ == "__main__":
	main(show="--no-show" not in sys.argv, export="--export" in sys.argv)