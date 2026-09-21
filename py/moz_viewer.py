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


def _stl_vertices(data):
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
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    center = (minimum + maximum) / 2
    radius = max(float(np.max(maximum - minimum)) / 2, 1e-3)
    return (points - center) / radius, face_normals


class Interactive3D(QOpenGLWidget):
    def __init__(self, shape, parent=None):
        super().__init__(parent)
        self.points, self.normals = _stl_vertices(shape.export_bytes("binstl"))
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
            uniform mat4 mvp;
            uniform mat4 modelView;
            varying vec3 viewNormal;
            varying vec3 viewPosition;
            void main() {
                vec4 positionInView = modelView * vec4(position, 1.0);
                viewPosition = positionInView.xyz;
                viewNormal = normalize((modelView * vec4(normal, 0.0)).xyz);
                gl_Position = mvp * vec4(position, 1.0);
            }
        """
        fragment_shader = """
            varying vec3 viewNormal;
            varying vec3 viewPosition;
            void main() {
                vec3 surfaceNormal = normalize(viewNormal);
                vec3 lightDirection = normalize(vec3(-0.45, 0.75, 1.0));
                vec3 viewDirection = normalize(-viewPosition);
                float diffuse = max(dot(surfaceNormal, lightDirection), 0.0);
                float rim = pow(1.0 - max(dot(surfaceNormal, viewDirection), 0.0), 2.0);
                float specular = pow(max(dot(reflect(-lightDirection, surfaceNormal), viewDirection), 0.0), 32.0);
                vec3 baseColor = vec3(0.20, 0.62, 0.90);
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
        interleaved = np.hstack((self.points, self.normals)).astype(np.float32)
        self.vertex_buffer.allocate(interleaved.tobytes(), interleaved.nbytes)
        self.program.bind()
        self.program.enableAttributeArray("position")
        self.program.enableAttributeArray("normal")
        self.program.setAttributeBuffer("position", 0x1406, 0, 3, 24)
        self.program.setAttributeBuffer("normal", 0x1406, 12, 3, 24)
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
    if shape.dimension == 3:
        view = Interactive3D(shape, window)
        message = "左键旋转 | 右键平移 | 滚轮缩放"
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
