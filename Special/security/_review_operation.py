"""Headless preview/approve/save or revoke one private, content-bound example review.

review_finding reads an explicit full report and selected profile. Preview performs no writes;
apply requires the exact current plan id. Saved reasons/evidence remain in private operational
state. It never edits settings, source/history, scanner rules, logs or shared fleet records.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from Basic._run import CommandFailed
from Special._settings import SETTINGS_NAME, SettingsError, resolve_settings, select_home
from Special._runtime.files import excluded
from Special.security._checks import inspect
from Special.security._findings import Finding, Report
from Special.security._me import load_policy, policy_revision
from Special.security._private_files import read_private_json, write_private_json
from Special.security import _reviews


@dataclass
class ReviewResult:
    """Safe presentation; no raw finding values, reason text or evidence keys."""
    status: str
    message: str
    plan_id: str | None = None
    review_id: str | None = None
    saved: bool = False
    scope: dict = field(default_factory=dict, repr=False)
    artifacts: list = field(default_factory=list, repr=False)

    def record(self):
        return {"schema_version": 1, "operation": "review-finding", "status": self.status,
                "message": self.message, "plan_id": self.plan_id, "review_id": self.review_id,
                "saved": self.saved, "scope": self.scope, "artifacts": self.artifacts}


def _report(raw, policy):
    if (not isinstance(raw, dict) or raw.get("schema_version") != 2 or
            not isinstance(raw.get("repository"), str) or not Path(raw["repository"]).is_absolute() or
            raw.get("material") not in ("tree", "index", "history", "outgoing", "proposed") or
            not isinstance(raw.get("scan_id"), str) or not re.fullmatch(r"scan-[0-9a-f]{32}", raw["scan_id"]) or
            not isinstance(raw.get("findings"), list)):
        raise ValueError("a current full private scan report is required")
    report = Report(raw["repository"], raw["material"], scan_id=raw["scan_id"],
                    private_values=tuple(value for values in policy.identities.values() for value in values))
    for number, row in enumerate(raw["findings"], 1):
        if not isinstance(row, dict) or row.get("finding_id") != f"finding-{number:06d}":
            raise ValueError("invalid report finding")
        fields = {name: row.get(name, "" if name != "line" else 0) for name in
                  ("check", "classification", "value", "where", "object_id", "line", "content_id")}
        if (any(not isinstance(fields[name], str) for name in fields if name != "line") or
                type(fields["line"]) is not int or fields["line"] < 0):
            raise ValueError("invalid report finding fields")
        fields["context_kind"], fields["occurrence"] = row.get("context_kind"), row.get("occurrence")
        if not isinstance(fields["context_kind"], str) or type(fields["occurrence"]) is not int or fields["occurrence"] < 1:
            raise ValueError("current context/occurrence bindings are required")
        report.findings.append(Finding(**fields))
    return report


def review_finding(source, finding_id=None, reason="", *, home=None, legacy_policy=False,
                   apply=False, approve=None, revoke=None):
    """Return a masked plan; save only after exact approval. A report is evidence, not clearance."""
    try:
        if (not isinstance(reason, str) or not reason.strip() or len(reason) > 2000 or
                bool(finding_id) == bool(revoke) or (approve is not None and not apply)):
            raise ValueError("select one finding or revocation and supply a private reason")
        selected = select_home(home, component="security")[0]
        try:
            (selected / SETTINGS_NAME).lstat()
            common = True
        except FileNotFoundError:
            common = False
        if legacy_policy and common:
            return ReviewResult("incomplete", "Explicit legacy mode cannot bypass common settings; no report was read.")
        if not legacy_policy:
            preferences = resolve_settings("security", home=selected)
            if excluded(Path(source).expanduser().absolute(), preferences.values["scope"]["exclude_paths"]):
                return ReviewResult("refused", "The requested report is excluded by the selected policy; it was not read.")
        raw = read_private_json(source)
        if not isinstance(raw, dict) or not isinstance(raw.get("repository"), str) or not Path(raw["repository"]).is_absolute():
            raise ValueError("a current full private scan report is required")
        policy = load_policy(Path(raw["repository"]), home=selected, legacy_policy=legacy_policy)
        if policy.gaps:
            return ReviewResult("incomplete", "Review state or policy could not be verified; no decision saved.")
        report = _report(raw, policy)
        folder = _reviews.directory(selected, report.repository)
        if excluded(folder, policy.exclude_paths, contains=True):
            return ReviewResult("refused", "Review storage is excluded by the selected policy; no decision saved.")
        scope = {}
        if revoke:
            if not isinstance(revoke, str) or not _reviews.REVIEW_ID.fullmatch(revoke):
                raise ValueError("invalid review id")
            if revoke not in policy.reviewed_examples.values():
                return ReviewResult("refused", "The selected profile has no active example review with that id.")
            decision = {"decision": "revoke", "review_id": revoke}
        else:
            ids = {f"finding-{index:06d}": item for index, item in enumerate(report.findings, 1)}
            if finding_id not in ids:
                raise ValueError("the requested finding is not in this report")
            finding = ids[finding_id]
            try:
                binding = _reviews.evidence(report.repository, finding)
            except ValueError:
                return ReviewResult("refused", "This finding requires remediation or policy review; example acceptance is unavailable.")
            if any(item.severity == "high" for item in inspect(finding.value, finding.where, policy)):
                return ReviewResult("refused", "A currently prohibited value or strong credential cannot be accepted as an example.")
            public = report.record()["findings"][list(ids).index(finding_id)]
            scope = {key: public[key] for key in ("finding_id", "check", "classification", "severity", "where", "line", "value")}
            existing = policy.reviewed_examples.get(_reviews.digest(binding))
            if existing:
                return ReviewResult("already-reviewed", "This exact finding/content already has an active example review.",
                                    review_id=existing, scope=scope)
            decision = {"decision": "accept-example", "evidence": binding, "source_scan": report.scan_id}
        plan_id = "review-plan-" + _reviews.digest({"source": raw, "home": str(selected), "decision": decision,
                                                     "reason": reason, "policy": policy_revision(policy)})
        if not apply:
            return ReviewResult("planned", "Review plan only; the private reason is not displayed and no decision is saved.",
                                plan_id=plan_id, review_id=revoke, scope=scope)
        if approve != plan_id:
            return ReviewResult("approval-required", "No decision saved: approve this exact current review plan.",
                                plan_id=plan_id, scope=scope)
        # Re-read every ownership/input binding before the one explicit private write.
        if (read_private_json(source) != raw or
                policy_revision(load_policy(Path(report.repository), home=selected, legacy_policy=legacy_policy)) != policy_revision(policy)):
            return ReviewResult("stale", "Report or policy changed; create a new review plan.")
        review_id = revoke or "review-" + uuid4().hex
        record = {"schema_version": 1, "repository": _reviews.repository_scope(report.repository),
                  "requires_settings": isinstance(policy.sources.get("settings"), dict) and policy.sources["settings"].get("configured", False),
                  "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "review_id": review_id, "reason": reason, **decision}
        if len(json.dumps(record, ensure_ascii=True).encode("utf-8")) > 256 * 1024:
            return ReviewResult("refused", "Review evidence exceeds the private record limit; no decision saved.")
        filename = review_id + (".revoke.json" if revoke else ".json")
        path = write_private_json(folder / filename, record)
        report.artifacts.append({"kind": "example review", "path": str(path), "disclosure": "private evidence and reason"})
        return ReviewResult("revoked" if revoke else "accepted", "Private review decision saved; rescan before taking a Git action.",
                            plan_id, review_id, True, scope, report.record()["artifacts"])
    except (CommandFailed, SettingsError, OSError, ValueError, TypeError):
        return ReviewResult("incomplete", "Report, finding, destination or policy could not be verified; no decision saved.")
