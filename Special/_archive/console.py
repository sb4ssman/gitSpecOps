"""Archive runs drawn as station run screens, for a person at a console.

Why:          update-archive and manage-archives run over many repositories; at a console that
              is a run screen (Sb4ssport station script design): one step line per repository,
              a Summary and one result notice. Reports, JSON and redirected output keep their
              own formats; this is only the human view of the same result.
Reads:        an update or archive result already produced; the progress text while it runs.
May change:   nothing.
Results:      text on stdout.
Layer:        Special (presentation of this machine's archive operations).
Status:       working

Every name and detail passes through the same masking as the reports (`conceal`).
"""
from __future__ import annotations

import re

from Basic._station import clean, line, notice, row, say, section, step_line, summary, width
from Special._runtime.output import conceal


def repo_status(text: str, *, scan_only: bool = False) -> tuple[str, str]:
    """A repository's result as a step status word and a short detail."""
    text = text or ""
    if text == "updated":
        return "changed", "fast-forwarded"
    if text in ("already current", "cloned", "fixed", "renamed"):
        return ("ok", text) if text == "already current" else ("changed", text)
    if text.startswith("eligible:"):
        return ("ok", "can be updated") if scan_only else ("ok", text.removeprefix("eligible:").strip())
    if text.startswith("skip:"):
        return "skipped", text.removeprefix("skip:").strip()
    if text.startswith("failed:"):
        return "FAILED", text.removeprefix("failed:").strip()
    return "ok", text


class Working:
    """While a run works: one line, rewritten in place, naming the repository being worked on."""

    NAME = re.compile(r"^\s*\[(?:PULL|SKIP|CLONE|ORIGIN|RENAME|PUSH)\]\s+(?P<name>[^:]+?)(?:\s+-\s.*|:.*)?$")

    def __init__(self, protected=()):
        self.protected, self.shown = protected, False

    def __call__(self, text: str) -> None:
        match = self.NAME.match(str(text))
        if not match:
            return
        name = clean(conceal(match["name"], self.protected))
        message = f"  working on {name}"[: width()]
        print("\r" + message.ljust(width()), end="", flush=True)
        self.shown = True

    def clear(self) -> None:
        if self.shown:
            print("\r" + " " * width() + "\r", end="", flush=True)
            self.shown = False


def show_update(result) -> None:
    """An update-archive result (UpdateResult) as steps per repository, a Summary and a notice."""
    protected = result.protected
    scan_only = result.mode == "scan-only"
    counts = {"changed": 0, "ok": 0, "skipped": 0, "FAILED": 0}
    for report in result.reports:
        section(conceal(report.root, protected))
        repos = report.repos
        if not repos:
            line("No folders here.", "detail")
        for index, repo in enumerate(repos, 1):
            status, detail = repo_status(repo.result or repo.action, scan_only=scan_only)
            counts[status] += 1
            step_line(index, len(repos), conceal(repo.name, protected), status,
                      float(getattr(repo, "elapsed_seconds", 0) or 0), conceal(detail, protected))
    facts = ([f"{counts['ok']} can be updated" if scan_only else f"{counts['changed']} updated",
              f"{counts['ok']} already current" if not scan_only else "",
              f"{counts['skipped']} skipped (local changes, no approved origin, or not a repository)"
              if counts["skipped"] else "",
              f"{counts['FAILED']} failed" if counts["FAILED"] else ""]
             + [f"{artifact['kind']}: {artifact['path']}" for artifact in result.record()["artifacts"]])
    summary(facts)
    from Special._archive.update_operation import explain_error
    _result_notice(result.exit_code, bool(result.errors), scan_only,
                   [explain_error(error) for error in result.errors])


def show_refresh(result, *, explain=None) -> None:
    """A manage-archives refresh (ArchiveResult) as one section per archive."""
    record = result.record()
    counts = {"changed": 0, "ok": 0, "skipped": 0, "FAILED": 0}
    for item in record["archives"]:
        section(f"{item['root']}  ({item['operation']})")
        payload = item.get("result") or {}
        if payload.get("error"):
            line(payload["error"], "error")
        if payload.get("security_notice"):
            line(payload["security_notice"], "warning")
        repos = [repo for root in payload.get("roots", []) for repo in root["scan"]["repos"]]
        for index, repo in enumerate(repos, 1):
            status, detail = repo_status(repo.get("result") or repo["action"], scan_only=result.scan_only)
            counts[status] += 1
            step_line(index, len(repos), repo["name"], status, float(repo.get("elapsed_seconds") or 0), detail)
        for name, count in (payload.get("applied") or {}).items():
            row(name.replace("_", " ").capitalize(), str(count), "warning" if count else "text")
            counts["changed"] += count
        for issue in payload.get("issues", []):
            line(f"{issue['repo']}: {issue['action']}: {issue['detail']}", "warning")
            counts["skipped"] += 1
        for published in payload.get("publication", []):
            row(published["folder"], published["message"])
    summary([f"{len(record['archives'])} archive{'s' if len(record['archives']) != 1 else ''}",
             f"{counts['changed']} changed" if counts["changed"] else "",
             f"{counts['ok']} current" if counts["ok"] else "",
             f"{counts['skipped']} skipped or needing attention" if counts["skipped"] else "",
             f"{counts['FAILED']} failed" if counts["FAILED"] else ""]
            + [f"{artifact['kind']}: {artifact['path']}" for artifact in record["artifacts"]])
    _result_notice(result.exit_code, bool(result.errors), result.scan_only,
                   [explain(code) if explain else code for code in result.errors])


def _result_notice(exit_code: int, errors: bool, scan_only: bool, messages) -> None:
    for message in messages:
        line(message, "error")
    if exit_code == 0:
        notice("Finished", "Checked; nothing was changed." if scan_only else
               "Every archive is as current as it can be.", "success")
    elif errors:
        notice("Could not complete this run", "Some steps may have completed. Review the lines above "
               "before running it again.", "error")
    else:
        notice("Finished with problems", "Some repositories failed; the rest are done. Review the "
               "FAILED lines, then run it again.", "warning")
    say()
