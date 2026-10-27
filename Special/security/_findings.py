"""Scan records and private report output. No repository mutation or network access."""
from __future__ import annotations

import json
import re
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from Basic._objects import git_output


@dataclass(frozen=True)
class Finding:
    check: str
    classification: str
    value: str
    where: str
    object_id: str = ""
    line: int = 0


def mask(value: str) -> str:
    return value[:2] + "***" + value[-2:] if len(value) > 5 else "***"


def linked(path: Path) -> bool:
    """Includes Windows junctions/reparse points on Python 3.11 as well as symlinks."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) &
                                             getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


@dataclass
class Report:
    repository: str
    material: str
    refs: dict = field(default_factory=dict)
    policy: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    files: int = 0
    commits: int = 0
    archives: int = 0
    checks: tuple = ("credential-shapes", "personal-shapes", "identity", "leak-description")
    private_values: tuple = field(default=(), repr=False)

    @property
    def actionable(self):
        return [item for item in self.findings if item.classification != "quiet"]

    @property
    def exit_code(self):
        return 2 if self.gaps else (1 if self.actionable else 0)

    def gap(self, where: str, reason: str):
        entry = {"where": where, "reason": reason}
        if entry not in self.gaps:
            self.gaps.append(entry)

    def record(self, *, redacted=True):
        result = asdict(self)
        private_values = result.pop("private_values")
        if redacted:
            # Values also occur in filenames, ref names and the repository path.
            values = sorted({value for value in [*private_values, *(item.value for item in self.findings)] if value}, key=len, reverse=True)
            def conceal(value):
                if isinstance(value, str):
                    for private in values:
                        value = re.sub(re.escape(private), lambda match: mask(match[0]), value, flags=re.I)
                    return value
                if isinstance(value, list):
                    return [conceal(item) for item in value]
                if isinstance(value, dict):
                    return {conceal(key): conceal(item) for key, item in value.items()}
                return value
            result = conceal(result)
        result.update(schema_version=1, coverage="incomplete" if self.gaps else "complete-for-selected-checks",
                      result="review-findings" if self.actionable else "no-actionable-findings",
                      scope_note=(("Indexed and non-ignored untracked working-tree files; staged-only bytes excluded. " if self.material == "tree" else
                                   "All selected local refs, including private refs, and HEAD; excludes reflogs/unreachable objects. ") +
                                  "No fetch, remote caches, forks, LFS payloads, image pixels or security clearance; offline candidate checks only."),
                      external_secret_scanner="not-run")
        return result

    def summary(self):
        record = self.record()
        lines = [f"{Path(record['repository']).name}: {self.material}; {self.files} file version(s), {self.commits} commit(s)",
                 "Checks: " + ", ".join(self.checks) + "; external secret scanner: not run",
                 "Policy: " + json.dumps(self.policy, sort_keys=True),
                 f"{len(self.actionable)} finding(s) to review; {len(self.findings) - len(self.actionable)} quiet note(s); {len(self.gaps)} coverage gap(s)"]
        for item in [item for item in record["findings"] if item["classification"] != "quiet"][:30]:
            lines.append(f"  {item['classification']}: {item['check']} at {item['where']}: {item['value']}")
        for entry in record["gaps"][:20]:
            lines.append(f"  NOT INSPECTED: {entry['where']}: {entry['reason']}")
        if len(self.actionable) > 30 or len(self.gaps) > 20:
            lines.append("  More entries are in the full report.")
        return "\n".join(lines)


def write_report(destination: Path, report: Report):
    """Exclusive-create a full report only in a positively verified ignored Git location."""
    destination = Path(destination).expanduser().absolute()
    if ".." in destination.parts:
        raise ValueError("report paths must not contain parent traversal")
    for part in (destination, *destination.parents):
        if linked(part):
            raise ValueError("report paths must not traverse links")
    ancestor = destination.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    top = Path(git_output(ancestor, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    relative = destination.relative_to(top).as_posix()
    if git_output(top, ["ls-files", "--cached", "--", relative]).strip():
        raise ValueError("a private report destination must not be tracked")
    from Basic._run import run_git
    ignored = run_git(top, ["check-ignore", "-q", "--no-index", "--", relative])
    if ignored.returncode != 0:
        raise ValueError("report destination must be positively verified as Git-ignored")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report.record(redacted=False), stream, indent=2, ensure_ascii=True)
        stream.write("\n")
