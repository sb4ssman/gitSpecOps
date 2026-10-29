"""Scan records and private report output. No repository mutation or network access."""
from __future__ import annotations

import json
import re
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from Basic._objects import git_output

STRONG_CREDENTIAL_CHECKS = frozenset({"GitHub token", "AWS access key", "Slack token",
                                     "Google API key", "private key block"})

@dataclass(frozen=True)
class Finding:
    check: str
    classification: str
    value: str = field(repr=False)
    where: str = field(repr=False)
    object_id: str = ""
    line: int = 0

    @property
    def severity(self):
        """One presentation/action classification; high confidence is not live validation."""
        return ("high" if self.classification == "leak" or self.check in STRONG_CREDENTIAL_CHECKS else
                "info" if self.classification == "quiet" else "review")


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
    engines: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list, repr=False)

    @property
    def actionable(self):
        return [item for item in self.findings if item.classification != "quiet"]

    @property
    def exit_code(self):
        return 2 if self.gaps else (1 if self.actionable else 0)

    @property
    def check_status(self):
        """Shared check outcome, not permission to execute an action or publish a repository."""
        if self.gaps:
            return "incomplete"
        if any(item.severity == "high" for item in self.actionable):
            return "blocked"
        return "review-required" if self.actionable else "passed"

    def gap(self, where: str, reason: str):
        entry = {"where": where, "reason": reason}
        if entry not in self.gaps:
            self.gaps.append(entry)

    def record(self, *, redacted=True):
        """Actionable presentation record; ids are report-local, never hashes of secrets.

        Trusted human/report callers may request full values. Choosing that channel does not
        change logs, fleet state or this method's default. No source snippets are returned.
        """
        result = asdict(self)
        private_values = result.pop("private_values")
        for number, (item, finding) in enumerate(zip(result["findings"], self.findings), 1):
            item.update(finding_id=f"finding-{number:06d}",
                        severity=finding.severity,
                        recommendation=("Inspect the referenced outgoing object/commit; a working-tree fix alone does not change outgoing history."
                                        if self.material == "outgoing" and finding.classification != "quiet" else
                                        "Remove the prohibited value from the proposed publication; review history separately."
                                        if finding.classification == "leak" else
                                        "Inspect the referenced location locally; classify the candidate before publishing."))
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
        result.update(schema_version=2, check_status=self.check_status,
                      coverage="incomplete" if self.gaps else "complete-for-selected-checks",
                      result="review-findings" if self.actionable else "no-actionable-findings",
                      scope_note=(("Indexed and non-ignored untracked working-tree files; staged-only bytes excluded. " if self.material == "tree" else
                                   "Changed blob/path versions and commit messages/identities in the exact base..tip range. " if self.material == "outgoing" else
                                   "Named proposed file bytes/paths, message and author/committer; other staged and baseline files excluded. " if self.material == "proposed" else
                                   "All selected local refs, including private refs, and HEAD; excludes reflogs/unreachable objects. ") +
                                  "No fetch, remote caches, forks, LFS payloads, image pixels or security clearance; offline candidate checks only."),
                      external_secret_scanner=("not-run" if not self.engines else
                                               ("incomplete" if any(value != "checked" for value in self.engines.values())
                                                else "checked-selected-engines")))
        return result

    def summary(self):
        return render_record(self.record())


def render_record(record):
    """Render an already masked scan record, including records returned by a hook worker."""
    policy = record["policy"]
    settings = policy.get("sources", {}).get("settings")
    origin = ("legacy-explicit" if settings == "legacy-explicit" else
              "saved" if isinstance(settings, dict) and settings.get("configured") else "built-in")
    actionable = [item for item in record["findings"] if item["classification"] != "quiet"]
    lines = [f"{Path(record['repository']).name}: {record['material']}; {record['files']} file version(s), {record['commits']} commit(s)",
             "Checks: " + ", ".join(record["checks"]) + "; external engines: " +
             (json.dumps(record["engines"], sort_keys=True) if record["engines"] else "none selected"),
             f"Policy: {origin}; {policy.get('identity_values', 0)} identity/protected value(s), "
             f"{policy.get('safe_values', 0)} allowance(s), {policy.get('public_handles', 0)} public handle(s)",
             f"{len(actionable)} finding(s) to review; {len(record['findings']) - len(actionable)} quiet note(s); {len(record['gaps'])} coverage gap(s)"]
    for item in actionable[:30]:
        location = item["where"] + (f":{item['line']}" if item["line"] else "")
        lines.append(f"  {item['finding_id']} [{item['severity']}] {item['classification']}: {item['check']} at {location}: {item['value']}")
        lines.append("    " + item["recommendation"])
    for entry in record["gaps"][:20]:
        lines.append(f"  NOT INSPECTED: {entry['where']}: {entry['reason']}")
    if len(actionable) > 30 or len(record["gaps"]) > 20:
        lines.append("  Use --json for all masked entries; no report file is created by default.")
    for artifact in record["artifacts"]:
        lines.append(f"  Produced {artifact['kind']}: {artifact['path']} ({artifact['disclosure']})")
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
