"""The gitSpecOps mark as SVG: the web view's favicon and header, and exported files.

Why:          the browser shows the same mark the tray shows, drawn from the same primitives.
Reads:        two states and a pixel size.
May change:   nothing.
Results:      a standalone SVG document; the bytes and status for the /v1/mark.svg route.
Layer:        App: presence and presentation.
Status:       working

Plain SVG only (lines, circles, opacity, dashes): no masks or nested documents, so simple SVG
readers such as Qt's can draw it too.
"""
from __future__ import annotations

from App._mark.geometry import (COLOURS, DOT_HALO, HALO_EXTRA, HALO_RGBA, HOLLOW, RING_WIDTH,
                                SMALL_MAX, STATES, Dot, Line, mark)

HALO = "rgba({},{},{},{})".format(*HALO_RGBA)
SIZES = range(16, 513)


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def svg(machine: str, fleet: str, size: int = 32) -> str:
    drawing = mark(machine, fleet, size)
    k, small = drawing.scale, size <= SMALL_MAX
    halo, main = [], []
    for item in drawing.items:
        colour = COLOURS[item.state]
        if isinstance(item, Line):
            ends = f'x1="{_n(item.x1)}" y1="{_n(item.y1)}" x2="{_n(item.x2)}" y2="{_n(item.y2)}"'
            halo.append(f'<line {ends} stroke="{HALO}" stroke-width="{_n(item.width + HALO_EXTRA * k)}" stroke-linecap="round"/>')
            absent = ""
            if item.state == "none":
                absent = (' opacity=".6"' if small else
                          f' stroke-dasharray="{_n(2 * k)} {_n(2.2 * k)}" opacity=".75"')
            main.append(f'<line {ends} stroke="{colour}" stroke-width="{_n(item.width)}" stroke-linecap="round"{absent}/>')
        elif isinstance(item, Dot):
            centre = f'cx="{_n(item.x)}" cy="{_n(item.y)}"'
            halo.append(f'<circle {centre} r="{_n(item.r + DOT_HALO * k)}" fill="{HALO}"/>')
            if item.state in HOLLOW:
                main.append(f'<circle {centre} r="{_n(item.r - 0.5 * k)}" fill="none" stroke="{colour}" '
                            f'stroke-width="{_n(RING_WIDTH * k)}"/>')
            else:
                main.append(f'<circle {centre} r="{_n(item.r)}" fill="{colour}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}" height="{size}">'
            + "".join(halo) + "".join(main) + "</svg>")


def mark_response(query: dict) -> tuple[int, bytes, str]:
    """The /v1/mark.svg route: ?machine=<state>&fleet=<state>&size=<16..512>. Anything else is
    refused; the route reads no fleet data, so it reveals nothing."""
    try:
        machine = (query.get("machine") or ["starting"])[0]
        fleet = (query.get("fleet") or ["none"])[0]
        size = int((query.get("size") or ["32"])[0])
        if machine not in STATES or fleet not in STATES or size not in SIZES:
            raise ValueError
    except ValueError:
        return 400, b"unknown mark", "text/plain; charset=utf-8"
    return 200, svg(machine, fleet, size).encode(), "image/svg+xml"
