"""The gitSpecOps mark, "hub and ring", as drawing primitives: one source for every face.

Why:          the tray, the web view and the Qt window show the same mark with the same meaning.
              The hub is this machine; five nodes with their ring and spokes are the fleet. Each
              part takes its own state, so two independent signals fit in a 16 px tray icon.
Reads:        two states.
May change:   nothing.
Results:      lines and dots on a 32-unit square, zoomed so the mark fills it.
Layer:        App: presence and presentation.
Status:       working

Pure Python: the SVG writer (App/_mark/svg.py) and the Qt painter (App/_mark/qt.py) only
translate these primitives. Designed and compared in the org's private icon studio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

#: Every state a part can show. "none": the part does not apply yet (no fleet joined).
STATES = ("starting", "ok", "attention", "error", "none")
COLOURS = {"starting": "#8b929a", "ok": "#2ea043", "attention": "#d4a017", "error": "#e5534b",
           "none": "#8b929a"}
#: Hollow parts draw as rings: not known yet, or not applicable.
HOLLOW = frozenset({"starting", "none"})
#: A thin dark outline under every part, so the mark holds up on light and dark taskbars.
HALO_RGBA = (0, 0, 0, 0.42)
HALO_EXTRA = 1.6      # added to a line's width
DOT_HALO = 0.8        # added to a dot's radius
RING_WIDTH = 1.3      # a hollow dot's ring
#: Pixel sizes at or under this use the simplified drawing: thicker lines, larger nodes.
SMALL_MAX = 24
CANVAS = 32.0
RANK = {"none": 0, "ok": 0, "starting": 1, "attention": 2, "error": 3}


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    state: str


@dataclass(frozen=True)
class Dot:
    x: float
    y: float
    r: float
    state: str


@dataclass(frozen=True)
class Mark:
    """Primitives already zoomed; `scale` multiplies the fixed widths above."""
    items: tuple
    scale: float


def check_state(state: str) -> str:
    if state not in STATES:
        raise ValueError(f"unknown mark state: {state!r}")
    return state


def worst(*states: str) -> str:
    return max(states, key=lambda s: RANK[s])


def _trim(a, ra, b, rb):
    """The segment from a to b, shortened to stop at the edge of each end's dot, so a hollow
    dot's ring stays empty inside without any masking."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    ux, uy = dx / d, dy / d
    return a[0] + ux * ra, a[1] + uy * ra, b[0] - ux * rb, b[1] - uy * rb


def _raw(machine: str, fleet: str, small: bool) -> list:
    width, node, hub = (1.9, 2.7, 5.0) if small else (1.5, 2.3, 4.6)
    c, radius = 16.0, 11.8
    nodes = [(c + radius * math.cos(math.radians(-90 + 72 * k)),
              c + radius * math.sin(math.radians(-90 + 72 * k))) for k in range(5)]
    items = [Line(*_trim(nodes[k], node, nodes[(k + 1) % 5], node), width, fleet) for k in range(5)]
    items += [Line(*_trim((c, c), hub, p, node), width, fleet) for p in nodes]
    items += [Dot(x, y, node, fleet) for x, y in nodes]
    items.append(Dot(c, c, hub, machine))
    return items


@lru_cache(maxsize=4)
def _fit(small: bool) -> tuple[float, float, float]:
    """(x0, y0, scale) that makes the mark, outline included, fill the square. The geometry does
    not depend on the states, so every state shares one zoom: nothing jumps when colours change."""
    xs, ys = [], []
    for item in _raw("ok", "ok", small):
        if isinstance(item, Line):
            pad = (item.width + HALO_EXTRA) / 2
            xs += [item.x1 - pad, item.x1 + pad, item.x2 - pad, item.x2 + pad]
            ys += [item.y1 - pad, item.y1 + pad, item.y2 - pad, item.y2 + pad]
        else:
            pad = item.r + DOT_HALO
            xs += [item.x - pad, item.x + pad]
            ys += [item.y - pad, item.y + pad]
    margin = 0.25
    side = max(max(xs) - min(xs), max(ys) - min(ys)) + 2 * margin
    x0 = (min(xs) + max(xs)) / 2 - side / 2
    y0 = (min(ys) + max(ys)) / 2 - side / 2
    return x0, y0, CANVAS / side


def mark(machine: str, fleet: str, size: int = 32) -> Mark:
    """The mark for one pair of states at one pixel size, on the 32-unit square."""
    check_state(machine)
    check_state(fleet)
    small = size <= SMALL_MAX
    x0, y0, k = _fit(small)
    items = []
    for item in _raw(machine, fleet, small):
        if isinstance(item, Line):
            items.append(Line((item.x1 - x0) * k, (item.y1 - y0) * k, (item.x2 - x0) * k,
                              (item.y2 - y0) * k, item.width * k, item.state))
        else:
            items.append(Dot((item.x - x0) * k, (item.y - y0) * k, item.r * k, item.state))
    return Mark(tuple(items), k)
