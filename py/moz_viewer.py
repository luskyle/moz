#!/usr/bin/env python3
"""Interactive Qt/OpenGL viewer for moz_openscad shapes (with animation playback)."""

import argparse
import importlib.util
import json
import os
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


def _color_schemes():
    """资源目录里可用的渲染配色方案名（`color-schemes/render/*.json` 的 name 字段）。"""
    root = os.environ.get("MOZ_OPENSCAD_RESOURCE_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "3rd", "openscad")
    directory = os.path.join(root, "color-schemes", "render")
    names = []
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return names
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, entry), encoding="utf-8") as handle:
                names.append(json.load(handle).get("name") or entry[:-5])
        except (OSError, ValueError):
            names.append(entry[:-5])
    return names


def _face_colors(shape, colorscheme=None):
    """取逐面颜色；旧版库、非 3D 几何拿不到时返回 None（预览器退回默认色）。"""
    try:
        return shape.face_colors(colorscheme)
    except Exception:
        return None


def _mesh_from_shape(shape, colorscheme=None):
    """Shape → {points, normals, colors}（世界坐标，未居中）。

    用 ``Geometry.triangles()`` 直取三角面（不再解析 STL 字节），法线由叉积算出。
    ``Shape`` 有惰性求值缓存，所以 ``triangles()`` 与 ``face_colors()`` 只求值一次。
    """
    triangles = shape.triangles()
    if not len(triangles):
        empty = np.zeros((0, 3), dtype=np.float32)
        return {"points": empty, "normals": empty, "colors": empty}

    points = np.frombuffer(triangles, dtype=np.float32).reshape(-1, 3)
    tri = points.reshape(-1, 3, 3)
    face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    face_normals /= np.maximum(np.linalg.norm(face_normals, axis=1, keepdims=True), 1e-8)
    normals = np.repeat(face_normals, 3, axis=0).astype(np.float32)

    n_triangles = len(tri)
    colors = _face_colors(shape, colorscheme)
    if colors is not None and len(colors) == n_triangles * 4:
        rgb = np.frombuffer(colors, dtype=np.uint8).reshape(-1, 4)[:, :3].astype(np.float32) / 255.0
        per_vertex = np.repeat(rgb, 3, axis=0)
    else:
        per_vertex = np.tile(_DEFAULT_COLOR, (n_triangles * 3, 1))
    return {"points": points, "normals": normals, "colors": per_vertex}


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
        # OpenSCAD 是 Z-up，预览器跟随（此前用 Y-up，与 OpenSCAD 的默认视角不一致）
        self.yaw, self.pitch, self.distance = -60.0, 30.0, 3.0
        self.target = np.zeros(3, dtype=np.float64)
        self.update()

    def set_view(self, yaw, pitch):
        """直接设定视角（用于预设按钮）。pitch 会夹到 ±89.5，避免与 up 向量平行。"""
        self.yaw = float(yaw)
        self.pitch = max(-89.5, min(89.5, float(pitch)))
        self.update()

    def _eye_direction(self):
        """由 yaw/pitch 得到相机相对目标点的方向（单位向量，Z-up）。"""
        yaw, pitch = np.radians([self.yaw, self.pitch])
        return np.array([np.cos(pitch) * np.cos(yaw),
                         np.cos(pitch) * np.sin(yaw),
                         np.sin(pitch)], dtype=np.float64)

    def _view(self):
        eye = self.target + self.distance * self._eye_direction()
        matrix = QMatrix4x4()
        matrix.lookAt(QVector3D(*(float(v) for v in eye)),
                      QVector3D(*(float(v) for v in self.target)),
                      QVector3D(0.0, 0.0, 1.0))
        return matrix

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

    def mousePressEvent(self, event):
        self.last_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        current = event.position().toPoint()
        delta = current - self.last_pos
        self.last_pos = current
        if event.buttons() & Qt.LeftButton:
            self.yaw -= delta.x() * 0.6
            self.pitch = max(-89.5, min(89.5, self.pitch + delta.y() * 0.6))
        elif event.buttons() & Qt.RightButton:
            # 沿屏幕的右/上方向平移目标点（Z-up 下屏幕上方不是世界 Y）
            direction = self._eye_direction()
            right = np.cross(direction, (0.0, 0.0, 1.0))
            norm = float(np.linalg.norm(right))
            right = right / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
            up = np.cross(right, direction)
            scale = 0.005 * self.distance
            self.target = self.target - delta.x() * scale * right + delta.y() * scale * up
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
        self.colorscheme = None   # None = 用库当前配色
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
        self._add_action(file_menu, "导出整个视图序列 PNG…（按当前视角）", self._export_frames_png)
        file_menu.addSeparator()
        self._add_action(file_menu, "退出", self.close, QKeySequence("Ctrl+Q"))

        view_menu = bar.addMenu("视图(&V)")
        self._add_action(view_menu, "重置视角", self._reset_view, QKeySequence("Home"))
        presets = view_menu.addMenu("视角预设")
        for label, (yaw, pitch) in (
            ("前视图", (-90.0, 0.0)),
            ("右视图", (0.0, 0.0)),
            ("俯视图", (-90.0, 89.5)),
            ("等轴测", (-60.0, 30.0)),
        ):
            self._add_action(presets, label, lambda checked=False, y=yaw, p=pitch: self._set_preset(y, p))
        self.ortho_action = QAction("正交投影", self, checkable=True)
        self.ortho_action.toggled.connect(self._toggle_ortho)
        view_menu.addAction(self.ortho_action)
        scheme_menu = view_menu.addMenu("配色方案")
        self._add_action(scheme_menu, "默认（库当前配色）", lambda: self.set_colorscheme(None))
        for name in _color_schemes():
            self._add_action(scheme_menu, name, lambda checked=False, n=name: self.set_colorscheme(n))

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

    def _set_preset(self, yaw, pitch):
        if isinstance(self.view, Interactive3D):
            self.view.set_view(yaw, pitch)

    def _toggle_ortho(self, checked):
        if isinstance(self.view, Interactive3D):
            self.view.orthographic = checked
            self.view.update()

    def set_colorscheme(self, name):
        """切换配色：重新取逐面颜色并重传缓冲。

        注意配色是**全局**的（上游 set_render_color_scheme 语义）。动画下要逐帧重新求值，
        帧多时会慢（状态栏会给提示）。
        """
        self.colorscheme = name
        if not isinstance(self.view, Interactive3D):
            return
        self.statusBar().showMessage(f"切换配色 {name or '默认'} …")
        QApplication.processEvents()
        source = self.frame_fn if self.frame_fn is not None else (lambda _index: self.shape)
        for index, mesh in enumerate(self.view.meshes):
            colors = _face_colors(source(index), name)
            n_triangles = len(mesh["points"]) // 3
            if colors is not None and len(colors) == n_triangles * 4:
                rgb = np.frombuffer(colors, np.uint8).reshape(-1, 4)[:, :3].astype(np.float32) / 255.0
                mesh["colors"] = np.repeat(rgb, 3, axis=0)
        if self.view.vertex_buffer is not None:
            self.view.vertex_buffer.bind()
            self.view._upload()
            self.view.vertex_buffer.release()
        self.view.update()
        self._refresh_status()

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

    def _export_frames_png(self):
        """按当前视角逐帧截图，导出 PNG 序列（与窗口所见一致：走 GL 截图而非引擎渲染）。"""
        if self.view is None or not hasattr(self.view, "grabFramebuffer"):
            QMessageBox.information(self, "导出序列", "当前视图不支持截图。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if not directory:
            return
        was_playing = self.timer.isActive()
        if was_playing:
            self.timer.stop()
        total = max(self.frames, 1)
        try:
            for index in range(total):
                if self.frames:
                    self._goto(index)
                QApplication.processEvents()
                self.view.grabFramebuffer().save(os.path.join(directory, f"view{index:03d}.png"))
        except Exception as exc:  # 导出失败不该让窗口崩
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        if was_playing:
            self.timer.start()
        QMessageBox.information(self, "导出完成", f"已保存 {total} 张到 {directory}")

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