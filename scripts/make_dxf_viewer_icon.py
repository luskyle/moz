"""生成 DXF/DWG 看图器的品牌图标（简单文字版）→ vsix 里的 icon.png。

透明底 + 粗体 "M"（moz 首字母，品牌蓝）+ 一个橙色拾取点（dxf 主题色）。
Qt 直接画（ARGB32 透明背景），不需要 OpenSCAD 内核。

用法：

    PYTHONPATH=py python3 scripts/make_dxf_viewer_icon.py plugins/vscode-dxf-viewer/icon.png
"""
import argparse
import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

BRAND_BLUE = QColor("#1857e0")
ACCENT = QColor("#ff8a1e")


def render(out, size=512, letter="M", pixel_size=400):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont("DejaVu Sans", 1, QFont.Bold)
    font.setPixelSize(pixel_size)
    painter.setFont(font)
    painter.setPen(BRAND_BLUE)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, letter)
    # 拾取点：右下角的橙色圆点（dxf 主题色）
    dot = max(64, size // 4)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ACCENT)
    painter.drawEllipse(QRectF(size - dot - size // 14, size - dot - size // 14,
                               dot, dot))
    painter.end()
    if not image.save(out):
        raise SystemExit(f"保存失败：{out}")
    print(f"已生成 {out}（{size}×{size}，{letter}）")


def main():
    parser = argparse.ArgumentParser(description="生成扩展图标 PNG（简单文字版）")
    parser.add_argument("out", help="输出 PNG 路径")
    parser.add_argument("--size", type=int, default=512)
    args = parser.parse_args()
    # 离屏无显示器也能画（字体/绘图需要 QGuiApplication）
    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    del app
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    render(os.path.abspath(args.out), args.size)


if __name__ == "__main__":
    sys.exit(main())
