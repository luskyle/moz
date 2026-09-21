"""viewer 逻辑测试（不打开窗口；没有显示器时跳过）。"""

import os

import pytest

np = pytest.importorskip("numpy")
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


def test_view_presets_and_clamp(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(2))
    w._set_preset(-90.0, 0.0)
    assert (w.view.yaw, w.view.pitch) == (-90.0, 0.0)
    w.view.set_view(0.0, 200.0)                # pitch 要被夹住，避免与 up 平行
    assert w.view.pitch == 89.5
    w._reset_view()
    assert (w.view.yaw, w.view.pitch, w.view.distance) == (-60.0, 30.0, 3.0)
    assert list(w.view.target) == [0.0, 0.0, 0.0]


def test_eye_direction_is_z_up(moz, qapp):
    """OpenSCAD 是 Z-up：pitch=0 水平、pitch→90 时相机在 +Z 方向。"""
    import numpy as np
    view = viewer.Interactive3D([viewer._mesh_from_shape(moz.cube(2))])
    view.set_view(0.0, 0.0)
    assert np.allclose(view._eye_direction(), [1.0, 0.0, 0.0], atol=1e-9)
    view.set_view(0.0, 89.5)
    assert view._eye_direction()[2] > 0.999
    matrix_values = view._view().data()      # 16 个 float
    assert len(matrix_values) == 16
    assert all(np.isfinite(value) for value in matrix_values)


def test_color_schemes_enumerated(qapp):
    names = viewer._color_schemes()
    if not names:
        pytest.skip("资源目录里没有 color-schemes")
    assert "Starnight" in names


def test_set_colorscheme_updates_mesh_colors(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_animation(lambda i: moz.Shape(f"translate([0, 0, {i * 2}]) cube(2);"), 3, 3.0)
    before = w.view.meshes[0]["colors"].copy()
    w.set_colorscheme("Starnight")
    assert not np.array_equal(before, w.view.meshes[0]["colors"])
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()


def test_engine_camera_front_view(moz, qapp):
    """前视图（eye 在 -Y、up=+Z）应精确对应上游的 $vpr = [90, 0, 0]。"""
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(10, center=True))
    w.view.set_view(-90.0, 0.0)
    vpr, vpt, vpd, vpf = w.view.engine_camera()
    assert vpr == pytest.approx([90.0, 0.0, 0.0], abs=1e-6)
    assert vpt == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert vpd == pytest.approx(5.0 * 3.0, rel=1e-6)   # radius(5) × distance(3)
    assert vpf == pytest.approx(45.0)


def test_engine_camera_ortho_field_of_view(moz, qapp):
    """正交模式用等效视场角 2·atan(0.55)（与 _projection 的 half=distance*0.55 对齐）。"""
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(10, center=True))
    w.view.orthographic = True
    _, _, _, vpf = w.view.engine_camera()
    assert vpf == pytest.approx(float(np.degrees(2.0 * np.arctan(0.55))), rel=1e-9)


def test_engine_camera_tracks_pan_and_distance(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(10, center=True))
    base = w.view.engine_camera()
    w.view.target = w.view.target + np.array([0.5, 0.0, 0.0])
    w.view.distance *= 2.0
    moved = w.view.engine_camera()
    assert moved[1][0] > base[1][0]                  # vpt 跟着 target 走
    assert moved[2] == pytest.approx(base[2] * 2.0)  # vpd 跟着 distance 走


def test_2d_view_is_interactive(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.eval_text("circle(10);"))
    assert type(w.view).__name__ == "Interactive2D"
    assert w.view.scene() is not None and w.view.scene().items()
    scale_before = w.view.transform().m11()
    w.view.scale(1.5, 1.5)
    assert w.view.transform().m11() > scale_before
    w.view.reset_view()          # 「重置视角」对 2D 也要能用（不崩）


def test_overlay_line_geometry(qapp):
    positions, _ = viewer._line_geometry(True, False)
    assert positions is not None and len(positions) == 12      # 3 轴 × 2 半线 × 2 顶点
    positions, _ = viewer._line_geometry(False, True)
    assert positions is not None and len(positions) == 44      # 11 条 × 2 方向 × 2 顶点
    assert viewer._line_geometry(False, False) == (None, None)


def test_overlay_menu_toggles(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(2))
    assert w.view.line_count == 0                              # 默认不画叠加层
    w.axes_action.setChecked(True)
    assert w.view.show_axes and w.view.line_count == 12
    w.grid_action.setChecked(True)
    assert w.view.show_grid and w.view.line_count == 56


def test_animation_toolbar(moz, qapp):
    w = viewer.ViewerWindow()
    w.set_shape(moz.cube(2))
    assert not w.anim_bar.isVisibleTo(w)                       # 静态几何下不显示
    w.set_animation(lambda i: moz.Shape(f"translate([0, 0, {i}]) cube(1);"), 5, 10.0)
    assert w.anim_bar.isVisibleTo(w)
    assert (w.frame_slider.minimum(), w.frame_slider.maximum()) == (0, 4)
    assert w.fps_spin.value() == pytest.approx(10.0)
    assert w.timer.interval() == 100
    w._goto(3)
    assert (w.index, w.frame_slider.value(), w.frame_label.text()) == (3, 3, "4/5")
    w._toggle_play()
    w._on_slider(1)                                            # 拖帧应暂停播放
    assert w.index == 1 and not w.timer.isActive()
    w._on_fps(20.0)
    assert w.timer.interval() == 50
