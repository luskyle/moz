#!/usr/bin/env python3
"""Interactive Qt/OpenGL viewer for moz_openscad shapes."""

import argparse
import importlib.util
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMatrix4x4, QOpenGLFunctions, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QStatusBar


def _stl_vertices(data, face_colors=None):
    """binstl → 归一化顶点 / 法线 / 逐顶点颜色。

    face_colors 是 moz_geom_face_colors 的输出（4 字节/面，顺序与 STL 三角面一一对应）；
    同一三角面的三个顶点取同一个颜色。没有颜色信息时返回 None。
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
    points = np.asarray(vertices, dtype=np.float32)
    face_normals = np.asarray(normals, dtype=np.float32)
    face_normals /= np.maximum(np.linalg.norm(face_normals, axis=1, keepdims=True), 1e-8)

    colors = None
    if face_colors is not None and len(face_colors) == count * 4:
        per_vertex = []
        for index in range(count):
            rgb = [face_colors[index * 4 + channel] / 255.0 for channel in range(3)]
            per_vertex.extend((rgb, rgb, rgb))
        colors = np.asarray(per_vertex, dtype=np.float32)

    minimum, maximum = points.min(axis=0), points.max(axis=0)
    center = (minimum + maximum) / 2
    radius = max(float(np.max(maximum - minimum)) / 2, 1e-3)
    return (points - center) / radius, face_normals, colors


def _face_colors(shape):
    """取逐面颜色；旧版库或非 3D 几何拿不到时返回 None（预览器退回默认色）。"""
    try:
        return shape.face_colors()
    except Exception:
        return None


class Interactive3D(QOpenGLWidget):
    def __init__(self, shape, parent=None):
        super().__init__(parent)
        stl = shape.export_bytes("binstl")
        self.points, self.normals, colors = _stl_vertices(stl, _face_colors(shape))
        if colors is None:
            # 拿不到逐面颜色时用默认材质色（与 OpenSCAD 默认配色同色系）
            colors = np.tile(np.asarray([0.20, 0.62, 0.90], dtype=np.float32),
                             (len(self.points), 1))
        self.colors = colors
        self.program = None
        self.gl = None
        self.vertex_buffer = None
        self.vao = None
        self.last_pos = QPoint()
        self.yaw, self.pitch, self.distance = -35.0, 25.0, 3.0
        self.pan_x = self.pan_y = 0.0
        self.setMinimumSize(640, 480)

    def initializeGL(self):
        self.gl = QOpenGLFunctions(self.context())
        self.gl.initializeOpenGLFunctions()
        self.gl.glClearColor(0.08, 0.09, 0.11, 1.0)
        self.gl.glEnable(0x0B71)
        self.gl.glEnable(0x0B44)
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
        interleaved = np.hstack((self.points, self.normals, self.colors)).astype(np.float32)
        self.vertex_buffer.allocate(interleaved.tobytes(), interleaved.nbytes)
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
        self.gl.glClear(0x00004100)
        if not self.program:
            return
        projection = self._projection(self.width() / max(self.height(), 1))
        self.program.bind()
        view = self._view()
        self.program.setUniformValue("mvp", projection * view)
        self.program.setUniformValue("modelView", view)
        self.vao.bind()
        self.gl.glDrawArrays(0x0004, 0, len(self.points))
        self.vao.release()
        self.program.release()

    def _projection(self, aspect):
        matrix = QMatrix4x4()
        matrix.perspective(45.0, aspect, 0.01, 100.0)
        return matrix

    def _view(self):
        yaw, pitch = np.radians([self.yaw, self.pitch])
        eye = QVector3D(float(self.distance * np.cos(pitch) * np.cos(yaw) + self.pan_x), float(self.distance * np.sin(pitch) + self.pan_y), float(self.distance * np.cos(pitch) * np.sin(yaw)))
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


def show_shape(shape, title="moz OpenSCAD", width=900, height=650):
    app = QApplication.instance() or QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle(title)
    window.resize(width, height)
    if shape.is_empty:
        # 注意：上游语义下空几何的 dimension 仍是 3（空 Nef），所以要先判空
        view = QLabel("空几何")
        message = "空几何"
    elif shape.dimension == 3:
        view = Interactive3D(shape, window)
        message = "左键旋转 | 右键平移 | 滚轮缩放 | 颜色来自 color()"
    elif shape.dimension == 2:
        view = Interactive2D(shape, window)
        message = "SVG 矢量视图"
    else:
        view = QLabel("空几何")
        message = "空几何"
    window.setCentralWidget(view)
    window.setStatusBar(QStatusBar())
    window.statusBar().showMessage(message)
    window.show()
    app.exec()


def main():
    parser = argparse.ArgumentParser(description="Preview a Python-built moz OpenSCAD shape")
    parser.add_argument("module", help="Python file exposing build()")
    args = parser.parse_args()
    path = Path(args.module).resolve()
    spec = importlib.util.spec_from_file_location("moz_viewer_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    show_shape(module.build(), title=f"moz - {path.stem}")


if __name__ == "__main__":
    main()
