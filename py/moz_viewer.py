#!/usr/bin/env python3
"""Interactive Qt/OpenGL viewer for moz_openscad shapes (with animation playback)."""

import argparse
import importlib.util
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QAction, QKeySequence, QMatrix4x4, QOpenGLFunctions, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QStatusBar,
)

# 未着色对象在预览器里的默认材质色（与 OpenSCAD 默认配色同色系）
_DEFAULT_COLOR = np.asarray([0.20, 0.62, 0.90], dtype=np.float32)


def _stl_vertices(data, face_colors=None):
    """binstl → (顶点, 面法线, 逐顶点颜色)，**不做**居中/归一化。

    face_colors 是 moz_geom_face_colors 的输出（4 字节/面，顺序与 STL 三角面一一对应）；
    同一三角面的三个顶点取同一个颜色。没有颜色信息时颜色返回 None。
    居中/缩放交给调用方（动画各帧必须用**同一套** center/radius，否则会逐帧抖动）。
    """
    if len(data) < 84:
        raise ValueError("invalid STL data")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) < 84 + count * 50:
        raise ValueError("truncated STL data")
    vertices = []
    normals = []
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12f", data, offset)
        normal = values[0:3]
        vertices.extend((values[3:6], values[6:9], values[9:12]))
        normals.extend((normal, normal, normal))
        offset += 50
    points = np.asarray(vertices, dtype=np.float32).reshape(-1, 3)
    face_normals = np.asarray(normals, dtype=np.float32).reshape(-1, 3)
    if len(face_normals):
        face_normals /= np.maximum(np.linalg.norm(face_normals, axis=1, keepdims=True), 1e-8)

    colors = None
    if face_colors is not None and len(face_colors) == count * 4:
        per_vertex = []
        for index in range(count):
            rgb = [face_colors[index * 4 + channel] / 255.0 for channel in range(3)]
            per_vertex.extend((rgb, rgb, rgb))
        colors = np.asarray(per_vertex, dtype=np.float32).reshape(-1, 3)
    return points, face_normals, colors


def _face_colors(shape):
    """取逐面颜色；旧版库或非 3D 几何拿不到时返回 None（预览器退回默认色）。"""
    try:
        return shape.face_colors()
    except Exception:
        return None


def _mesh_from_shape(shape):
    """Shape → {points, normals, colors}（世界坐标，未居中）。缺颜色时填默认材质色。"""
    points, normals, colors = _stl_vertices(shape.export_bytes("binstl"), _face_colors(shape))
    if colors is None:
        colors = np.tile(_DEFAULT_COLOR, (len(points), 1))
    return {"points": points, "normals": normals, "colors": colors}


class Interactive3D(QOpenGLWidget):
    """3D 视图：可显示一帧或一串动画帧（帧间共用同一 center/radius，避免抖动）。"""

    def __init__(self, meshes, parent=None):
        super().__init__(parent)
        if not meshes:
            raise ValueError("Interactive3D needs at least one mesh")
        self.meshes = meshes
        self.index = 0
        self.center, self.radius = self._bounds(meshes)
        self.program = None
        self.gl = None
        self.vertex_buffer = None
        self.vao = None
        self.last_pos = QPoint()
        self.orthographic = False
        self.reset_view()
        self.setMinimumSize(640, 480)

    @staticmethod
    def _bounds(meshes):
        """所有帧的并集包围盒 → (center, radius)，供各帧统一居中/缩放。"""
        stacks = [m["points"] for m in meshes if len(m["points"])]
        if not stacks:
            return np.zeros(3, dtype=np.float32), 1.0
        minimum = np.min([p.min(axis=0) for p in stacks], axis=0)
        maximum = np.max([p.max(axis=0) for p in stacks], axis=0)
        center = (minimum + maximum) / 2
        radius = max(float(np.max(maximum - minimum)) / 2, 1e-3)
        return center, radius

    def reset_view(self):
        self.yaw, self.pitch, self.distance = -35.0, 25.0, 3.0
        self.pan_x = self.pan_y = 0.0
        self.update()

    def _normalized(self, mesh):
        return (mesh["points"] - self.center) / self.radius

    def _upload(self):
        """把当前帧的顶点数据写进 vertex_buffer（**要求调用方已 bind**）。

        不能在内部 bind/release：`setAttributeBuffer` 依赖调用时仍绑定的 GL_ARRAY_BUFFER，
        提前 release 会让顶点属性指向 buffer 0。
        """
        mesh = self.meshes[self.index]
        interleaved = np.hstack((self._normalized(mesh), mesh["normals"], mesh["colors"])).astype(np.float32)
        self.vertex_buffer.allocate(interleaved.tobytes(), interleaved.nbytes)

    def set_frame(self, index):
        """切到第 index 帧（自动取模）并重传顶点缓冲。"""
        if len(self.meshes) == 1:
            return
        self.index = index % len(self.meshes)
        if self.vertex_buffer is not None:
            self.vertex_buffer.bind()
            self._upload()
            self.vertex_buffer.release()
        self.update()

    def initializeGL(self):
        self.gl = QOpenGLFunctions(self.context())
        self.gl.initializeOpenGLFunctions()
        self.gl.glClearColor(0.08, 0.09, 0.11, 1.0)
        self.gl.glEnable(0x0B71)   # GL_DEPTH_TEST
        self.gl.glEnable(0x0B44)   # GL_CULL_FACE
        self.program = QOpenGLShaderProgram(self)
        vertex_shader = """
            attribute vec3 position;
            attribute vec3 normal;
            attribute vec3 color;
            uniform mat4 mvp;
            uniform mat4 modelView;
            varying vec3 viewNormal;
            varying vec3 viewPosition;
            varying vec3 vertexColor;
            void main() {
                vec4 positionInView = modelView * vec4(position, 1.0);
                viewPosition = positionInView.xyz;
                viewNormal = normalize((modelView * vec4(normal, 0.0)).xyz);
                vertexColor = color;
                gl_Position = mvp * vec4(position, 1.0);
            }
        """
        fragment_shader = """
            varying vec3 viewNormal;
            varying vec3 viewPosition;
            varying vec3 vertexColor;
            void main() {
                vec3 surfaceNormal = normalize(viewNormal);
                vec3 lightDirection = normalize(vec3(-0.45, 0.75, 1.0));
                vec3 viewDirection = normalize(-viewPosition);
                float diffuse = max(dot(surfaceNormal, lightDirection), 0.0);
                float rim = pow(1.0 - max(dot(surfaceNormal, viewDirection), 0.0), 2.0);
                float specular = pow(max(dot(reflect(-lightDirection, surfaceNormal), viewDirection), 0.0), 32.0);
                vec3 baseColor = vertexColor;
                vec3 color = baseColor * (0.20 + 0.72 * diffuse + 0.16 * rim) + vec3(0.55) * specular;
                gl_FragColor = vec4(color, 1.0);
            }
        """
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vertex_shader):
            raise RuntimeError(self.program.log())
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, fragment_shader):
            raise RuntimeError(self.program.log())
        if not self.program.link():
            raise RuntimeError(self.program.log())
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()
        self.vao.bind()
        self.vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vertex_buffer.create()
        self.vertex_buffer.bind()
        self._upload()
        self.program.bind()
        self.program.enableAttributeArray("position")
        self.program.enableAttributeArray("normal")
        self.program.enableAttributeArray("color")
        # 顶点步长 36 字节：position(0) / normal(12) / color(24)，每项 3 个 float
        self.program.setAttributeBuffer("position", 0x1406, 0, 3, 36)
        self.program.setAttributeBuffer("normal", 0x1406, 12, 3, 36)
        self.program.setAttributeBuffer("color", 0x1406, 24, 3, 36)
        self.vertex_buffer.release()
        self.vao.release()
        self.program.release()

    def resizeGL(self, width, height):
        self.gl.glViewport(0, 0, width, max(height, 1))

    def paintGL(self):
        self.gl.glClear(0x00004100)  # GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT
        if not self.program:
            return
        projection = self._projection(self.width() / max(self.height(), 1))
        self.program.bind()
        view = self._view()
        self.program.setUniformValue("mvp", projection * view)
        self.program.setUniformValue("modelView", view)
        self.vao.bind()
        self.gl.glDrawArrays(0x0004, 0, len(self.meshes[self.index]["points"]))
        self.vao.release()
        self.program.release()

    def _projection(self, aspect):
        matrix = QMatrix4x4()
        if self.orthographic:
            half = self.distance * 0.55
            matrix.ortho(-half * aspect, half * aspect, -half, half, 0.01, 200.0)
        else:
            matrix.perspective(45.0, aspect, 0.01, 200.0)
        return matrix

    def _view(self):
        yaw, pitch = np.radians([self.yaw, self.pitch])
        eye = QVector3D(
            float(self.distance * np.cos(pitch) * np.cos(yaw) + self.pan_x),
            float(self.distance * np.sin(pitch) + self.pan_y),
            float(self.distance * np.cos(pitch) * np.sin(yaw)),
        )
        matrix = QMatrix4x4()
        matrix.lookAt(eye, QVector3D(self.pan_x, self.pan_y, 0), QVector3D(0, 1, 0))
        return matrix

    def mousePressEvent(self, event):
        self.last_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        current = event.position().toPoint()
        delta = current - self.last_pos
        self.last_pos = current
        if event.buttons() & Qt.LeftButton:
            self.yaw += delta.x() * 0.6
            self.pitch = max(-89.0, min(89.0, self.pitch + delta.y() * 0.6))
        elif event.buttons() & Qt.RightButton:
            self.pan_x += delta.x() * 0.005 * self.distance
            self.pan_y -= delta.y() * 0.005 * self.distance
        self.update()

    def wheelEvent(self, event):
        self.distance *= 0.9 if event.angleDelta().y() > 0 else 1.1
        self.distance = max(0.2, min(50.0, self.distance))
        self.update()


class Interactive2D(QSvgWidget):
    def __init__(self, shape, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.load(shape.export_bytes("svg"))


class ViewerWindow(QMainWindow):
    """预览窗口：中央视图 + 菜单栏（文件 / 视图 / 动画 / 帮助）+ 状态栏。"""

    def __init__(self, title="moz OpenSCAD", width=900, height=650):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(width, height)
        self.setStatusBar(QStatusBar())
        self.view = None
        self.shape = None       # 静态几何（Shape / Geometry），供文件菜单导出
        self.frame_fn = None    # 动画帧提供者 frame_fn(i) -> Shape
        self.frames = 0
        self.fps = 8.0
        self.index = 0
        self.status_hint = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self._build_menus()

    # ------------------------------------------------------------------ 载入
    def set_shape(self, shape):
        """显示单个静态几何。"""
        self.shape = shape
        self.frame_fn = None
        if shape.is_empty:
            # 上游语义下空几何的 dimension 仍是 3（空 Nef），所以要先判空
            self.view = QLabel("空几何")
            self.status_hint = "空几何"
        elif shape.dimension == 3:
            self.view = Interactive3D([_mesh_from_shape(shape)], self)
            self.status_hint = "左键旋转 | 右键平移 | 滚轮缩放 | 颜色来自 color()"
        elif shape.dimension == 2:
            self.view = Interactive2D(shape, self)
            self.status_hint = "SVG 矢量视图"
        else:
            self.view = QLabel("空几何")
            self.status_hint = "空几何"
        self.setCentralWidget(self.view)
        self.anim_menu.setEnabled(False)
        self._refresh_status()

    def set_animation(self, frame_fn, frames, fps=8.0):
        """预计算 frames 帧并用定时器播放。

        frame_fn(i) 返回第 i 帧的 Shape（``i`` 从 0 起）。各帧共用同一套居中/缩放，
        所以模型会“动”而不是逐帧被重新居中——预计算时在状态栏显示进度。
        """
        if frames <= 0:
            raise ValueError("frames must be > 0")
        self.frame_fn = frame_fn
        self.shape = None
        meshes = []
        first = None
        for i in range(frames):
            self.statusBar().showMessage(f"预计算帧 {i + 1}/{frames} …")
            QApplication.processEvents()
            shape = frame_fn(i)
            if first is None:
                first = shape
                if shape.is_empty or shape.dimension != 3:
                    self.set_shape(shape)  # 非 3D 没法在 GL 里动画，退回静态
                    return
            meshes.append(_mesh_from_shape(shape))
        if not meshes:
            self.set_shape(first)
            return

        self.frames = len(meshes)
        self.fps = float(fps) if fps > 0 else 8.0
        self.view = Interactive3D(meshes, self)
        self.setCentralWidget(self.view)
        self.anim_menu.setEnabled(True)
        self.index = 0
        self.timer.setInterval(max(1, int(1000.0 / self.fps)))
        self._refresh_status()

    # ------------------------------------------------------------------ 菜单
    def _build_menus(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("文件(&F)")
        self._add_action(file_menu, "导出当前帧 STL…", self._export_stl, QKeySequence("Ctrl+S"))
        self._add_action(file_menu, "导出当前帧 PNG（引擎渲染）…", self._export_png, QKeySequence("Ctrl+E"))
        self._add_action(file_menu, "保存视图截图…", self._save_screenshot, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        self._add_action(file_menu, "退出", self.close, QKeySequence("Ctrl+Q"))

        view_menu = bar.addMenu("视图(&V)")
        self._add_action(view_menu, "重置视角", self._reset_view, QKeySequence("Home"))
        self.ortho_action = QAction("正交投影", self, checkable=True)
        self.ortho_action.toggled.connect(self._toggle_ortho)
        view_menu.addAction(self.ortho_action)

        self.anim_menu = bar.addMenu("动画(&A)")
        self.play_action = QAction("播放 / 暂停", self)
        self.play_action.setShortcut(QKeySequence("Space"))
        self.play_action.triggered.connect(self._toggle_play)
        self.anim_menu.addAction(self.play_action)
        self._add_action(self.anim_menu, "上一帧", lambda: self._step(-1), QKeySequence("Left"))
        self._add_action(self.anim_menu, "下一帧", lambda: self._step(1), QKeySequence("Right"))
        self._add_action(self.anim_menu, "回到首帧", lambda: self._goto(0), QKeySequence("Ctrl+Home"))
        self.loop_action = QAction("循环播放", self, checkable=True)
        self.loop_action.setChecked(True)
        self.anim_menu.addAction(self.loop_action)
        self.anim_menu.setEnabled(False)

        help_menu = bar.addMenu("帮助(&H)")
        self._add_action(help_menu, "关于 moz viewer", self._about)

    def _add_action(self, menu, text, slot, shortcut=None):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------ 动画
    def _refresh_status(self):
        if self.frames:
            state = "播放中" if self.timer.isActive() else "暂停"
            self.statusBar().showMessage(
                f"{state} | 帧 {self.index + 1}/{self.frames} | {self.fps:g} fps | "
                f"左键旋转 | 右键平移 | 滚轮缩放 | Space 播放/暂停")
        else:
            self.statusBar().showMessage(self.status_hint)

    def _goto(self, index):
        if not self.frames:
            return
        self.index = index % self.frames
        self.view.set_frame(self.index)
        self._refresh_status()

    def _step(self, delta):
        if not self.frames:
            return
        if self.timer.isActive():
            self._toggle_play()  # 手动步进时先暂停
        self._goto(self.index + delta)

    def _advance(self):
        if not self.frames:
            return
        nxt = self.index + 1
        if nxt >= self.frames and not self.loop_action.isChecked():
            self.timer.stop()
            self._refresh_status()
            return
        self._goto(nxt)

    def _toggle_play(self):
        if not self.frames:
            return
        if self.timer.isActive():
            self.timer.stop()
        else:
            self.timer.start()
        self._refresh_status()

    # ------------------------------------------------------------------ 视图
    def _reset_view(self):
        if isinstance(self.view, Interactive3D):
            self.view.reset_view()

    def _toggle_ortho(self, checked):
        if isinstance(self.view, Interactive3D):
            self.view.orthographic = checked
            self.view.update()

    # ------------------------------------------------------------------ 文件
    def _current_source(self):
        """当前要导出的几何：动画取当前帧（重新求值一次），静态取原始几何。"""
        if self.frame_fn is not None:
            return self.frame_fn(self.index)
        return self.shape

    def _export_stl(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出当前帧 STL", "frame.stl", "STL (*.stl)")
        if not path:
            return
        try:
            self._current_source().export("binstl", path)
        except Exception as exc:  # 导出失败不该让窗口崩
            QMessageBox.warning(self, "导出失败", str(exc))

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出当前帧 PNG", "frame.png", "PNG (*.png)")
        if not path:
            return
        try:
            source = self._current_source()
            width = self.view.width() if self.view is not None and hasattr(self.view, "width") else 0
            height = self.view.height() if self.view is not None and hasattr(self.view, "height") else 0
            source.render_png(path, width, height)  # 引擎渲染，保留 color()
        except Exception as exc:
            QMessageBox.warning(self, "渲染失败", str(exc))

    def _save_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存视图截图", "view.png", "PNG (*.png)")
        if not path or self.view is None:
            return
        image = self.view.grabFramebuffer() if hasattr(self.view, "grabFramebuffer") else None
        if image is None or not image.save(path):
            QMessageBox.warning(self, "保存失败", "这个视图不支持截图。")

    def _about(self):
        from PySide6 import __version__ as pyside_version
        QMessageBox.about(
            self, "关于 moz viewer",
            f"<b>moz viewer</b><br>OpenSCAD 2021.01 无 GUI 内核的交互预览器。<br><br>"
            f"PySide6 {pyside_version} / Python {sys.version.split()[0]}<br><br>"
            f"左键旋转 · 右键平移 · 滚轮缩放 · Space 播放/暂停 · ←/→ 逐帧",
        )


def show_shape(shape, title="moz OpenSCAD", width=900, height=650):
    """打开窗口显示单个静态几何（保持旧签名：Shape.show() 会调它）。"""
    app = QApplication.instance() or QApplication(sys.argv)
    window = ViewerWindow(title=title, width=width, height=height)
    window.set_shape(shape)
    window.show()
    app.exec()


def show_animation(frame_fn, frames, fps=8.0, title="moz animation", width=900, height=650):
    """打开窗口播放动画。

    frame_fn(i) 返回第 i 帧的 Shape（i 从 0 起，共 frames 帧），fps 为播放帧率。
    帧在打开窗口时**一次性预计算**（状态栏显示进度），之后播放不再重新求值。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    window = ViewerWindow(title=title, width=width, height=height)
    window.set_animation(frame_fn, frames, fps)
    window.show()
    app.exec()


def main():
    parser = argparse.ArgumentParser(description="Preview a Python-built moz OpenSCAD shape")
    parser.add_argument("module", help="Python file exposing build()")
    parser.add_argument("--frames", type=int, default=0,
                        help="frames to animate (0 = static; module.build(t) is called with t=i/frames)")
    parser.add_argument("--fps", type=float, default=8.0)
    args = parser.parse_args()
    path = Path(args.module).resolve()
    spec = importlib.util.spec_from_file_location("moz_viewer_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if args.frames > 0:
        frames = args.frames
        show_animation(lambda i: module.build(t=i / frames), frames, args.fps, title=f"moz - {path.stem}")
    else:
        show_shape(module.build(), title=f"moz - {path.stem}")


if __name__ == "__main__":
    main()