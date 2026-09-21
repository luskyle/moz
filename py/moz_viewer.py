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
from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QMatrix4x4, QOpenGLFunctions, QPainter, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSlider,
    QStatusBar,
    QToolBar,
)

# 未着色对象在预览器里的默认材质色（与 OpenSCAD 默认配色同色系）
_DEFAULT_COLOR = np.asarray([0.20, 0.62, 0.90], dtype=np.float32)
# 边线（wireframe 叠加）的颜色：深色，压在亮色实体上看得出轮廓
_EDGE_COLOR = np.asarray([0.10, 0.12, 0.15], dtype=np.float32)


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


# 叠加层（坐标轴 / 地面网格）在归一化空间里的尺寸（几何已缩放到单位半径）
_AXIS_LENGTH = 1.25
_GRID_STEP = 0.25


def _line_geometry(show_axes, show_grid):
    """返回 (positions, colors)：坐标轴（X 红 / Y 绿 / Z 蓝）与 Z=0 地面网格的线段。

    预览器是 Z-up，所以网格铺在 Z=0 平面上。两者都关时返回 (None, None)。
    """
    positions, colors = [], []
    if show_axes:
        for direction, color in (((1.0, 0.0, 0.0), (0.92, 0.26, 0.26)),
                                 ((0.0, 1.0, 0.0), (0.30, 0.80, 0.30)),
                                 ((0.0, 0.0, 1.0), (0.30, 0.50, 0.95))):
            for sign in (-1.0, 1.0):
                positions.append((0.0, 0.0, 0.0))
                colors.append(color)
                positions.append(tuple(sign * _AXIS_LENGTH * value for value in direction))
                colors.append(color)
    if show_grid:
        grid_color = (0.34, 0.36, 0.40)
        steps = int(round(_AXIS_LENGTH / _GRID_STEP))
        for i in range(-steps, steps + 1):
            offset = i * _GRID_STEP
            for start, end in (((offset, -_AXIS_LENGTH, 0.0), (offset, _AXIS_LENGTH, 0.0)),
                               ((-_AXIS_LENGTH, offset, 0.0), (_AXIS_LENGTH, offset, 0.0))):
                positions.append(start)
                colors.append(grid_color)
                positions.append(end)
                colors.append(grid_color)
    if not positions:
        return None, None
    return (np.asarray(positions, dtype=np.float32).reshape(-1, 3),
            np.asarray(colors, dtype=np.float32).reshape(-1, 3))


def _edge_geometry(points, tolerance=1e-5):
    """三角面的边 → 线段顶点（去重后的唯一边），用于 wireframe 叠加。

    先按 `tolerance` 量化顶点再 `np.unique`，避免逐三角面 Python 循环（上万面也很快）。
    """
    if not len(points):
        return None
    quantized = np.round(points.astype(np.float64) / tolerance).astype(np.int64)
    unique_vertices, inverse = np.unique(quantized, axis=0, return_inverse=True)
    triangles = inverse.reshape(-1, 3)
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]], axis=0)
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    vertices = unique_vertices.astype(np.float64) * tolerance
    return vertices[edges.reshape(-1)].astype(np.float32)


class Interactive3D(QOpenGLWidget):
    """3D 视图：可显示一帧或一串动画帧（帧间共用同一 center/radius，避免抖动）。"""

    picked = Signal(object)      # 点选结果（dict）或 None

    def __init__(self, meshes, parent=None):
        super().__init__(parent)
        if not meshes:
            raise ValueError("Interactive3D needs at least one mesh")
        self.meshes = meshes
        self.index = 0
        self.part_ranges = None      # 多部件模式：[[name, start_vertex, count, visible], ...]
        self.center, self.radius = self._bounds(meshes)
        self.program = None
        self.gl = None
        self.vertex_buffer = None
        self.vao = None
        self.line_program = None
        self.line_vao = None
        self.line_buffer = None
        self.line_count = 0
        self.edge_vao = None
        self.edge_buffer = None
        self.edge_count = 0
        self.show_axes = False
        self.show_grid = False
        self.show_edges = False
        self.last_pos = QPoint()
        self._press_pos = None
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

    def engine_camera(self):
        """把当前视角换算成引擎相机，使引擎渲染与窗口视角一致。

        预览器是 ``lookAt(eye, target, +Z)``；上游是 ``R = Rx(rx)·Ry(ry)·Rz(rz)`` 之后从
        ``(0, -dist, 0)`` 用 ``+Z`` 观察（即 ``M = L·R``，``L`` 是那次 lookAt）。
        两者的旋转部分相等：``R = Lᵀ·M_ours``，再从 ``R`` 取 ZYX 欧拉角。
        ``vpr = (90 - rx, -ry, -rz)``（见上游 ``Camera::setVpr``）。

        返回 ``(vpr, vpt, vpd, vpf)``：坐标都换算回**世界单位**（引擎渲染的是原始模型，
        预览器则把网格归一化到单位半径）。正交模式下等效视场角取 ``2·atan(0.55)``，
        与 ``_projection`` 里的 ``half = distance * 0.55`` 对齐。
        """
        eye = self.target + self.distance * self._eye_direction()
        # 归一化空间 → 世界空间
        eye_w = self.center + self.radius * eye
        target_w = self.center + self.radius * self.target
        up = np.array([0.0, 0.0, 1.0])

        z = eye_w - target_w
        z = z / np.linalg.norm(z)
        x = np.cross(up, z)
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)
        m_ours = np.vstack([x, y, z])                      # lookAt 的旋转部分（行 = 相机轴）

        l_rot = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
        rotation = l_rot.T @ m_ours                        # R = Lᵀ · M
        # R = Rx(a)Ry(b)Rz(c) 的欧拉角
        b = float(np.arcsin(max(-1.0, min(1.0, rotation[0, 2]))))
        a = float(np.arctan2(-rotation[1, 2], rotation[2, 2]))
        c = float(np.arctan2(-rotation[0, 1], rotation[0, 0]))
        object_rot = np.degrees([a, b, c])
        vpr = [90.0 - object_rot[0], -object_rot[1], -object_rot[2]]

        vpf = float(np.degrees(2.0 * np.arctan(0.55))) if self.orthographic else 45.0
        return vpr, [float(value) for value in target_w], float(self.radius * self.distance), vpf

    def _ray(self, x, y):
        """屏幕坐标 → 归一化空间里的一条射线 (origin, direction)。"""
        width, height = max(self.width(), 1), max(self.height(), 1)
        aspect = width / height
        ndc_x = 2.0 * x / width - 1.0
        ndc_y = 1.0 - 2.0 * y / height

        view_direction = -self._eye_direction()          # 视线方向（eye → target）
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(view_direction, world_up)
        right = right / max(float(np.linalg.norm(right)), 1e-9)
        up = np.cross(right, view_direction)
        if self.orthographic:
            half = self.distance * 0.55
            origin = self.target + right * (ndc_x * half * aspect) + up * (ndc_y * half)
            direction = view_direction
        else:
            half = np.tan(np.radians(45.0) / 2.0)
            origin = self.target + self.distance * self._eye_direction()
            direction = view_direction + right * (ndc_x * half * aspect) + up * (ndc_y * half)
            direction = direction / max(float(np.linalg.norm(direction)), 1e-9)
        return origin, direction

    def pick(self, x, y):
        """按屏幕坐标拾取最近的面；返回 dict（世界坐标、三角形号、部件名）或 None。"""
        points = self.meshes[self.index]["points"]
        if not len(points):
            return None
        # mesh["points"] 是世界坐标（归一化只在上传 GPU 时做），这里先归一化到与 _ray 同一个空间
        triangles = self._normalized(self.meshes[self.index]).reshape(-1, 3, 3).astype(np.float64)
        candidates = np.arange(len(triangles))
        if self.part_ranges is not None:      # 只测可见部件
            visible = []
            for _name, start, count, shown in self.part_ranges:
                if shown and count:
                    visible.append(np.arange(start // 3, (start + count) // 3))
            candidates = np.concatenate(visible) if visible else np.empty(0, dtype=np.int64)
        if not len(candidates):
            return None
        triangles = triangles[candidates]

        origin, direction = self._ray(x, y)
        v0 = triangles[:, 0]
        edge1 = triangles[:, 1] - v0
        edge2 = triangles[:, 2] - v0
        pvec = np.cross(direction, edge2)
        det = np.einsum("ij,ij->i", edge1, pvec)
        mask = np.abs(det) > 1e-12
        inverse = np.zeros_like(det)
        inverse[mask] = 1.0 / det[mask]
        tvec = origin - v0
        bary_u = np.einsum("ij,ij->i", tvec, pvec) * inverse
        mask &= (bary_u >= -1e-9) & (bary_u <= 1.0 + 1e-9)
        qvec = np.cross(tvec, edge1)
        bary_v = (qvec @ direction) * inverse      # direction 是 1-D，用矩阵乘而不是 einsum
        mask &= (bary_v >= -1e-9) & (bary_u + bary_v <= 1.0 + 1e-9)
        distance = np.einsum("ij,ij->i", edge2, qvec) * inverse
        mask &= distance > 1e-9
        if not mask.any():
            return None
        nearest = int(np.argmin(np.where(mask, distance, np.inf)))
        hit = int(candidates[nearest])
        hit_normalized = origin + distance[nearest] * direction
        part = None
        if self.part_ranges is not None:
            for name, start, count, shown in self.part_ranges:
                if shown and start // 3 <= hit < (start + count) // 3:
                    part = name
                    break
        return {
            "world": self.center + self.radius * hit_normalized,
            "normalized": hit_normalized,
            "triangle": int(hit),
            "part": part,
        }

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
        if self.show_edges and self.edge_buffer is not None:
            self.edge_buffer.bind()
            self._upload_edges()
            self.edge_buffer.release()
        self.update()

    def _line_positions(self):
        """按当前开关返回叠加层几何，并同步 line_count（窗口未显示时也要一致）。"""
        positions, colors = _line_geometry(self.show_axes, self.show_grid)
        self.line_count = 0 if positions is None else len(positions)
        return positions, colors

    def _upload_lines(self):
        """把叠加层（坐标轴/网格）写进 line_buffer（**要求调用方已 bind**）。"""
        positions, colors = self._line_positions()
        if positions is None:
            return
        interleaved = np.hstack((positions, colors)).astype(np.float32)
        self.line_buffer.allocate(interleaved.tobytes(), interleaved.nbytes)

    def set_overlays(self, show_axes=None, show_grid=None):
        """开关坐标轴 / 地面网格（视图菜单）。"""
        if show_axes is not None:
            self.show_axes = bool(show_axes)
        if show_grid is not None:
            self.show_grid = bool(show_grid)
        self._line_positions()      # 先算出 line_count（GL 缓冲可能还没建）
        if self.line_buffer is not None:
            self.line_buffer.bind()
            self._upload_lines()
            self.line_buffer.release()
        self.update()

    def _edge_positions(self):
        """按当前开关返回边线几何，并同步 edge_count（窗口未显示时也要一致）。"""
        if not self.show_edges:
            self.edge_count = 0
            return None
        positions = _edge_geometry(self._normalized(self.meshes[self.index]))
        self.edge_count = 0 if positions is None else len(positions)
        return positions

    def _upload_edges(self):
        """把当前帧的唯一边写进 edge_buffer（**要求调用方已 bind**）。"""
        positions = self._edge_positions()
        if positions is None:
            return
        colors = np.tile(_EDGE_COLOR, (len(positions), 1))
        interleaved = np.hstack((positions, colors)).astype(np.float32)
        self.edge_buffer.allocate(interleaved.tobytes(), interleaved.nbytes)

    def set_edges(self, show):
        """开关 wireframe 边线（视图菜单）。"""
        self.show_edges = bool(show)
        self._edge_positions()          # GL 缓冲可能还没建，先同步 edge_count
        if self.edge_buffer is not None:
            self.edge_buffer.bind()
            self._upload_edges()
            self.edge_buffer.release()
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

        # 叠加层（坐标轴 / 地面网格）：单独一套线框着色器与缓冲
        self.line_program = QOpenGLShaderProgram(self)
        line_vertex = """
            attribute vec3 position;
            attribute vec3 color;
            uniform mat4 mvp;
            varying vec3 vertexColor;
            void main() { vertexColor = color; gl_Position = mvp * vec4(position, 1.0); }
        """
        line_fragment = """
            varying vec3 vertexColor;
            void main() { gl_FragColor = vec4(vertexColor, 1.0); }
        """
        if not self.line_program.addShaderFromSourceCode(QOpenGLShader.Vertex, line_vertex):
            raise RuntimeError(self.line_program.log())
        if not self.line_program.addShaderFromSourceCode(QOpenGLShader.Fragment, line_fragment):
            raise RuntimeError(self.line_program.log())
        if not self.line_program.link():
            raise RuntimeError(self.line_program.log())
        self.line_vao = QOpenGLVertexArrayObject(self)
        self.line_vao.create()
        self.line_vao.bind()
        self.line_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.line_buffer.create()
        self.line_buffer.bind()
        self._upload_lines()
        self.line_program.bind()
        self.line_program.enableAttributeArray("position")
        self.line_program.enableAttributeArray("color")
        # 步长 24 字节：position(0) / color(12)
        self.line_program.setAttributeBuffer("position", 0x1406, 0, 3, 24)
        self.line_program.setAttributeBuffer("color", 0x1406, 12, 3, 24)
        self.line_buffer.release()
        self.line_vao.release()
        self.line_program.release()

        # 边线（wireframe 叠加）：复用同一套线框着色器，单独一个顶点缓冲
        self.edge_vao = QOpenGLVertexArrayObject(self)
        self.edge_vao.create()
        self.edge_vao.bind()
        self.edge_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.edge_buffer.create()
        self.edge_buffer.bind()
        self._upload_edges()
        self.line_program.bind()
        self.line_program.enableAttributeArray("position")
        self.line_program.enableAttributeArray("color")
        self.line_program.setAttributeBuffer("position", 0x1406, 0, 3, 24)
        self.line_program.setAttributeBuffer("color", 0x1406, 12, 3, 24)
        self.edge_buffer.release()
        self.edge_vao.release()
        self.line_program.release()

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
        if self.edge_count:
            # 让边线压过面（否则共面处会 z-fighting）
            self.gl.glEnable(0x8037)          # GL_POLYGON_OFFSET_FILL
            self.gl.glPolygonOffset(1.0, 1.0)
        self.vao.bind()
        if self.part_ranges is None:
            self.gl.glDrawArrays(0x0004, 0, len(self.meshes[self.index]["points"]))
        else:                                   # 多部件：只画可见部件（各段连续，用 first 偏移）
            for _name, start, count, shown in self.part_ranges:
                if shown and count:
                    self.gl.glDrawArrays(0x0004, start, count)
        self.vao.release()
        if self.edge_count:
            self.gl.glDisable(0x8037)
        self.program.release()

        if self.edge_count and self.edge_buffer is not None:
            self.line_program.bind()
            self.line_program.setUniformValue("mvp", projection * view)
            self.edge_vao.bind()
            self.gl.glDrawArrays(0x0001, 0, self.edge_count)   # GL_LINES
            self.edge_vao.release()
            self.line_program.release()

        if self.line_count and self.line_program is not None:
            self.line_program.bind()
            self.line_program.setUniformValue("mvp", projection * view)
            self.line_vao.bind()
            self.gl.glDrawArrays(0x0001, 0, self.line_count)   # GL_LINES
            self.line_vao.release()
            self.line_program.release()

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
        self._press_pos = self.last_pos

    def mouseReleaseEvent(self, event):
        """左键单击（不是拖动）→ 拾取最近的面并发出 picked 信号。"""
        if event.button() != Qt.LeftButton or self._press_pos is None:
            return
        current = event.position().toPoint()
        moved = (current - self._press_pos).manhattanLength()
        self._press_pos = None
        if moved > 4:          # 拖动是旋转视角，不算点选
            return
        self.picked.emit(self.pick(current.x(), current.y()))

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


class Interactive2D(QGraphicsView):
    """2D 视图：SVG 矢量图，滚轮缩放、左键拖动平移、双击「适应窗口」。"""

    def __init__(self, shape, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._renderer = QSvgRenderer(QByteArray(shape.export_bytes("svg")))
        self._item = QGraphicsSvgItem()
        self._item.setSharedRenderer(self._renderer)
        scene = QGraphicsScene(self)
        scene.addItem(self._item)
        self.setScene(scene)
        self.setSceneRect(self._item.boundingRect())
        self.fit_to_window()

    def fit_to_window(self):
        """缩放到刚好显示整张图。"""
        if not self._item.boundingRect().isEmpty():
            self.fitInView(self._item, Qt.KeepAspectRatio)

    def reset_view(self):
        self.resetTransform()
        self.fit_to_window()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        self.fit_to_window()


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
        self.part_shapes = {}     # 多部件模式：name -> Shape
        self.parts_dock = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self._build_menus()
        self._build_anim_bar()

    def _build_anim_bar(self):
        """动画工具条：帧滑块 + 播放速度（只在动画模式下显示）。"""
        self.anim_bar = QToolBar("动画", self)
        self.addToolBar(Qt.BottomToolBarArea, self.anim_bar)
        self.frame_slider = QSlider(Qt.Horizontal, self)
        self.frame_slider.setMinimumWidth(240)
        self.frame_slider.valueChanged.connect(self._on_slider)
        self.frame_label = QLabel("0/0", self)
        self.fps_spin = QDoubleSpinBox(self)
        self.fps_spin.setRange(0.5, 120.0)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.valueChanged.connect(self._on_fps)
        self.anim_bar.addWidget(QLabel("帧", self))
        self.anim_bar.addWidget(self.frame_slider)
        self.anim_bar.addWidget(self.frame_label)
        self.anim_bar.addSeparator()
        self.anim_bar.addWidget(QLabel("速度", self))
        self.anim_bar.addWidget(self.fps_spin)
        self.anim_bar.setVisible(False)

    def _on_slider(self, value):
        if not self.frames:
            return
        if self.timer.isActive():
            self._toggle_play()      # 手动拖帧就暂停
        self._goto(value)

    def _on_fps(self, value):
        self.fps = float(value)
        if self.frames:
            self.timer.setInterval(max(1, int(1000.0 / self.fps)))
        self._refresh_status()

    # ------------------------------------------------------------------ 载入
    def set_shape(self, shape):
        """显示单个静态几何。"""
        self.shape = shape
        self.frame_fn = None
        self.part_shapes = {}
        self._remove_parts_dock()
        if shape.is_empty:
            # 上游语义下空几何的 dimension 仍是 3（空 Nef），所以要先判空
            self.view = QLabel("空几何")
            self.status_hint = "空几何"
        elif shape.dimension == 3:
            self.view = self._make_3d_view([_mesh_from_shape(shape)])
            self.status_hint = "左键旋转 | 右键平移 | 滚轮缩放 | 左键单击测量 | 颜色来自 color()"
        elif shape.dimension == 2:
            self.view = Interactive2D(shape, self)
            self.status_hint = "SVG 矢量视图 | 滚轮缩放 | 左键拖动平移 | 双击适应窗口"
        else:
            self.view = QLabel("空几何")
            self.status_hint = "空几何"
        self.setCentralWidget(self.view)
        self.anim_menu.setEnabled(False)
        self.anim_bar.setVisible(False)
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
        self.part_shapes = {}
        self._remove_parts_dock()
        meshes = []
        first = None
        # 预计算是帧数与求值次数的乘积，大模型会慢 —— 给进度并可取消。
        # （不做「按需求值 + LRU」：各帧包围盒需要在取景前统一，否则逐帧重新居中会抖动。）
        progress = QProgressDialog("正在预计算动画帧 …", "取消", 0, frames, self)
        progress.setWindowTitle("moz viewer")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)
        cancelled = False
        for i in range(frames):
            progress.setValue(i)
            progress.setLabelText(f"正在预计算动画帧 {i + 1}/{frames} …")
            QApplication.processEvents()
            if progress.wasCanceled():
                cancelled = True
                break
            shape = frame_fn(i)
            if first is None:
                first = shape
                if shape.is_empty or shape.dimension != 3:
                    progress.close()
                    self.set_shape(shape)  # 非 3D 没法在 GL 里动画，退回静态
                    return
            meshes.append(_mesh_from_shape(shape))
        progress.setValue(frames)
        progress.close()
        if cancelled:
            self.status_hint = f"已取消（预计算了 {len(meshes)}/{frames} 帧）"
            if meshes:
                self.view = self._make_3d_view(meshes)
                self.setCentralWidget(self.view)
                self.frames = len(meshes)
                self._refresh_status()
            else:
                self.view = QLabel("已取消")
                self.setCentralWidget(self.view)
                self._refresh_status()
            return
        if not meshes:
            self.set_shape(first)
            return

        self.frames = len(meshes)
        self.fps = float(fps) if fps > 0 else 8.0
        self.view = self._make_3d_view(meshes)
        self.setCentralWidget(self.view)
        self.anim_menu.setEnabled(True)
        self.index = 0
        self.timer.setInterval(max(1, int(1000.0 / self.fps)))
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, self.frames - 1)
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)
        self.fps_spin.blockSignals(True)
        self.fps_spin.setValue(self.fps)
        self.fps_spin.blockSignals(False)
        self.anim_bar.setVisible(True)
        self._refresh_status()

    # ------------------------------------------------------------------ 菜单
    def _make_3d_view(self, meshes, part_ranges=None):
        """建 Interactive3D 并接上点选信号（多部件时带上分段信息）。"""
        view = Interactive3D(meshes, self)
        if part_ranges is not None:
            view.part_ranges = part_ranges
        view.picked.connect(self._on_picked)
        return view

    def _remove_parts_dock(self):
        if self.parts_dock is not None:
            self.removeDockWidget(self.parts_dock)
            self.parts_dock = None

    def set_parts(self, parts, title=None):
        """显示多个命名部件：右侧列表可勾选显示/隐藏，点选会报告部件名。

        parts 是 ``(name, Shape)`` 序列或 ``{name: Shape}`` 字典；各部件共用一套
        居中/缩放（否则小零件会被放大得和大的一样）。
        """
        items = list(parts.items()) if isinstance(parts, dict) else list(parts)
        if not items:
            raise ValueError("set_parts requires at least one part")
        if title:
            self.setWindowTitle(title)
        self.shape = None
        self.frame_fn = None
        self.part_shapes = dict(items)
        self._remove_parts_dock()

        part_meshes = [_mesh_from_shape(shape) for _name, shape in items]
        combined = {key: np.vstack([mesh[key] for mesh in part_meshes])
                    for key in ("points", "normals", "colors")}
        ranges, offset = [], 0
        for (name, _shape), mesh in zip(items, part_meshes, strict=False):
            count = len(mesh["points"])
            ranges.append([name, offset, count, True])
            offset += count

        self.view = self._make_3d_view([combined], part_ranges=ranges)
        self.setCentralWidget(self.view)
        self.anim_menu.setEnabled(False)
        self.anim_bar.setVisible(False)
        self._build_parts_dock([name for name, _shape in items])
        self.status_hint = "左键旋转 | 右键平移 | 滚轮缩放 | 左键单击选部件 | 右侧列表可隐藏部件"
        self._refresh_status()

    def _build_parts_dock(self, names):
        self.parts_list = QListWidget(self)
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.parts_list.addItem(item)
        self.parts_list.itemChanged.connect(self._on_part_toggled)
        self.parts_dock = QDockWidget("部件", self)
        self.parts_dock.setWidget(self.parts_list)
        self.addDockWidget(Qt.RightDockWidgetArea, self.parts_dock)

    def _on_part_toggled(self, item):
        if isinstance(self.view, Interactive3D) and self.view.part_ranges:
            row = self.parts_list.row(item)
            if row < len(self.view.part_ranges):
                self.view.part_ranges[row][3] = item.checkState() == Qt.Checked
                self.view.update()

    def _on_picked(self, info):
        """点选结果 → 状态栏（世界坐标、距原点距离、面号、部件名）。"""
        if not info:
            self.statusBar().showMessage("点选：未命中")
            return
        x, y, z = (float(v) for v in info["world"])
        distance = float(np.linalg.norm(info["world"]))
        part = f" | 部件 {info['part']}" if info.get("part") else ""
        self.statusBar().showMessage(
            f"点选：({x:.3f}, {y:.3f}, {z:.3f}) | 距原点 {distance:.3f}"
            f" | 面 #{info['triangle']}{part}")

    def _build_menus(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("文件(&F)")
        self._add_action(file_menu, "导出当前帧 STL…", self._export_stl, QKeySequence("Ctrl+S"))
        self._add_action(file_menu, "导出当前帧 PNG（引擎渲染）…", self._export_png, QKeySequence("Ctrl+E"))
        self._add_action(file_menu, "保存视图截图…", self._save_screenshot, QKeySequence("Ctrl+Shift+S"))
        self._add_action(file_menu, "导出整个视图序列 PNG…（按当前视角）", self._export_frames_png)
        self._add_action(file_menu, "导出动画 GIF…（需要 Pillow）", self._export_gif, QKeySequence("Ctrl+G"))
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
        self.axes_action = QAction("显示坐标轴", self, checkable=True)
        self.axes_action.toggled.connect(lambda checked: self._set_overlay(show_axes=checked))
        view_menu.addAction(self.axes_action)
        self.grid_action = QAction("显示地面网格（Z=0）", self, checkable=True)
        self.grid_action.toggled.connect(lambda checked: self._set_overlay(show_grid=checked))
        view_menu.addAction(self.grid_action)
        self.edges_action = QAction("显示边线（wireframe）", self, checkable=True)
        self.edges_action.toggled.connect(lambda checked: self._set_edges(checked))
        view_menu.addAction(self.edges_action)
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
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(self.index)
        self.frame_slider.blockSignals(False)
        self.frame_label.setText(f"{self.index + 1}/{self.frames}")
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
        if isinstance(self.view, Interactive3D | Interactive2D):
            self.view.reset_view()

    def _set_preset(self, yaw, pitch):
        if isinstance(self.view, Interactive3D):
            self.view.set_view(yaw, pitch)

    def _toggle_ortho(self, checked):
        if isinstance(self.view, Interactive3D):
            self.view.orthographic = checked
            self.view.update()

    def _set_overlay(self, show_axes=None, show_grid=None):
        if isinstance(self.view, Interactive3D):
            self.view.set_overlays(show_axes=show_axes, show_grid=show_grid)

    def _set_edges(self, checked):
        if isinstance(self.view, Interactive3D):
            self.view.set_edges(checked)

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

        def _rgb(colors):
            if colors is None:
                return None
            return np.frombuffer(colors, np.uint8).reshape(-1, 4)[:, :3].astype(np.float32) / 255.0

        if self.view.part_ranges is not None and self.part_shapes:
            # 多部件：合并缓冲里按部件分段写回颜色
            mesh = self.view.meshes[0]
            for part_name, start, count, _shown in self.view.part_ranges:
                rgb = _rgb(_face_colors(self.part_shapes[part_name], name))
                if rgb is None or len(rgb) != count // 3:
                    continue
                mesh["colors"][start:start + count] = np.repeat(rgb, 3, axis=0)
        else:
            source = self.frame_fn if self.frame_fn is not None else (lambda _index: self.shape)
            for index, mesh in enumerate(self.view.meshes):
                rgb = _rgb(_face_colors(source(index), name))
                if rgb is not None and len(rgb) == len(mesh["points"]) // 3:
                    mesh["colors"] = np.repeat(rgb, 3, axis=0)
        if self.view.vertex_buffer is not None:
            self.view.vertex_buffer.bind()
            self.view._upload()
            self.view.vertex_buffer.release()
        self.view.update()
        self._refresh_status()

    # ------------------------------------------------------------------ 文件
    def _current_source(self):
        """当前要导出的几何：动画取当前帧，多部件取可见部件的并集，否则原始几何。"""
        if self.frame_fn is not None:
            return self.frame_fn(self.index)
        if self.part_shapes and isinstance(self.view, Interactive3D) and self.view.part_ranges:
            import moz_openscad as moz
            visible = [self.part_shapes[name] for name, _start, _count, shown in self.view.part_ranges if shown]
            if not visible:
                raise RuntimeError("没有可见部件可导出")
            return visible[0] if len(visible) == 1 else moz.union(*visible)
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
            options = {}
            if isinstance(self.view, Interactive3D):
                # 把窗口视角换算成引擎相机，导出的图与所见一致
                vpr, vpt, vpd, vpf = self.view.engine_camera()
                options = dict(vpr=vpr, vpt=vpt, vpd=vpd, vpf=vpf,
                               projection="ortho" if self.view.orthographic else "perspective")
            width = self.view.width() if hasattr(self.view, "width") else 0
            height = self.view.height() if hasattr(self.view, "height") else 0
            source.render_png(path, width, height, **options)  # 引擎渲染，保留 color()
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

    def _export_gif(self):
        """把动画逐帧截图导出为 GIF。Pillow 是**可选**依赖，缺了会提示（不硬引）。"""
        if not self.frames:
            QMessageBox.information(self, "导出 GIF", "GIF 需要动画模式（多帧）。")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.information(
                self, "导出 GIF",
                "需要 Pillow：pip install Pillow\n（或先用「导出整个视图序列 PNG」拿 PNG 序列）")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 GIF", "animation.gif", "GIF (*.gif)")
        if not path or not hasattr(self.view, "grabFramebuffer"):
            return
        was_playing = self.timer.isActive()
        if was_playing:
            self.timer.stop()
        frames = []
        try:
            for index in range(self.frames):
                self._goto(index)
                QApplication.processEvents()
                image = self.view.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
                raw = bytes(image.constBits())
                pil = Image.frombytes("RGBA", (image.width(), image.height()), raw, "raw", "RGBA",
                                      image.bytesPerLine())
                frames.append(pil.convert("P", palette=Image.ADAPTIVE))
            frames[0].save(path, save_all=True, append_images=frames[1:],
                           duration=max(20, int(1000.0 / self.fps)), loop=0, disposal=2)
        except Exception as exc:  # 导出失败不该让窗口崩
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        finally:
            if was_playing:
                self.timer.start()
        QMessageBox.information(self, "导出完成", f"已保存 {len(frames)} 帧到 {path}")

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


def show_parts(parts, title="moz parts", width=1100, height=700):
    """打开窗口显示多个命名部件。

    parts 是 ``(name, Shape)`` 序列或 ``{name: Shape}`` 字典；右侧列表可勾选显示/隐藏，
    左键单击会报告点到的部件名与世界坐标。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    window = ViewerWindow(title=title, width=width, height=height)
    window.set_parts(parts)
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
