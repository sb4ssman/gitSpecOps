"""Reference for the page: the catalog of operations, and the documents.

Why:          the page shows what needs doing; this says what each operation is and where its
              manual is (the user, 2026-11-17: a Catalog and Docs, as one Reference item).
Reads:        gitso's own command table and manuals, asked as a terminal would
              (`gitso commands --json`, `gitso docs <command>`: source text, no operation runs),
              and this project's Markdown documents.
May change:   nothing.
Results:      a JSON-ready answer for the page.
Layer:        App.
Status:       working

The catalog is the one `gitso commands` prints, grouped by layer. A document is asked for by
its listed id only: no path ever comes from the page.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

from Basic._run import run

ROOT = Path(__file__).resolve().parents[2]
TEXT_LIMIT = 400_000
LAYERS = (("Basic", "Basic: one Git or host operation"),
          ("Special", "Special: this machine, once"),
          ("Elaborate", "Elaborate: across machines, over time"),
          ("App", "App: the tray and this page"),
          ("_build", "Setup and packaging"))
#: The manuals of the tools gitSpecOps drives, and its own home.
LINKS = (("Git reference", "https://git-scm.com/docs"),
         ("GitHub CLI (gh) manual", "https://cli.github.com/manual/"),
         ("Tailscale documentation", "https://tailscale.com/kb"),
         ("gitleaks", "https://github.com/gitleaks/gitleaks"),
         ("gitSpecOps on GitHub", "https://github.com/sb4ssman/gitSpecOps"))
#: A Basic operation is one Git command: its own manual page.
GIT_PAGES = {"status": "git-status", "fetch": "git-fetch", "pull": "git-pull", "clone": "git-clone",
             "commit": "git-commit", "push": "git-push", "reset-keep": "git-reset"}


def _documents() -> dict[str, Path]:
    """The documents by id, in reading order: the README, docs/*.md, the changelog."""
    found = {"README": ROOT / "README.md"}
    for path in sorted((ROOT / "docs").glob("*.md")):
        found[f"docs/{path.stem}"] = path
    found["CHANGELOG"] = ROOT / "CHANGELOG.md"
    return {name: path for name, path in found.items() if path.is_file()}


def _title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return path.stem


def _gitso(*args: str) -> str:
    done = run([sys.executable, str(ROOT / "gitso.py"), *args], timeout=60, cwd=str(ROOT))
    if done.returncode:
        raise ValueError("the catalog could not be read")
    return done.stdout


@lru_cache(maxsize=1)
def _commands() -> tuple:
    """gitso's command table: (command, script, description) records."""
    try:
        return tuple(json.loads(_gitso("commands", "--json"))["commands"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("the catalog could not be read") from exc


def catalog() -> dict:
    layers = []
    for folder, label in LAYERS:
        entries = [{**command, "git": (f"https://git-scm.com/docs/{GIT_PAGES[command['command']]}"
                                       if folder == "Basic" and command["command"] in GIT_PAGES else None)}
                   for command in _commands() if command["script"].split("/", 1)[0] == folder]
        if entries:
            layers.append({"id": folder, "label": label, "commands": entries})
    return {"layers": layers,
            "documents": [{"id": name, "title": _title(path)} for name, path in _documents().items()],
            "links": [{"label": label, "url": url} for label, url in LINKS]}


def reference(payload: dict) -> dict:
    """{} -> the catalog; {"command": name} -> its manual; {"document": id} -> its text."""
    if not isinstance(payload, dict) or not set(payload) <= {"command", "document"} or len(payload) > 1:
        raise ValueError("ask for the catalog, one command or one document")
    if "command" in payload:
        chosen = next((command for command in _commands() if command["command"] == payload["command"]), None)
        if chosen is None:
            raise ValueError("no such command")
        try:
            source = (ROOT / chosen["script"]).read_text(encoding="utf-8-sig")[:TEXT_LIMIT]
        except OSError:
            source = ""
        return {"title": f"gitso {chosen['command']}", "script": chosen["script"],
                "text": _gitso("docs", *chosen["command"].split())[:TEXT_LIMIT], "source": source}
    if "document" in payload:
        path = _documents().get(str(payload["document"]))
        if path is None:
            raise ValueError("no such document")
        return {"title": _title(path), "text": path.read_text(encoding="utf-8-sig")[:TEXT_LIMIT]}
    return catalog()
