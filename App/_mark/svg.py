"""The gitSpecOps mark as SVG: the web view's favicon and header, and exported files.

Why:          the browser shows the same mark the tray shows, drawn from the same primitives.
Reads:        two states, a pixel size, and whether the app is working.
May change:   nothing.
Results:      a standalone SVG document; the bytes and status for the /v1/mark.svg route.
Layer:        App: presence and presentation.
Status:       working

Plain SVG only (lines, circles, opacity, dashes): no masks or nested documents, so simple SVG
readers such as Qt's can draw it too. The working version adds a small CSS animation inside the
document (colour flowing from the outer dots to the hub, as in the tray); browsers run it in an
<img>, and readers without CSS show it fully lit.
"""
from __future__ import annotations

from App._mark.geometry import (DARK_OPACITY, DOT_HALO, FRAME_MS, FRAMES, HALO_EXTRA, HALO_RGBA,
                                RING_WIDTH, SMALL_MAX, STATES, Dot, Line, mark, style)

HALO = "rgba({},{},{},{})".format(*HALO_RGBA)
SIZES = range(16, 513)
#: The frame in which each part lights up (frame 0 is the dark one).
STEP = {part: next(i for i, lit in enumerate(FRAMES) if part in lit) for part in ("node", "rim", "spoke", "hub")}


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _animation() -> str:
    cycle = FRAME_MS * len(FRAMES) / 1000
    rules = []
    for part, step in STEP.items():
        start = 100 * step / len(FRAMES)
        rules.append(f"@keyframes w-{part}{{0%,{start - 0.01:.2f}%{{opacity:{DARK_OPACITY}}}{start:.2f}%,100%{{opacity:1}}}}"
                     f".w-{part}{{animation:w-{part} {cycle:.2f}s infinite}}")
    return "<style>" + "".join(rules) + "@media(prefers-reduced-motion:reduce){*{animation:none!important}}</style>"


def svg(machine: str, fleet: str, size: int = 32, working: bool = False) -> str:
    drawing = mark(machine, fleet, size)
    k, small = drawing.scale, size <= SMALL_MAX
    halo, main = [], []
    for item in drawing.items:
        colour, hollow, _opacity = style(item, working)
        cls = f' class="w-{item.part}"' if working else ""
        if isinstance(item, Line):
            ends = f'x1="{_n(item.x1)}" y1="{_n(item.y1)}" x2="{_n(item.x2)}" y2="{_n(item.y2)}"'
            halo.append(f'<line {ends}{cls} stroke="{HALO}" stroke-width="{_n(item.width + HALO_EXTRA * k)}" stroke-linecap="round"/>')
            absent = ""
            if item.state == "none" and not working:
                absent = (' opacity=".6"' if small else
                          f' stroke-dasharray="{_n(2 * k)} {_n(2.2 * k)}" opacity=".75"')
            main.append(f'<line {ends}{cls} stroke="{colour}" stroke-width="{_n(item.width)}" stroke-linecap="round"{absent}/>')
        elif isinstance(item, Dot):
            centre = f'cx="{_n(item.x)}" cy="{_n(item.y)}"'
            halo.append(f'<circle {centre}{cls} r="{_n(item.r + DOT_HALO * k)}" fill="{HALO}"/>')
            if hollow:
                main.append(f'<circle {centre}{cls} r="{_n(item.r - 0.5 * k)}" fill="none" stroke="{colour}" '
                            f'stroke-width="{_n(RING_WIDTH * k)}"/>')
            else:
                main.append(f'<circle {centre}{cls} r="{_n(item.r)}" fill="{colour}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}" height="{size}">'
            + (_animation() if working else "") + "".join(halo) + "".join(main) + "</svg>")


def mark_response(query: dict) -> tuple[int, bytes, str]:
    """The /v1/mark.svg route: ?machine=<state>&fleet=<state>&size=<16..512>[&working=1].
    Anything else is refused; the route reads no fleet data, so it reveals nothing."""
    try:
        machine = (query.get("machine") or ["starting"])[0]
        fleet = (query.get("fleet") or ["none"])[0]
        size = int((query.get("size") or ["32"])[0])
        working = (query.get("working") or ["0"])[0]
        if machine not in STATES or fleet not in STATES or size not in SIZES or working not in ("0", "1"):
            raise ValueError
    except ValueError:
        return 400, b"unknown mark", "text/plain; charset=utf-8"
    return 200, svg(machine, fleet, size, working == "1").encode(), "image/svg+xml"
