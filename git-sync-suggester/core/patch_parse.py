"""Reading `git diff --binary` output: which files a patch touches, and what it adds.

Shared by preview (what would a restore change?) and secret screening (what content is new?).
It imports nothing from the snapshot modules on purpose: capture screens its own output with it,
so a dependency back onto the store or preview would be circular.

The parser tracks hunk line counts rather than pattern-matching lines, because patch *content* can
look like patch *structure*: removing a SQL line that reads `-- comment` produces a line reading
`--- comment`, and a naive reader would take it for a file header.
"""
from __future__ import annotations

import re

HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
MODE_LINE = re.compile(r"^(?:new file mode|deleted file mode|new mode|old mode) (\d{6})$")
INDEX_LINE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+(?: (\d{6}))?$")
# A symlink restored from another machine's bundle could point anywhere, and `git apply` refuses
# writes beyond one only when it notices; a submodule entry carries no content at all. The first
# slice refuses both rather than restoring something that is either unsafe or empty.
UNSUPPORTED_MODES = {"120000": "symbolic link", "160000": "submodule"}
C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


class PatchUnreadable(Exception):
    """A patch that cannot be interpreted, so it can be neither previewed nor screened."""


def unquote_c(text: str) -> str:
    """Decode Git's C-style quoted path (`core.quotePath`). Unquoted text is returned as-is."""
    if not (len(text) >= 2 and text.startswith('"') and text.endswith('"')):
        return text
    body, out, index = text[1:-1], bytearray(), 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        if index + 1 >= len(body):
            raise ValueError("dangling escape in quoted path")
        following = body[index + 1]
        if following in "01234567":
            digits = body[index + 1:index + 4]
            if len(digits) != 3 or any(d not in "01234567" for d in digits):
                raise ValueError("bad octal escape in quoted path")
            out.append(int(digits, 8))
            index += 4
        elif following in C_ESCAPES:
            out.append(C_ESCAPES[following])
            index += 2
        else:
            raise ValueError("unknown escape in quoted path")
    return out.decode("utf-8")


def _header_paths(rest: str):
    """`(old, new)` from `diff --git a/X b/Y`, or None when the header alone is ambiguous."""
    try:
        if rest.startswith('"'):
            match = QUOTED.match(rest)
            if not match or rest[match.end():match.end() + 1] != " ":
                return None
            first, second = unquote_c(match.group()), unquote_c(rest[match.end() + 1:])
        elif rest.endswith('"'):
            split = rest.rfind(' "')
            if split < 0:
                return None
            first, second = rest[:split], unquote_c(rest[split + 1:])
        else:
            # Unquoted names may contain spaces, so only the identical-name form is unambiguous:
            # "a/P b/P" has length 2L+5.
            if (len(rest) - 5) % 2:
                return None
            size = (len(rest) - 5) // 2
            first, second = rest[:2 + size], rest[3 + size:]
            if rest[2 + size] != " " or first[2:] != second[2:]:
                return None
    except ValueError:
        return None
    if not first.startswith("a/") or not second.startswith("b/"):
        return None
    return first[2:], second[2:]


def _file_header_path(value: str, prefix: str):
    # Git appends a tab to ---/+++ names containing spaces, for the benefit of GNU patch.
    value = value[:-1] if value.endswith("\t") else value
    try:
        value = unquote_c(value)
    except ValueError as exc:
        raise PatchUnreadable("unreadable quoted path in patch") from exc
    if value == "/dev/null":
        return None
    if not value.startswith(prefix):
        raise PatchUnreadable("unexpected path prefix in patch")
    return value[len(prefix):]


def parse_patch(text: str) -> list[dict]:
    """One entry per file section.

    Keys: `path`, `old`, `new`, `change` (modified/added/deleted/renamed/copied), `binary`,
    `binary_content` (False when Git reported a binary change but emitted no data),
    `unsupported` (a symlink or submodule label, else ""), and `added` -- the lines this section
    adds, which is the only content a snapshot introduces beyond the committed base.
    """
    entries: list[dict] = []
    current = None
    state, old_left, new_left = "header", 0, 0
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if state == "hunk":
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            marker = line[:1]
            if marker not in (" ", "+", "-", ""):
                raise PatchUnreadable("malformed hunk in patch")
            if marker in (" ", ""):
                old_left, new_left = old_left - 1, new_left - 1
            elif marker == "-":
                old_left -= 1
            else:
                new_left -= 1
                current["added"].append(line[1:])
            if old_left < 0 or new_left < 0:
                raise PatchUnreadable("hunk longer than its header declares")
            if old_left == 0 and new_left == 0:
                state = "header"
            continue
        if line.startswith("diff --git "):
            paths = _header_paths(line[len("diff --git "):]) or (None, None)
            current = {"old": paths[0], "new": paths[1], "change": "modified",
                       "binary": False, "binary_content": True, "unsupported": "", "added": []}
            entries.append(current)
            state = "header"
            continue
        if state == "binary":
            continue  # base85 data lines cannot contain a space, so cannot fake a header
        if current is None:
            if line.strip():
                raise PatchUnreadable("patch content outside a file section")
            continue
        mode = MODE_LINE.match(line) or INDEX_LINE.match(line)
        if mode and mode.group(1) in UNSUPPORTED_MODES:
            current["unsupported"] = UNSUPPORTED_MODES[mode.group(1)]
        if line.startswith("new file mode"):
            current["change"] = "added"
        elif line.startswith("deleted file mode"):
            current["change"] = "deleted"
        elif line.startswith(("rename from ", "copy from ")):
            current["change"] = "renamed" if line.startswith("rename") else "copied"
            try:
                current["old"] = unquote_c(line.split(" from ", 1)[1])
            except ValueError as exc:
                raise PatchUnreadable("unreadable quoted path in patch") from exc
        elif line.startswith(("rename to ", "copy to ")):
            try:
                current["new"] = unquote_c(line.split(" to ", 1)[1])
            except ValueError as exc:
                raise PatchUnreadable("unreadable quoted path in patch") from exc
        elif line.startswith("--- "):
            current["old"] = _file_header_path(line[4:], "a/")
        elif line.startswith("+++ "):
            current["new"] = _file_header_path(line[4:], "b/")
        elif line == "GIT binary patch":
            current["binary"] = True
            state = "binary"
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            # Git knew the file changed but emitted no content: nothing here can restore it.
            current["binary"], current["binary_content"] = True, False
        elif line.startswith("@@"):
            match = HUNK.match(line)
            if not match:
                raise PatchUnreadable("malformed hunk header in patch")
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_left = int(match.group(2)) if match.group(2) is not None else 1
            state = "hunk" if (old_left or new_left) else "header"
    if state == "hunk":
        raise PatchUnreadable("patch is truncated inside a hunk")
    for entry in entries:
        if entry["change"] == "deleted" or entry["new"] is None:
            entry["path"] = entry["old"]
        else:
            entry["path"] = entry["new"]
    return entries
