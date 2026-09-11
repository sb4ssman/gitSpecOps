"""Make console output survive a non-UTF-8 stdout. Read-only, stdlib-only, no policy.

Every tool here prints status glyphs (``✓ ✗ ⚠ ✎ ↑ ↓ ↕ ⚑ →``). None of them are encodable in
cp1252, which is what Python picks for a *redirected* stream on a Western Windows install --
so ``check > status.txt``, a launcher writing a log, or any pipe raised ``UnicodeEncodeError``
and killed the command *after* its real work had already succeeded. The interactive console
happens to be fine (Python writes it through a UTF-8 console writer), which is exactly why the
failure hid for so long: it only appeared once someone redirected.

``enable_unicode_output()`` is called at the top of each entry point. It reconfigures the
standard streams to UTF-8 and, if even that is refused, degrades to ``errors="replace"`` so a
glyph becomes ``?`` and the command still finishes. Printing must never be the thing that fails.
"""
from __future__ import annotations

import sys

#: Characters outside cp1252, mapped to a plain-ASCII stand-in for ``ascii_fallback``.
ASCII_EQUIVALENTS = {
    "✓": "OK", "✗": "X", "⚠": "!", "✎": "M", "⚑": "S", "ℹ": "i",
    "↑": "^", "↓": "v", "↕": "^v", "→": "->", "—": "-", "–": "-",
    "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "*",
}


def _reconfigure(stream, encoding: str | None, errors: str) -> bool:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:  # a plain file object, or something already wrapped by a caller
        return False
    try:
        if encoding is None:
            reconfigure(errors=errors)
        else:
            reconfigure(encoding=encoding, errors=errors)
    except (OSError, ValueError, LookupError):
        return False
    return True


def enable_unicode_output() -> bool:
    """Best-effort UTF-8 stdout/stderr. Never raises; returns whether UTF-8 is in play.

    Honors an explicit ``PYTHONIOENCODING`` by only ever *widening* what a stream accepts:
    a stream already carrying a UTF-8 codec is left alone apart from its error handler.
    """
    utf8 = True
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:  # pythonw / a detached GUI process has no standard streams
            continue
        current = (getattr(stream, "encoding", "") or "").lower().replace("-", "_")
        if current in ("utf_8", "utf8"):
            _reconfigure(stream, None, "replace")
            continue
        if not _reconfigure(stream, "utf-8", "replace"):
            # Cannot switch codecs -- keep the stream, but stop it from raising.
            _reconfigure(stream, None, "replace")
            utf8 = False
    return utf8


def ascii_fallback(text: str) -> str:
    """Replace the known glyphs with ASCII. For callers that must not emit any UTF-8 at all."""
    for glyph, plain in ASCII_EQUIVALENTS.items():
        text = text.replace(glyph, plain)
    return text


def main() -> int:
    """Standalone check: print the glyph set the way this terminal would actually receive it."""
    enable_unicode_output()
    print(f"stdout encoding: {getattr(sys.stdout, 'encoding', 'unknown')}")
    line = " ".join(ASCII_EQUIVALENTS)
    print(f"glyphs : {line}")
    print(f"ascii  : {ascii_fallback(line)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
