"""动画帧（moz.eval_animation）测试。"""

import pytest


def test_frames_get_increasing_t(moz):
    seen = []
    done = moz.eval_animation(
        "translate([$t * 10, 0, 0]) cube(1);", 3, 1.0,
        callback=lambda i, g: seen.append((i, g.measure.bbox_min[0])),
    )
    assert done == 3
    assert [i for i, _ in seen] == [0, 1, 2]
    assert [round(x, 6) for _, x in seen] == [0.0, 10.0, 20.0]


def test_fps_scales_t(moz):
    xs = []
    moz.eval_animation("translate([$t * 10, 0, 0]) cube(1);", 3, 2.0,
                       callback=lambda i, g: xs.append(round(g.measure.bbox_min[0], 6)))
    assert xs == [0.0, 5.0, 10.0]


def test_callback_abort_returns_completed(moz):
    seen = []
    done = moz.eval_animation("cube(1);", 5, callback=lambda i, g: (seen.append(i), 1)[1])
    assert done == 1 and seen == [0]


def test_callback_exception_propagates(moz):
    def cb(i, g):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        moz.eval_animation("cube(1);", 3, callback=cb)


def test_borrowed_geometry_invalid_after_callback(moz):
    holder = {}
    moz.eval_animation("cube(1);", 1, callback=lambda i, g: holder.setdefault("g", g))
    with pytest.raises(moz.OpenSCADError):
        holder["g"].measure


def test_invalid_arguments(moz):
    with pytest.raises(ValueError):
        moz.eval_animation("cube(1);", 0, callback=lambda i, g: None)
    with pytest.raises(ValueError):
        moz.eval_animation("cube(1);", 3, callback=None)


def test_dollar_t_in_toplevel_assignment_is_not_seen(moz):
    """$t 必须在几何表达式里直接用；放进顶层赋值看不到 -D 覆盖（scad-semantics §9）。"""
    source = "tz = 6 * $t;\ntranslate([0, 0, tz]) cube(1);"
    tops = []
    moz.eval_animation(source, 3, 1.0, callback=lambda i, g: tops.append(round(g.measure.bbox_max[2], 6)))
    assert len(set(tops)) == 1


def test_animation_from_file(moz, tmp_path):
    src = tmp_path / "anim.scad"
    src.write_text("translate([$t * 4, 0, 0]) cube(1);\n")
    xs = []
    moz.eval_animation("", 4, 4.0, path=str(src),
                       callback=lambda i, g: xs.append(round(g.measure.bbox_min[0], 6)))
    assert xs == [0.0, 1.0, 2.0, 3.0]