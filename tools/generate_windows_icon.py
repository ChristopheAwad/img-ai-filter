"""Regenerate the Windows application icon from the source SVG."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))
RENDER_SIZE = 256


def render_svg(svg_bytes: bytes, size: int) -> Image.Image:
    """Render SVG bytes to a transparent square raster image."""
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    if not renderer.isValid():
        raise ValueError("The source SVG could not be rendered")

    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("The rendered icon could not be encoded")
    buffer.close()
    return Image.open(BytesIO(bytes(buffer.data())))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = root / "src" / "img_ai_filter" / "resources" / (
        "io.github.img_ai_filter.ImageFilter.svg"
    )
    output = root / "packaging" / "windows" / "ImageFilter.ico"

    if not source.is_file():
        raise SystemExit(f"Missing source icon: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    raster = render_svg(source.read_bytes(), RENDER_SIZE)
    raster.save(output, format="ICO", sizes=list(SIZES))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
