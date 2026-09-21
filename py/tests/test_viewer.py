"""viewer 逻辑测试（不打开窗口；没有显示器时跳过）。"""

import os

import pytest

viewer = pytest.importorskip("moz_viewer")


@pytest.fixture(scope="module")
def qapp():
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("没有显示器，跳过 Qt 视图测试")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_static_shape_uses_3d_view(moz, qapp):
    w = viewer.ViewerWindow(title="t")
    w.set_shape(moz.cube(2))
    assert type(w.view).__name__ == "Interactive3D"
    assert len(w.view.meshes) == 1
    assert not w.anim_menu.isEnabled()


def test_empty_shape_shows_label(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.eval_text('echo(1);'))
    assert w.status_hint == "空几何"
    assert not w.anim_menu.isEnabled()


def test_animation_precomputes_frames(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape(f"translate([{i * 2}, 0, 0]) cube(1);"), 5, 5.0)
    assert w.frames == 5
    assert len(w.view.meshes) == 5
    assert w.anim_menu.isEnabled()


def test_animation_shares_bounds_across_frames(moz, qapp):
    """各帧共用同一套 center/radius，否则模型会逐帧被重新居中（抖动）。"""
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape(f"translate([{i * 2}, 0, 0]) cube(1);"), 5, 5.0)
    # 立方体位于 x = 0,2,4,6,8，各占 1 宽 → 并集 x∈[0,9]，半径 4.5
    assert float(w.view.radius) == pytest.approx(4.5)
    assert float(w.view.center[0]) == pytest.approx(4.5)


def test_playback_state_machine(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape("cube(1);"), 5, 5.0)
    w._goto(3)
    assert w.index == 3
    w._toggle_play()
    assert w.timer.isActive()
    w._advance()                       # 3 → 4
    w._advance()                       # 4 → 0（循环回绕）
    assert w.index == 0
    w._toggle_play()
    assert not w.timer.isActive()
    w._step(1)
    assert w.index == 1


def test_loop_disabled_stops_at_last_frame(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape("cube(1);"), 3, 5.0)
    w.loop_action.setChecked(False)
    w._goto(2)
    w._toggle_play()
    w._advance()                       # 到末帧后应停
    assert w.index == 2
    assert not w.timer.isActive()


def test_non_3d_animation_falls_back_to_static(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape("circle(2);"), 3, 5.0)
    assert w.frames == 0                       # 未进入动画模式
    assert type(w.view).__name__ == "Interactive2D"
    assert not w.anim_menu.isEnabled()