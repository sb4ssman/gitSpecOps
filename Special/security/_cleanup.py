"""Headless cleanup planning/application over active scans and the general mirror rewriter.

Private reports supply raw values; explicit choices select finding ids, whole containing files,
literal paths and exact identity pairs. Nothing is inferred as safe to purge. Plans bind source
refs and selected policy. Results/logs are masked; source checkout/history and remotes are never
changed. A rewritten mirror still needing review stays private and cannot authorize publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from Basic._run import CommandFailed
from Special._history.native import snapshot
from Special._history.operation import execute
from Special._history.plan import load, prepare, save
from Special._history.rules import IdentityRule, Rule, Rules
from Special._runtime.files import checked_path, excluded, RuntimeIOError
from Special._runtime.logger import configure_logging
from Special._runtime.output import ReportSink, conceal
from Special._settings import (SETTINGS_NAME, SettingsError, resolve_document, resolve_settings,
                               select_home, SECURITY_ENGINES)
from Special.security._findings import write_report
from Special.security._material import scan
from Special.security._me import load_policy, policy_revision
from Special.security._private_files import private_path, read_private_json
from Special.security._review_operation import _report


@dataclass
class CleanupResult:
    status: str = "incomplete"
    message: str = "Cleanup did not complete; no publication is authorized."
    plan_id: str | None = None
    source_scan: str | None = None
    counts: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict, repr=False)
    check: dict = field(default_factory=dict, repr=False)
    artifacts: list = field(default_factory=list, repr=False)
    protected: tuple = field(default=(), repr=False)
    effects_possible: bool = False
    stage: str = "inputs"
    error_code: str | None = None
    delivery: dict = field(default_factory=lambda: {"mode": "stdout", "format": "text"}, repr=False)

    @property
    def exit_code(self):
        return (0 if self.status in ("planned", "verified") else 1 if self.status == "review-required" else
                130 if self.status == "interrupted" else 2)

    def record(self):
        return conceal({"schema_version": 1, "operation": "clean-history", "status": self.status,
                        "message": self.message, "plan_id": self.plan_id, "counts": self.counts,
                        "source_scan": self.source_scan,
                        "decisions": self.decisions, "stage": self.stage, "error_code": self.error_code,
                        "check": self.check, "artifacts": self.artifacts, "effects_possible": self.effects_possible,
                        "publication_clearance": False}, self.protected)


def _preferences(home, legacy, overrides):
    if type(legacy) is not bool or (overrides is not None and (
            not isinstance(overrides, dict) or set(overrides) - {"output", "logging"})):
        raise SettingsError("cleanup overrides select output/logging only; security and scope use the selected profile")
    selected = select_home(home, component="security")[0]
    checked_path(selected / SETTINGS_NAME)
    if legacy:
        if (selected / SETTINGS_NAME).exists():
            raise SettingsError("legacy mode cannot bypass common settings")
        return resolve_document({"schema_version": 2}, "security", home=selected, overrides=overrides, configured=False)
    return resolve_settings("security", home=selected, overrides=overrides)


def _policy(repo, settings, legacy):
    # Re-resolve the selected home on EVERY freshness check, including missing/corrupt files.
    policy = load_policy(repo, home=settings.home, legacy_policy=legacy)
    if policy.gaps:
        raise SettingsError("selected policy or review state is incomplete")
    return policy


def _evidence(item):
    return tuple(getattr(item, name) for name in ("check", "classification", "value", "where", "object_id",
                 "line", "content_id", "context_kind", "occurrence"))


def _choices(raw, reported, current, model):
    """Translate explicit finding-id choices without returning protected raw values."""
    keys = {"schema_version", "replace_findings", "remove_files", "remove_paths", "rewrite_identities"}
    if not isinstance(raw, dict) or set(raw) != keys or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("a current explicit cleanup-choice document is required")
    if any(not isinstance(raw[key], list) or len(raw[key]) > 10000 for key in keys - {"schema_version"}):
        raise ValueError("invalid cleanup choices")
    if not any(raw[key] for key in keys - {"schema_version"}):
        raise ValueError("select at least one explicit cleanup action")
    ids = {f"finding-{index:06d}": item for index, item in enumerate(reported.findings, 1)}
    fresh = {_evidence(item) for item in current.findings}
    selected = set()
    def finding(identifier):
        if not isinstance(identifier, str) or identifier not in ids or _evidence(ids[identifier]) not in fresh:
            raise ValueError("selected finding is stale or absent")
        selected.add(identifier)
        return ids[identifier]
    replacements, identities, removals = [], [], list(raw["remove_paths"])
    paths = {name for tree in model.trees.values() for name in tree}
    for row in raw["replace_findings"]:
        if not isinstance(row, dict) or set(row) != {"finding_id", "new", "targets", "ignore_case", "bounded"} or not isinstance(row["targets"], list):
            raise ValueError("invalid finding replacement choice")
        item = finding(row["finding_id"])
        if item.context_kind in ("identity", "ref") or item.check == "image GPS position":
            raise ValueError("use an exact identity or explicit file removal for this finding")
        replacements.append(Rule(item.value, row["new"], row["ignore_case"], row["bounded"], tuple(row["targets"])))
    for identifier in raw["remove_files"]:
        item = finding(identifier)
        if item.context_kind not in ("content", "path", "archive-path", "archive-member", "metadata", "archive-metadata"):
            raise ValueError("selected finding does not name a containing file")
        candidates = {path for path in paths if item.where == path or item.where.startswith(path + "!") or
                      item.where in (path + " [path]", path + " [metadata]")}
        if len(candidates) != 1:
            raise ValueError("containing file is ambiguous; choose its literal path explicitly")
        removals.extend(candidates)
    for row in raw["rewrite_identities"]:
        if not isinstance(row, dict) or set(row) != {"finding_id", "name", "email"}:
            raise ValueError("invalid identity choice")
        item = finding(row["finding_id"])
        person = None
        if item.context_kind == "identity":
            if item.object_id in model.commits and item.where in ("author", "committer"):
                person = getattr(model.commits[item.object_id], item.where)
            elif item.object_id in model.tags and item.where.endswith(" [tagger]"):
                person = model.tags[item.object_id].tagger
        if person is None:
            raise ValueError("select an exact author, committer or tagger identity finding")
        rule = IdentityRule(person.name, person.email, row["name"], row["email"])
        if rule not in identities:
            identities.append(rule)
    rules = Rules(replacements, list(dict.fromkeys(removals)), identities)
    for path in rules.remove_paths:
        if not any(name.startswith(path) if path.endswith("/") else name == path for name in paths):
            raise ValueError("an explicitly selected removal path has no historical match")
    return rules, {"selected_findings": len(selected), "replacements": len(replacements),
                   "removal_choices": len(rules.remove_paths), "identity_pairs": len(identities)}


def _artifact(result, path, kind="private operational record"):
    value = {"kind": kind, "path": str(path), "disclosure": "private"}
    if not any(item["path"] == str(path) for item in result.artifacts):
        result.artifacts.append(value)


def run_cleanup(action, source, *, choices=None, plan_out=None, workspace=None,
                home=None, legacy_policy=False, include_remote_refs=False, engines=None,
                approve=None, confirmation=None, overrides=None):
    """One callable operation for direct CLI, gitso and future GUI. No prompts or printing.

plan reads a full private history report and explicit choices; only --plan-out saves a plan.
apply reloads its saved policy binding, proves the mirror and rescans using that same policy.
Optional common reports/logs are reserved before effects; failures never select another sink.
"""
    result, log, sink, created = CleanupResult(), None, None, []
    settings = None
    try:
        if action not in ("plan", "apply"):
            raise ValueError("select plan or apply")
        settings = _preferences(home, legacy_policy, overrides)
        if excluded(Path(source).expanduser().absolute(), settings.values["scope"]["exclude_paths"]):
            raise SettingsError("selected report or saved plan is excluded; it was not read")
        if action == "apply":
            if choices is not None or plan_out is not None or include_remote_refs or engines is not None:
                raise ValueError("apply uses the policy and scope bound into the saved plan")
            plan = load(source)
            context = plan.context
            if (set(context) != {"kind", "home", "legacy_policy", "policy_revision", "engines", "source_scan", "decisions"} or
                    context["kind"] != "security-cleanup" or type(context["legacy_policy"]) is not bool):
                raise ValueError("a saved security cleanup plan is required")
            if context["home"] != str(settings.home) or context["legacy_policy"] != legacy_policy:
                raise SettingsError("select the same settings home and policy mode used to prepare this plan")
            policy = _policy(Path(plan.source), settings, context["legacy_policy"])
            if policy_revision(policy) != context["policy_revision"]:
                raise ValueError("policy changed; create a new cleanup plan")
            selected_engines = context["engines"]
            if workspace is None or confirmation != "REWRITE" or approve != plan.plan_id:
                raise ValueError("a new workspace, exact plan approval and typed REWRITE are required")
            plan.current()
            result.decisions = context["decisions"]
            result.source_scan = context["source_scan"]
        else:
            if choices is None or workspace is not None or approve is not None or confirmation is not None:
                raise ValueError("planning needs choices and does not accept execution options")
            for path in (source, choices, plan_out):
                if path is not None and excluded(Path(path).expanduser().absolute(), settings.values["scope"]["exclude_paths"]):
                    raise SettingsError("a selected input or destination is excluded")
            raw = read_private_json(source)
            if (not isinstance(raw, dict) or raw.get("material") != "history" or
                    not isinstance(raw.get("repository"), str) or not Path(raw["repository"]).is_absolute()):
                raise ValueError("a full private history report is required")
            policy = _policy(Path(raw["repository"]), settings, legacy_policy)
            selected_engines = list(policy.engines if engines is None else engines)
        result.protected = tuple(value for values in policy.identities.values() for value in values)
        if (not isinstance(selected_engines, (list, tuple)) or
                any(not isinstance(value, str) or value not in SECURITY_ENGINES for value in selected_engines) or
                len(set(selected_engines)) != len(selected_engines)):
            raise ValueError("select distinct supported engines")
        result.delivery = dict(settings.values["output"])
        exclusions = settings.values["scope"]["exclude_paths"]
        if action == "apply" and excluded(Path(workspace).expanduser().absolute(), exclusions, contains=True):
            raise SettingsError("selected workspace is excluded")
        if action == "apply" and excluded(Path(source).expanduser().absolute(), exclusions):
            raise SettingsError("selected saved plan is excluded")
        for section, enabled in (("output", result.delivery["mode"] != "stdout"),
                                 ("logging", settings.values["logging"]["enabled"])):
            directory = settings.values[section]["directory"]
            if enabled and excluded(directory, exclusions):
                raise SettingsError("selected output or log destination is excluded")
        if settings.values["logging"]["enabled"]:
            private_path(settings.values["logging"]["directory"] / "security_cleanup.log")
        if result.delivery["mode"] != "stdout":
            sink = ReportSink(result.delivery["directory"], result.delivery["format"], prefix="security-cleanup")
            try:
                private_path(sink.path)
            except (OSError, ValueError):
                sink.abort()
                sink = None
                raise
            _artifact(result, sink.path, "masked operation report")
        log = configure_logging(settings, "security_cleanup")
        if log.handler is not None:
            _artifact(result, Path(log.handler.baseFilename), "counts-only operational log")
        log.event("started", attempted=1)
        if action == "plan":
            result.stage = "planning"
            report = _report(raw, policy)
            result.protected += tuple(item.value for item in report.findings)
            model, unused = snapshot(report.repository, include_remote_refs=include_remote_refs)
            expected_refs = {**model.refs, "HEAD": model.refs[model.head]}
            if raw.get("refs") != expected_refs:
                raise ValueError("report references are stale")
            current = scan(Path(report.repository), policy, material="history", engines=selected_engines)
            if current.refs != expected_refs:
                raise ValueError("references changed while planning")
            decisions = read_private_json(choices)
            rules, counts = _choices(decisions, report, current, model)
            context = {"kind": "security-cleanup", "home": str(settings.home), "legacy_policy": legacy_policy,
                       "policy_revision": policy_revision(policy), "engines": selected_engines, "source_scan": report.scan_id,
                       "decisions": decisions}
            plan = prepare(report.repository, rules, include_remote_refs=include_remote_refs, context=context)
            if plan.refs != model.refs or plan.symbolic_refs != model.symbolic_refs or policy_revision(
                    _policy(Path(plan.source), settings, legacy_policy)) != context["policy_revision"]:
                raise ValueError("source or policy changed during planning")
            result.plan_id, result.counts, result.check = plan.plan_id, counts, current.record()
            result.source_scan = report.scan_id
            result.decisions = decisions
            result.counts.update(commits=len(model.commits), refs=len(model.refs),
                                 remote_refs=sum(name.startswith("refs/remotes/") for name in model.refs),
                                 symbolic_refs=len(model.symbolic_refs))
            if plan_out is not None:
                result.stage = "saving-plan"
                _artifact(result, save(plan, plan_out), "saved cleanup plan")
            result.status, result.message = "planned", "Explicit cleanup planned; only a new private mirror may be rewritten."
        else:
            result.plan_id = plan.plan_id
            rules = Rules.from_record(plan.choices)
            result.protected += tuple(rule.old for rule in rules.replacements)
            result.protected += tuple(value for rule in rules.identities for value in (rule.old_name, rule.old_email))
            result.effects_possible = True
            result.stage = "rewriting-mirror"
            outcome = execute(plan, workspace, confirmation=confirmation, approved_plan=approve, artifacts=created)
            _artifact(result, outcome.mirror, "rewritten private mirror")
            if policy_revision(_policy(Path(plan.source), settings, context["legacy_policy"])) != context["policy_revision"]:
                raise ValueError("policy changed during rewriting; the private mirror needs review")
            result.stage = "rescanning-mirror"
            checked = scan(outcome.mirror, policy, material="history", engines=selected_engines)
            try:
                plan.current()
                if policy_revision(_policy(Path(plan.source), settings, context["legacy_policy"])) != context["policy_revision"]:
                    checked.gap("policy", "policy changed during rescan; review required")
            except (CommandFailed, OSError, ValueError):
                checked.gap("freshness", "source or policy could not be revalidated after rescan")
            scan_path = Path(workspace).absolute() / "rescan.json"
            write_report(scan_path, checked)
            _artifact(result, scan_path, "full private rescan")
            result.check = checked.record()
            result.counts = {"commits": outcome.proof.commits, "refs": outcome.proof.refs,
                             "retained_files_checked": outcome.proof.files}
            result.status = "incomplete" if checked.gaps else "review-required" if checked.actionable else "verified"
            result.message = "Private mirror proved and rescanned; review the result before any separate publication."
        result.stage = "completed"
        log.event("finished", attempted=1, failed=int(result.exit_code != 0), exit_code=result.exit_code)
    except KeyboardInterrupt:
        result.status, result.message = "interrupted", "Cleanup interrupted; inspect the listed private artifacts before continuing."
    except (CommandFailed, SettingsError, RuntimeIOError, OSError, ValueError, TypeError, KeyError) as exc:
        result.status = "incomplete"
        result.message = {"inputs": "Input, approval, policy or output validation failed; no rewrite was started.",
                          "planning": "Choices, report or source freshness could not be verified; no plan was saved.",
                          "saving-plan": "The selected plan could not be saved; no mirror was rewritten.",
                          "rewriting-mirror": "Mirror rewriting or proof did not complete; inspect listed private artifacts.",
                          "rescanning-mirror": "The private mirror needs review; security rescanning did not complete."}.get(
                              result.stage, "Cleanup did not complete; inspect listed private artifacts.")
        if isinstance(exc, SettingsError):
            result.message = str(exc)
        hints = {
            "unsupported refs; remote-tracking refs require explicit inclusion": ("ref-scope", "Tracking refs require --include-remote-refs; other ref namespaces need separate review."),
            "report references are stale": ("report-stale", "The repository moved since this report; create a fresh history report."),
            "selected finding is stale or absent": ("finding-stale", "A selected finding no longer matches; refresh the report and review the choices."),
            "an explicitly selected removal path has no historical match": ("path-absent", "An explicit removal path has no history; review the choices."),
            "policy changed; create a new cleanup plan": ("policy-stale", "The selected policy changed; create a fresh cleanup plan."),
            "source refs changed since planning": ("plan-stale", "The repository moved since planning; create a fresh cleanup plan."),
        }
        result.error_code = "validation-failed"
        if str(exc) in hints:
            result.error_code, result.message = hints[str(exc)]
    finally:
        for path in created:
            _artifact(result, path)
        if sink is not None:
            try:
                sink.write(render(result, result.delivery["format"]))
            except (OSError, RuntimeIOError):
                result.artifacts = [item for item in result.artifacts if item["path"] != str(sink.path)]
                result.status, result.message = "incomplete", "The requested operation report failed; inspect private operational artifacts."
                result.error_code = "report-write"
        if log is not None:
            try:
                if result.exit_code:
                    log.event("held", failed=1, exit_code=result.exit_code)
            except (OSError, RuntimeIOError):
                result.status, result.message = "incomplete", "Required operational logging could not finish."
            finally:
                try:
                    log.close()
                except OSError:
                    result.status, result.message = "incomplete", "Required operational logging could not close."
    return result


def render(result, format):
    """Same masked payload for stdout, report and GUI adapters; no raw native diagnostics."""
    record = result.record()
    if format == "json":
        return json.dumps(record, indent=2)
    lines = [record["message"], "Status: " + record["status"]]
    if record["plan_id"]:
        lines.append("Plan: " + record["plan_id"])
    lines.append("Counts: " + json.dumps(record["counts"], sort_keys=True))
    if record["check"]:
        lines.append("Security check: " + record["check"]["check_status"])
    for artifact in record["artifacts"]:
        lines.append(f"Produced {artifact['kind']}: {artifact['path']} ({artifact['disclosure']})")
    lines.append("History cleanup does not rotate credentials or erase external copies.")
    return "\n".join(lines)
