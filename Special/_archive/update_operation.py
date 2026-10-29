"""Headless archive updating with explicitly resolved settings and structured results.

Call run_update(settings, UpdateRequest(...)). It never resolves another user profile or
prints. Requested reports/logs are local sinks; progress is an optional caller callback.
This operation pulls existing eligible checkouts only, without fleet enrollment or gh.
"""
from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from Basic._run import run
from Special._archive import updater
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES
from Special._runtime.files import RuntimeIOError, excluded
from Special._runtime.logger import configure_logging
from Special._runtime.output import ReportSink, conceal
from Special._settings import ResolvedSettings

ERROR_MESSAGES = {
    "approval_required": "The proposed update was not approved; no further updates were run.",
    "settings_component": "This operation needs the archive updater's resolved settings.",
    "invalid_scope": "Select at least one existing archive folder and an allowed origin prefix.",
    "scope": "A selected archive folder is missing or cannot be accessed.",
    "excluded_root": "A selected archive folder is excluded by the scope policy.",
    "excluded_destination": "A selected report or log destination conflicts with an exclusion.",
    "source_destination": "Reports and logs must be outside the gitSpecOps source checkout.",
    "linked_destination": "A report or log destination crosses a symlink or junction.",
    "invalid_destination": "A selected report or log destination is not a directory.",
    "report_setup": "The selected report destination could not be prepared.",
    "report_write": "The requested report could not be saved.",
    "logging_setup": "The selected operational log could not be opened.",
    "logging_busy": "The operational log is busy; its existing lock was left in place.",
    "logging_write": "Required operational logging failed; further updates were stopped.",
    "git_unavailable": "Git is missing or could not be started.",
    "inspection": "Archive inspection or updating could not finish.",
}


def explain_error(code: str) -> str:
    return ERROR_MESSAGES.get(code, "The operation could not finish.")


@dataclass(frozen=True)
class UpdateRequest:
    roots: tuple[Path, ...] | None = field(default=None, repr=False)
    scan_only: bool = False
    approved_prefixes: tuple[str, ...] = tuple(DEFAULT_APPROVED_REMOTE_PREFIXES)


@dataclass
class UpdateResult:
    mode: str
    approved_prefixes: tuple[str, ...] = field(repr=False)
    generated: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    reports: list = field(default_factory=list, repr=False)
    errors: list[str] = field(default_factory=list)
    completed_roots: int = 0
    effects_possible: bool = False
    elapsed_seconds: float = 0.0
    report_path: Path | None = field(default=None, repr=False)
    log_path: Path | None = field(default=None, repr=False)
    protected: tuple[str, ...] = field(default=(), repr=False)

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 2
        return int(any(repo.result.startswith("failed:") for report in self.reports for repo in report.repos))

    def record(self, *, redacted: bool = True, show_remote_urls: bool = False) -> dict:
        """Schema-v1 presentation record. Raw records are only for explicitly trusted callers."""
        record = updater.report_payload(self.reports, self.mode, list(self.approved_prefixes))
        record.update(schema_version=1, operation="archive_update", generated=self.generated, exit_code=self.exit_code,
                      status=("partial" if self.errors and (self.effects_possible or self.completed_roots)
                              else ("failed" if self.exit_code else "ok")), errors=list(self.errors),
                      completed_roots=self.completed_roots, effects_possible=self.effects_possible,
                      elapsed_seconds=self.elapsed_seconds,
                      artifacts=[{"kind": kind, "path": str(path)} for kind, path in
                                 (("report", self.report_path), ("operational-log", self.log_path)) if path is not None])
        if redacted:
            if not show_remote_urls:
                for root in record["roots"]:
                    for repo in root["scan"]["repos"]:
                        repo["origin"] = "present" if repo["origin_present"] else None
            return conceal(record, self.protected)
        return record


def render_result(result: UpdateResult, format: str, *, show_remote_urls: bool = False) -> str:
    """Render without replacing process-global stdout, for CLI, GUI and report-file reuse."""
    if format == "json":
        return json.dumps(result.record(show_remote_urls=show_remote_urls), indent=2)
    stream = io.StringIO()
    print(f"{updater.APP_NAME} v{updater.VERSION}\nMode: {result.mode}", file=stream)
    for report in result.reports:
        updater.print_scan(report, show_remote_urls, stream=stream)
        print(f"Excluded folders: {report.excluded_folders}", file=stream)
        if result.mode == "scan-only":
            print("Scan only: no repositories were updated.", file=stream)
        else:
            updater.print_summary(report, stream=stream)
    print(f"Result: {result.record()['status']} (exit {result.exit_code})", file=stream)
    for error in result.errors:
        print(f"Error: {explain_error(error)}", file=stream)
    for artifact in result.record()["artifacts"]:
        print(f"{artifact['kind']}: {artifact['path']}", file=stream)
    print(f"Elapsed: {result.elapsed_seconds:.3f}s", file=stream)
    return conceal(stream.getvalue().rstrip(), result.protected)


def run_update(settings: ResolvedSettings, request: UpdateRequest | None = None, *,
               progress=None, show_remote_urls: bool = False, before_action=None, approve=None) -> UpdateResult:
    """Validate scope/sinks before pulls, execute, and return results without printing.

An explicit empty request scope is an error; omitted scope uses saved roots, then cwd.
Exclusions apply before Git inspection, including to a checkout containing an excluded
subtree. Required sink failures stop further work and never trigger another destination.
"""
    started = time.perf_counter()
    request = request or UpdateRequest()
    private = [*settings.values["security"]["never_publish"], *settings.values["security"].get("local_never_publish", ())]
    secret = settings.values.get("machine", {}).get("fleet_secret")
    if secret:
        private.append(secret)
    result = UpdateResult("scan-only" if request.scan_only else "update", request.approved_prefixes,
                          protected=tuple(private))
    sink = log = None
    phase = "scope"
    try:
        if settings.component != "archive_update":
            raise RuntimeIOError("settings_component")
        raw_roots = request.roots if request.roots is not None else settings.values["scope"]["roots"] or [Path.cwd()]
        exclusions = settings.values["scope"]["exclude_paths"]
        if not raw_roots or not request.approved_prefixes:
            raise RuntimeIOError("invalid_scope")
        roots = updater.resolve_roots([Path(root) for root in raw_roots])
        if any(excluded(root, exclusions) for root in roots):
            raise RuntimeIOError("excluded_root")
        for section, active in (("output", settings.values["output"]["mode"] != "stdout"),
                                ("logging", settings.values["logging"]["enabled"])):
            if active and excluded(settings.values[section]["directory"], exclusions, contains=True):
                raise RuntimeIOError("excluded_destination")
        phase = "report_setup"
        if settings.values["output"]["mode"] != "stdout":
            sink = ReportSink(settings.values["output"]["directory"], settings.values["output"]["format"])
            result.report_path = sink.path
        phase = "logging_setup"
        log = configure_logging(settings, "archive_update")
        if log.handler is not None:
            result.log_path = Path(log.handler.baseFilename)
        log.event("scan_started" if request.scan_only else "update_started", roots=len(roots))
        phase = "git_unavailable"
        if run(["git", "--version"], timeout=30).returncode:
            raise RuntimeIOError("git_unavailable")
        phase = "inspection"
        for root in roots:
            report = updater.scan_root(root, list(request.approved_prefixes), exclude_paths=exclusions)
            result.reports.append(report)
            if request.scan_only:
                for repo in report.repos:
                    repo.result = repo.action if not repo.eligible else "not run (scan only)"
            else:
                if approve is not None and not approve(conceal(updater.report_payload([report], "update", list(request.approved_prefixes)), result.protected)):
                    result.errors.append("approval_required")
                    break
                result.effects_possible |= any(repo.eligible for repo in report.repos)
                emit = ((lambda text: progress(conceal(text, result.protected))) if progress is not None else None)
                updater.run_updates(report, emit=emit, log=log, before_action=before_action)
            result.completed_roots += 1
            log.event("archive_finished", repositories=len(report.repos), excluded=report.excluded_folders)
    except RuntimeIOError as exc:
        result.errors.append(exc.code)
    except (OSError, ValueError, RuntimeError):
        result.errors.append(phase)
    finally:
        if log is not None:
            try:
                log.event("execution_finished", exit_code=result.exit_code,
                          repositories=sum(len(report.repos) for report in result.reports))
            except (RuntimeIOError, OSError):
                result.errors.append("logging_write")
            log.close()
    result.elapsed_seconds = round(time.perf_counter() - started, 3)
    if sink is not None:
        # Setup failure has no repository result to deliver; discard the reserved file.
        if result.errors and not result.reports:
            sink.abort()
            result.report_path = None
        else:
            try:
                sink.write(render_result(result, settings.values["output"]["format"],
                                         show_remote_urls=show_remote_urls))
            except (RuntimeIOError, OSError):
                sink.abort()
                result.errors.append("report_write")
                result.report_path = None
    return result
