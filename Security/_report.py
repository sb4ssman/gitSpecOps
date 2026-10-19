"""The text of a history report: masked for the screen, full for the ignored report file."""
from __future__ import annotations

from Security._history import HistoryReport
from Security._patterns import SECRETS, mask


def render(report: HistoryReport, show_values: bool = False) -> tuple[str, int]:
    """The report text and the number of findings."""
    shown = (lambda value: value) if show_values else mask
    lines = [f"Scanned {report.commits} commit(s), {report.blobs} file version(s), "
             f"{report.objects} object(s) reachable from: {', '.join(report.refs)}"]
    findings = 0
    people = report.personal_identities()
    if people:
        lines.append("\nCommit identities (published on every commit page and .patch URL):")
        for person in sorted(people, key=lambda p: -p.commits):
            findings += 1
            lines.append(f"  {shown(person.email)} / {shown(person.name)}: {person.concern} — "
                         f"{person.commits} commit(s), {person.first[:10]} to {person.last[:10]}")
    if show_values:
        # The full report lists every identity, not only the problems: you should see exactly
        # what history says about who wrote it.
        lines.append(f"\nEvery author/committer identity ({len(report.identities)}):")
        for person in sorted(report.identities.values(), key=lambda p: -p.commits):
            lines.append(f"  {person.email} / {person.name}: {person.commits} commit(s) — "
                         + (person.concern or "fine (noreply or the host's own)"))
    secrets = [e for e in report.exposures.values() if e.kind in SECRETS]
    others = [e for e in report.exposures.values() if e.kind not in SECRETS]
    for title, group in (("Secrets — rotate these first; removing them does not un-publish them",
                          secrets), ("Personal data in files, paths or messages", others)):
        if not group:
            continue
        lines.append(f"\n{title}:")
        for exposure in sorted(group, key=lambda e: (e.kind, e.value)):
            findings += 1
            where = []
            if exposure.paths:
                sample = ", ".join(sorted(exposure.paths)[:3])
                more = len(exposure.paths) - 3
                where.append(f"in {len(exposure.paths)} file path(s): {sample}"
                             + (f" (+{more} more)" if more > 0 else ""))
            if exposure.in_paths:
                where.append(f"in {len(exposure.in_paths)} file name(s)")
            if exposure.commits:
                where.append(f"in {len(exposure.commits)} commit message(s)")
            state = "STILL IN CURRENT FILES" if exposure.current else "history only"
            lines.append(f"  {exposure.kind}: {shown(exposure.value)!r} [{state}]")
            lines.extend(f"      {item}" for item in where)
    if report.located_images:
        lines.append("\nImages whose metadata holds a GPS position (where the photo was taken):")
        for path in sorted(report.located_images):
            findings += 1
            lines.append(f"  {path}")
    if report.archives:
        lines.append(f"\nOpened {len(report.archives)} archive(s) and read "
                     f"{sum(report.archives.values())} member(s); a finding inside one is "
                     "listed above as archive!member.")
    if report.uninspected:
        lines.append(f"\nNot inspected ({len(report.uninspected)}) -- not the same as clean:")
        for path, why in sorted(report.uninspected.items())[:20]:
            lines.append(f"  {path}: {why}")
        if len(report.uninspected) > 20:
            lines.append(f"  (+{len(report.uninspected) - 20} more)")
    if not findings:
        lines.append("Nothing found.")
    return "\n".join(lines), findings
