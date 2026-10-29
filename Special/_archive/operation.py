"""Headless archive operations and registered refresh: one result/report/log per invocation.

run_archives executes explicit requests; run_refresh selects registered update/sync requests.
Both return masked records without printing. The caller approves mutations; publication is
an exclusive operation and always uses the outgoing-history security gate. Sinks are prepared
before actions. Registration, conversion and scheduling are separate operations.
"""
from __future__ import annotations

import copy
import json
import math
import os
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from Special._archive import sync
from Special._archive.registry import load_registry, save_registry
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES, approved_remote
from Special._archive.update_operation import UpdateRequest, explain_error, run_update
from Special._runtime.files import RuntimeIOError, checked_path, excluded, linked
from Special._runtime.logger import configure_logging
from Special._runtime.output import ReportSink, conceal
from Special._settings import ResolvedSettings, SettingsError, resolve_document
from Special._settings.archives import _key
from Special.security._me import load_policy


ERRORS = {"settings": "Archive settings or selection are invalid; nothing was run.",
          "scope": "Archive scope, mode or remote allowances are invalid; nothing was run.",
          "not_registered": "Requested archive is not registered in the selected profile.",
          "interrupted": "Refresh was interrupted; verify any in-progress repository before retrying.",
          "stale": "Archive state changed after partial operations; later archives were not run.",
          "receipts": "Archive operations finished but receipt saving failed; review partial results.",
          "execution": "Archive execution could not finish; inspect partial results before retrying."}


@dataclass
class ArchiveResult:
    """Safe programmatic result; source settings/protected values remain private backend data."""
    scan_only: bool
    archives: list = field(default_factory=list, repr=False)
    errors: list = field(default_factory=list)
    effects_possible: bool = False
    elapsed_seconds: float = 0.0
    report_path: Path | None = field(default=None, repr=False)
    log_path: Path | None = field(default=None, repr=False)
    settings: ResolvedSettings | None = field(default=None, repr=False)
    protected: tuple = field(default=(), repr=False)

    @property
    def exit_code(self):
        """0 complete, 1 repository issues, 2 incomplete/failed orchestration, 130 interrupted."""
        if "interrupted" in self.errors or any(item["exit_code"] == 130 for item in self.archives):
            return 130
        return 2 if self.errors or any(item["exit_code"] >= 2 for item in self.archives) else int(any(item["exit_code"] for item in self.archives))

    def record(self):
        artifacts = [{"kind": kind, "path": str(path)} for kind, path in
                     (("report", self.report_path), ("operational-log", self.log_path)) if path is not None]
        return conceal({"schema_version": 1, "operation": self.settings.component if self.settings else "archive",
                        "scan_only": self.scan_only,
                        "status": "partial" if self.exit_code and self.effects_possible else "failed" if self.exit_code else "ok",
                        "exit_code": self.exit_code, "effects_possible": self.effects_possible,
                        "archives": self.archives, "errors": self.errors, "artifacts": artifacts,
                        "elapsed_seconds": self.elapsed_seconds}, self.protected)


def error_message(code):
    return ERRORS.get(code, explain_error(code))


def render_result(result, format):
    """Render the same masked record for CLI, GUI and optional aggregate report."""
    record = result.record()
    if format == "json":
        return json.dumps(record, indent=2)
    lines = [f"Archive operation: {record['status']} (exit {record['exit_code']})"]
    for item in record["archives"]:
        lines.append(f"{item['root']}: {item['operation']}; {item['status']} (exit {item['exit_code']})")
        if item.get("result") is not None:
            payload = item["result"]
            if payload.get("error"):
                lines.append("  " + payload["error"])
            if payload.get("security_notice"):
                lines.append("  " + payload["security_notice"])
            for root in payload.get("roots", []):
                for repo in root["scan"]["repos"]:
                    lines.append(f"  {repo['name']}: {repo.get('result') or repo['action']}")
            if "applied" in payload:
                lines.append("  Applied: " + ", ".join(f"{name}={count}" for name, count in payload["applied"].items()))
                for name, entries in payload.get("plan", {}).items():
                    if entries:
                        lines.append(f"  {name}: {len(entries)}")
                        lines.extend("    " + (entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=True))
                                     for entry in entries)
                for issue in payload["issues"]:
                    lines.append(f"  [{issue['action']}] {issue['repo']}: {issue['detail']}")
            for published in payload.get("publication", []):
                lines.append(f"  {published['folder']}: {published['message']}")
                if published.get("security") is not None:
                    lines.append("  Security: " + json.dumps(published["security"], ensure_ascii=True))
    lines.extend("Error: " + error_message(code) for code in result.errors)
    lines.extend(f"{item['kind']}: {item['path']}" for item in record["artifacts"])
    return "\n".join(lines)


def _scope(root, settings):
    checked_path(root)
    if excluded(root, settings.values["scope"]["exclude_paths"], contains=True):
        raise SettingsError("archive scope conflicts with exclusions")
    if root.is_dir() and any(linked(child) for child in root.iterdir()):
        raise SettingsError("linked entries require review")


def _target(root, name):
    if not isinstance(name, str) or not name or name.casefold() in (".", "..", ".git") or any(char in name for char in "/\\:\0\r\n"):
        raise SettingsError("archive action target must be one direct child")
    return checked_path(root / name)


def _uncertain(result, request, scan_only, code):
    """Retain the active scope when a backend cannot return a trustworthy completion record."""
    if request is not None:
        result.effects_possible |= not scan_only
        result.archives.append({"root": request["root"], "operation": request["mode"],
                                "status": "partial" if not scan_only else "failed", "exit_code": code,
                                "effects_possible": not scan_only,
                                "result": {"error": "Operation did not return verified completion; current Git state needs review."}})


def execute_archive(item, settings, before_action, *, scan_only=False, progress=None, approve=None):
    """One headless operation. Approval receives masked data; the parent owns all sinks."""
    root, mode, prefixes = Path(item["root"]), item["mode"], item["approved_remote_prefixes"]
    if mode == "update" and not (item.get("reconcile") or item.get("rename_folders")):
        child = replace(copy.deepcopy(settings), component="archive_update")
        child.values["output"]["mode"], child.values["logging"]["enabled"] = "stdout", False
        def verify():
            before_action()
            _scope(root, settings)
        result = run_update(child, UpdateRequest(roots=(root,), scan_only=scan_only, approved_prefixes=tuple(prefixes)),
                            progress=progress, before_action=verify,
                            approve=None if approve is None else lambda plan: approve("update", plan))
        blocked = any(repo.action == "skip: origin is not approved" for report in result.reports for repo in report.repos)
        return {"exit_code": result.exit_code or int(blocked), "effects_possible": result.effects_possible,
                "result": result.record()}
    if mode == "publish":
        return _publish(item, settings, before_action, scan_only=scan_only, progress=progress, approve=approve)
    detected = sync.detect_plan(root, prefixes, owner_override=item.get("owner_override"))
    issues = list(detected.errors)
    # Provider diagnostics may include raw host errors; programmatic output uses finite reasons.
    for issue in issues:
        issue.detail = "Discovery or scope requires review; inspect provider/Git locally."
    applied = {"pulled": 0, "cloned": 0, "origins_fixed": 0, "renamed": 0}
    effects = False
    failure = None
    try:
        for local in detected.plan.to_pull:
            _target(root, local.folder)
        for ref in detected.plan.to_clone:
            _target(root, ref.name)
            if not isinstance(ref.url, str) or not approved_remote(ref.url, prefixes) or ref.url.startswith("-") or any(char in ref.url for char in "\0\r\n"):
                raise SettingsError("invalid clone source")
        for repair in detected.plan.to_reconcile:
            _target(root, repair.local.folder)
            _target(root, repair.ref.name)
            if not approved_remote(repair.ref.url, prefixes) or any(char in repair.ref.url for char in "\0\r\n"):
                raise SettingsError("invalid repair source")
        if not scan_only:
            preview = conceal(sync.build_report(detected, applied, issues, mode), _protected(settings))
            if approve is None or not approve(mode, preview):
                return {"exit_code": 2, "effects_possible": False, "result": {"error": error_message("approval_required")}}
            for local in detected.plan.to_pull:
                if mode not in ("update", "sync"):
                    break
                before_action()
                _scope(root, settings)
                path = _target(root, local.folder)
                current = sync.inspect_candidate(path, prefixes)
                if not current.eligible or current.origin != local.origin:
                    raise SettingsError("pull scope changed")
                effects = True
                applied["pulled"] += sync.apply_pull(root, replace(detected.plan, to_pull=[local]), issues, emit=progress)
            for ref in detected.plan.to_clone:
                if mode != "sync":
                    break
                before_action()
                _scope(root, settings)
                _target(root, ref.name)
                effects = True
                applied["cloned"] += sync.apply_clone(root, replace(detected.plan, to_clone=[ref]), issues, emit=progress)
            for repair in detected.plan.to_reconcile:
                if not (item.get("reconcile") or item.get("rename_folders")):
                    break
                before_action()
                _scope(root, settings)
                path = _target(root, repair.local.folder)
                current = sync.inspect_candidate(path, prefixes)
                if current.origin != repair.local.origin or not current.eligible:
                    raise SettingsError("repair scope changed")
                selected = replace(detected.plan, to_reconcile=[repair])
                if item.get("reconcile") and repair.origin_stale:
                    effects = True
                    applied["origins_fixed"] += sync.apply_reconcile_origins(root, selected, issues, emit=progress)
                if item.get("rename_folders") and repair.folder_mismatch:
                    before_action()
                    _scope(root, settings)
                    _target(root, repair.ref.name)
                    current = sync.inspect_candidate(path, prefixes)
                    expected_origin = repair.ref.url if item.get("reconcile") and repair.origin_stale else repair.local.origin
                    if not current.eligible or current.origin != expected_origin:
                        raise SettingsError("rename scope changed")
                    effects = True
                    applied["renamed"] += sync.apply_rename_folders(root, selected, issues, emit=progress)
    except (SettingsError, OSError, ValueError):
        failure = "Execution scope or state changed; inspect partial results before retrying."
    payload = sync.build_report(detected, applied, issues, "scan-only" if scan_only else mode)
    if failure:
        payload["issues"].append({"repo": "archive", "action": "held", "detail": failure})
    return {"exit_code": 2 if failure else int(bool(issues)), "effects_possible": effects, "result": payload}


def _protected(settings):
    security = settings.values["security"]
    return tuple([*security["never_publish"], *security.get("local_never_publish", ()),
                  settings.values.get("machine", {}).get("fleet_secret", "")])


def _publish(item, settings, before_action, *, scan_only, progress, approve):
    """Plan locally, approve masked scope, then gate each exact tip/target before pushing."""
    root = Path(item["root"])
    plan = sync.build_publish_plan(sync.collect_publish_candidates(root), include_dirty=item.get("include_dirty", False))
    policies = {}
    for candidate in plan.to_push:
        _target(root, candidate.folder)
        snapshot = candidate.push_snapshot
        if snapshot is not None and not approved_remote(snapshot.endpoint, item["approved_remote_prefixes"]):
            raise SettingsError("publication destination outside allowances")
        policies[candidate.folder] = load_policy(root / candidate.folder, home=settings.home)
    payload = {"mode": "publish", "counts": plan.counts(),
               "plan": {name: [{"folder": candidate.folder, "branch": candidate.branch,
                                 "upstream": candidate.upstream, "ahead": candidate.ahead,
                                 "behind": candidate.behind,
                                 "tip": candidate.push_snapshot.tip if candidate.push_snapshot else None}
                                for candidate in getattr(plan, name)]
                        for name in ("to_push", "dirty_ahead", "diverged", "behind", "no_upstream", "in_sync")},
               "applied": {"pushed": 0}, "publication": [], "issues": [],
               "security_notice": "Local plan only. Security checking runs before each actual push."}
    if scan_only or not plan.to_push:
        return {"exit_code": 0, "effects_possible": False, "result": payload}
    if approve is None or not approve("publish", conceal(payload, _protected(settings))):
        payload["error"] = error_message("approval_required")
        return {"exit_code": 2, "effects_possible": False, "result": payload}
    issues, effects = [], False
    def verify():
        nonlocal effects
        before_action()
        _scope(root, settings)
        for candidate in plan.to_push:
            _target(root, candidate.folder)
        effects = True
    try:
        payload["applied"]["pushed"] = sync.apply_publish(root, plan, issues,
            pause=item.get("publish_pause", sync.DEFAULT_PUBLISH_PAUSE_SECONDS), settings_home=settings.home,
            emit=progress, results=payload["publication"], before_action=verify, expected_policies=policies)
    except KeyboardInterrupt:
        payload["error"] = error_message("interrupted")
        payload["interrupted"] = True
    except Exception:
        payload["error"] = "Publication scope or state changed; inspect partial results before retrying."
    # Completed candidates remain visible if a later push or policy check failed/interrupted.
    payload["applied"]["pushed"] = sum(result["status"] in ("pushed", "already-current") for result in payload["publication"])
    payload["issues"] = [{"repo": issue.repo, "action": issue.action, "detail": issue.detail} for issue in issues]
    return {"exit_code": 130 if payload.get("interrupted") else 2 if payload.get("error") else int(bool(issues)),
            "effects_possible": effects, "result": payload}


def run_archives(settings, selected, *, scan_only=True, before_action=lambda: None,
                 after_run=None, approve=None) -> ArchiveResult:
    """Validate all selected scope/sinks before action; stop on changed state/required I/O.

    No implicit approval or receipts. Callbacks recheck caller-owned state and optionally save
    completion metadata. Requested reports/logs are listed as actual invocation artifacts.
    """
    started = time.perf_counter()
    result, sink, log, phase = ArchiveResult(scan_only, settings=settings), None, None, "scope"
    active_request = None
    try:
        result.protected = _protected(settings)
        if not scan_only and approve is None:
            raise RuntimeIOError("approval_required")
        selected = copy.deepcopy(selected)
        roots = []
        for item in selected:
            if item["mode"] not in ("update", "sync", "scan", "repair", "publish") or not isinstance(item["approved_remote_prefixes"], list) or not item["approved_remote_prefixes"] or any(
                    not isinstance(prefix, str) or not prefix.strip() for prefix in item["approved_remote_prefixes"]):
                raise SettingsError("invalid operation mode or remote allowances")
            root = checked_path(Path(item["root"]))
            if any(root == other or root in other.parents or other in root.parents for other in roots):
                raise SettingsError("selected archives overlap")
            roots.append(root)
            item["root"] = str(root)
            if any(type(item.get(key, False)) is not bool for key in ("reconcile", "rename_folders", "include_dirty")):
                raise SettingsError("action selections must be booleans")
            pause = item.get("publish_pause", sync.DEFAULT_PUBLISH_PAUSE_SECONDS)
            if type(pause) not in (int, float) or not math.isfinite(pause) or pause < 0:
                raise SettingsError("invalid publish pause")
            if item["mode"] == "publish" and (item.get("reconcile") or item.get("rename_folders")):
                raise SettingsError("publication must be exclusive")
            if item["mode"] == "scan" and (not scan_only or item.get("reconcile") or item.get("rename_folders")):
                raise SettingsError("scan requests cannot select mutations")
            if item["mode"] != "publish" and item.get("include_dirty"):
                raise SettingsError("dirty publication choice requires publish")
            _scope(Path(item["root"]), settings)
        phase = "stale"
        before_action()
        for section, active in (("output", settings.values["output"]["mode"] != "stdout"),
                                ("logging", settings.values["logging"]["enabled"])):
            if active and excluded(settings.values[section]["directory"], settings.values["scope"]["exclude_paths"], contains=True):
                raise RuntimeIOError("excluded_destination")
        phase = "report_setup"
        if settings.values["output"]["mode"] != "stdout":
            sink = ReportSink(settings.values["output"]["directory"], settings.values["output"]["format"],
                              prefix=settings.component.replace("_", "-"))
            result.report_path = sink.path
        phase = "logging_setup"
        log = configure_logging(settings, settings.component)
        if log.handler is not None:
            result.log_path = Path(log.handler.baseFilename)
        log.event("refresh_started", roots=len(selected))
        for item in selected:
            phase = "stale"
            before_action()
            _scope(Path(item["root"]), settings)
            request = item
            phase = "execution"
            archive_started = time.perf_counter()
            if not Path(item["root"]).is_dir():
                outcome = {"exit_code": 1, "effects_possible": False, "result": {"error": "root missing"}}
            else:
                active_request = request
                outcome = execute_archive(request, settings, before_action, scan_only=scan_only, approve=approve)
            result.effects_possible |= outcome["effects_possible"]
            result.archives.append({"root": item["root"], "operation": request["mode"],
                                    "status": "partial" if outcome["exit_code"] and outcome["effects_possible"] else "failed" if outcome["exit_code"] else "ok",
                                    "elapsed_seconds": round(time.perf_counter() - archive_started, 3), **outcome})
            active_request = None
            log.event("archive_finished", roots=1, failed=int(bool(outcome["exit_code"])))
            if outcome["exit_code"] == 130:
                raise KeyboardInterrupt
        phase = "stale"
        before_action()
        if not scan_only and selected and after_run is not None:
            phase = "receipts"
            after_run(result)
    except KeyboardInterrupt:
        result.errors.append("interrupted")
        _uncertain(result, active_request, scan_only, 130)
    except RuntimeIOError as exc:
        result.errors.append(exc.code)
        _uncertain(result, active_request, scan_only, 2)
    except Exception:  # backend/plugin failures must never conceal uncertain repository effects
        result.errors.append(phase)
        _uncertain(result, active_request, scan_only, 2)
    finally:
        if log is not None:
            try:
                log.event("refresh_finished", exit_code=result.exit_code, roots=len(result.archives))
            except (RuntimeIOError, OSError):
                result.errors.append("logging_write")
            try:
                log.close()
            except (RuntimeIOError, OSError):
                result.errors.append("logging_write")
        result.elapsed_seconds = round(time.perf_counter() - started, 3)
    if sink is not None:
        if result.errors and not result.archives:
            sink.abort()
            result.report_path = None
        else:
            try:
                sink.write(render_result(result, result.settings.values["output"]["format"]))
            except (RuntimeIOError, OSError):
                sink.abort()
                result.errors.append("report_write")
                result.report_path = None
    return result


def run_refresh(*, home=None, only_root=None, scan_only=False, force_sync=False, overrides=None) -> ArchiveResult:
    """Refresh registered update/sync choices; preview leaves receipts unchanged."""
    try:
        data = load_registry(home=home)
        preferences = data.preferences
        settings = resolve_document(preferences.document if preferences else {"schema_version": 2},
                                    "archive_manage", home=data.home, overrides=overrides,
                                    configured=preferences is not None)
        selected = data["installations"]
        if only_root is not None:
            key = _key(os.path.abspath(Path(only_root).expanduser()))
            selected = [item for item in selected if _key(item["root"]) == key]
            if not selected:
                raise RuntimeIOError("not_registered")
        if any(item.get("mode", "update") not in ("update", "sync") for item in selected):
            raise RuntimeIOError("scope")
        requests = [{**item, "mode": "sync" if force_sync else item.get("mode", "update"),
                     "approved_remote_prefixes": item.get("approved_remote_prefixes", list(DEFAULT_APPROVED_REMOTE_PREFIXES))}
                    for item in selected]
        def save_receipts(result):
            for item, outcome in zip(selected, result.archives):
                item.update(last_run_at=datetime.now().isoformat(timespec="seconds"),
                            last_run_result="ok" if not outcome["exit_code"] else f"failed: exit {outcome['exit_code']}",
                            last_run_elapsed_seconds=outcome["elapsed_seconds"], last_report=None, last_report_at=None)
            save_registry(data)
        return run_archives(settings, requests, scan_only=scan_only, before_action=data.verify,
                            after_run=save_receipts, approve=lambda *_: True)
    except (SettingsError, OSError, RuntimeIOError) as exc:
        return ArchiveResult(scan_only, errors=[exc.code if isinstance(exc, RuntimeIOError) else "settings"])
