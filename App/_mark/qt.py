"""The gitSpecOps mark painted with Qt: the tray icon now, the Qt window later.

Why:          Qt's own SVG reader supports only part of SVG, and the tray needs crisp pixels at
              each size, so the mark is painted directly from the shared primitives.
Reads:        two states, and optionally one frame of the working animation.
May change:   nothing.
Results:      a QPixmap at one size, or a QIcon holding every tray and window size.
Layer:        App: presence and presentation (App alone may import PySide6).
Status:       working
"""
from __future__ import annotations

from App._mark.geometry import (DOT_HALO, HALO_EXTRA, HALO_RGBA, RING_WIDTH, SMALL_MAX, Dot, Line,
                                mark, style)

#: Sizes put into one icon; sizes up to 24 px use the simplified drawing.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def pixmap(machine: str, fleet: str, size: int, ratio: float = 1.0, frame: int | None = None):
    from PySide6 import QtCore, QtGui

    pixels = max(1, round(size * ratio))
    image = QtGui.QPixmap(pixels, pixels)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    drawing = mark(machine, fleet, size, frame)
    k, small, working = drawing.scale, size <= SMALL_MAX, frame is not None
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.scale(pixels / 32.0, pixels / 32.0)
    halo = QtGui.QColor.fromRgbF(*HALO_RGBA)

    def pen(colour, width):
        p = QtGui.QPen(colour, width)
        p.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        return p

    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for item in drawing.items:  # the outline under everything
        painter.setOpacity(style(item, working)[2])
        if isinstance(item, Line):
            painter.setPen(pen(halo, item.width + HALO_EXTRA * k))
            painter.drawLine(QtCore.QPointF(item.x1, item.y1), QtCore.QPointF(item.x2, item.y2))
        elif isinstance(item, Dot):
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QtCore.QPointF(item.x, item.y), item.r + DOT_HALO * k, item.r + DOT_HALO * k)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for item in drawing.items:
        colour, hollow, opacity = style(item, working)
        colour = QtGui.QColor(colour)
        painter.setOpacity(opacity)
        if isinstance(item, Line):
            p = pen(colour, item.width)
            if item.state == "none" and not working:
                painter.setOpacity(0.6 if small else 0.75)
                if not small:
                    p.setDashPattern([2 * k / item.width, 2.2 * k / item.width])
            painter.setPen(p)
            painter.drawLine(QtCore.QPointF(item.x1, item.y1), QtCore.QPointF(item.x2, item.y2))
        elif isinstance(item, Dot):
            if hollow:
                painter.setPen(pen(colour, RING_WIDTH * k))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                r = item.r - 0.5 * k
            else:
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(colour)
                r = item.r
            painter.drawEllipse(QtCore.QPointF(item.x, item.y), r, r)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def icon(machine: str, fleet: str, frame: int | None = None):
    """One QIcon with every size drawn for its size (simplified at tray sizes); `frame` draws one
    step of the working animation."""
    from PySide6 import QtGui

    result = QtGui.QIcon()
    for size in ICON_SIZES:
        result.addPixmap(pixmap(machine, fleet, size, frame=frame))
    return result
