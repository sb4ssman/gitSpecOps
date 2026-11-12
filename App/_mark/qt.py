"""The gitSpecOps mark painted with Qt: the tray icon now, the Qt window later.

Why:          Qt's own SVG reader supports only part of SVG, and the tray needs crisp pixels at
              each size, so the mark is painted directly from the shared primitives.
Reads:        two states.
May change:   nothing.
Results:      a QPixmap at one size, or a QIcon holding every tray and window size.
Layer:        App: presence and presentation (App alone may import PySide6).
Status:       working
"""
from __future__ import annotations

from App._mark.geometry import (COLOURS, DOT_HALO, HALO_EXTRA, HALO_RGBA, HOLLOW, RING_WIDTH,
                                SMALL_MAX, Dot, Line, mark)

#: Sizes put into one icon; sizes up to 24 px use the simplified drawing.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def pixmap(machine: str, fleet: str, size: int, ratio: float = 1.0):
    from PySide6 import QtCore, QtGui

    pixels = max(1, round(size * ratio))
    image = QtGui.QPixmap(pixels, pixels)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    drawing = mark(machine, fleet, size)
    k, small = drawing.scale, size <= SMALL_MAX
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
        if isinstance(item, Line):
            painter.setPen(pen(halo, item.width + HALO_EXTRA * k))
            painter.drawLine(QtCore.QPointF(item.x1, item.y1), QtCore.QPointF(item.x2, item.y2))
        elif isinstance(item, Dot):
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QtCore.QPointF(item.x, item.y), item.r + DOT_HALO * k, item.r + DOT_HALO * k)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for item in drawing.items:
        colour = QtGui.QColor(COLOURS[item.state])
        if isinstance(item, Line):
            p = pen(colour, item.width)
            painter.setOpacity(1.0)
            if item.state == "none":
                painter.setOpacity(0.6 if small else 0.75)
                if not small:
                    p.setDashPattern([2 * k / item.width, 2.2 * k / item.width])
            painter.setPen(p)
            painter.drawLine(QtCore.QPointF(item.x1, item.y1), QtCore.QPointF(item.x2, item.y2))
            painter.setOpacity(1.0)
        elif isinstance(item, Dot):
            if item.state in HOLLOW:
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


def _faded(image, opacity: float):
    from PySide6 import QtCore, QtGui

    faded = QtGui.QPixmap(image.size())
    faded.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, image)
    painter.end()
    return faded


def icon(machine: str, fleet: str, opacity: float = 1.0):
    """One QIcon with every size drawn for its size (simplified at tray sizes). A lower opacity
    gives the dimmed frame the tray alternates with while it is working."""
    from PySide6 import QtGui

    result = QtGui.QIcon()
    for size in ICON_SIZES:
        image = pixmap(machine, fleet, size)
        result.addPixmap(image if opacity >= 1.0 else _faded(image, opacity))
    return result
