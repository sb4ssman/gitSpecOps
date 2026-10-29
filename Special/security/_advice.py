"""Read-only local security advice over the same policy/readers/engines as action checks.

inspect_advice(repo, ...) checks current tracked/untracked nonignored working files and cached
outgoing history for one supported push mapping. It never fetches, stages, publishes, writes a
report or authorizes an action. Results are masked and local-only, never fleet manifest fields.
No message or future commit is guessed. Observations are advisory, not atomic file snapshots;
the actual commit/push must still run its exact current checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from Basic._objects import git_output
from Basic._run import CommandFailed, run_git
from Special._settings import SettingsError, select_home
from Special.security._material import scan
from Special.security._me import load_policy
from Special.security._push import _same_policy, read_push_snapshot


def _revision(repo):
    """Private freshness facts; no names, object ids or errors are copied into advice."""
    head = run_git(repo, ["rev-parse", "--verify", "--quiet", "HEAD"])
    if head.returncode not in (0, 1):
        raise ValueError("HEAD unavailable")
    return head.stdout, git_output(repo, ["ls-files", "--stage", "-z"])


def inspect_advice(repo, *, settings_home=None, legacy_policy=False, expected_settings=None):
    """Return a safe local record; failures leave useful available findings, never clearance.

    Policy/root exclusions are checked before inspecting files. Outgoing comparison uses the
    current local upstream ref, whose freshness is separate from this check's timestamp.
    Missing mappings do not prevent working-tree advice and cannot imply a clean outgoing scan.
    """
    result = {"schema_version": 1, "scope": "local-advisory", "action_clearance": False,
              "observed_at": datetime.now(timezone.utc).isoformat(), "check_status": "incomplete",
              "working_tree": None, "outgoing": None, "gaps": [], "artifacts": []}
    try:
        home = select_home(settings_home, component="security")[0]
        if expected_settings is not None:
            expected_settings.verify()
            if home.resolve() != expected_settings.home.resolve():
                raise SettingsError("selected common profile changed")
        repo = Path(repo).absolute()
        policy = load_policy(repo, home=home, legacy_policy=legacy_policy)
        if Path(git_output(repo, ["rev-parse", "--show-toplevel"]).strip()).resolve() != repo.resolve():
            raise ValueError("select root")
        before = _revision(repo)
        tree = scan(repo, policy, material="tree")
        result["working_tree"] = tree.record()
        statuses = [tree.check_status]
        try:
            snapshot = read_push_snapshot(repo)
            upstream = git_output(repo, ["rev-parse", "--verify", "@{upstream}"]).strip()
        except (CommandFailed, ValueError):
            result["outgoing"] = {"check_status": "not-checked", "basis": "cached-upstream",
                                  "reason": "No supported local push mapping or cached upstream; outgoing history unchecked."}
            statuses.append("incomplete")
        else:
            outgoing = scan(repo, policy, material="outgoing", refs=[upstream, snapshot.tip],
                            reference_names=(snapshot.branch, snapshot.destination))
            result["outgoing"] = {"check_status": outgoing.check_status, "basis": "cached-upstream",
                                  "security": outgoing.record()}
            statuses.append(outgoing.check_status)
            if read_push_snapshot(repo) != snapshot or git_output(repo, ["rev-parse", "--verify", "@{upstream}"]).strip() != upstream:
                result["gaps"].append({"where": "advice", "reason": "Local outgoing scope changed during checking; rerun."})
        if before != _revision(repo) or not _same_policy(policy, load_policy(repo, home=home, legacy_policy=legacy_policy)):
            result["gaps"].append({"where": "advice", "reason": "HEAD, index or policy changed during checking; rerun."})
        if expected_settings is not None:
            expected_settings.verify()
        result["check_status"] = next((status for status in ("incomplete", "blocked", "review-required")
                                       if status in statuses), "passed")
        if result["gaps"]:
            result["check_status"] = "incomplete"
    except (SettingsError, CommandFailed, OSError, ValueError):
        result["gaps"].append({"where": "advice", "reason": "Security scope, policy or material could not be checked; no clearance."})
        result["check_status"] = "incomplete"
    return result


def inspect_paths(entries, *, settings_home=None, legacy_policy=False, expected_settings=None):
    """Check explicit (repo id, checkout path) pairs, retaining duplicate checkouts separately."""
    return [{"repo_id": repo_id, "checkout": number,
             "security": inspect_advice(path, settings_home=settings_home, legacy_policy=legacy_policy,
                                         expected_settings=expected_settings)}
            for number, (repo_id, path) in enumerate(entries, 1)]


def inspect_registered(payload, checkouts, *, settings_home=None, expected_settings=None):
    """Local UI boundary: accept a known repo id, never a client-supplied filesystem path.

    checkouts(id) supplies every locally observed copy. No findings are persisted or shared;
    the response is the same local-only masked advice used by the CLI.
    """
    if (not isinstance(payload, dict) or set(payload) != {"repo_id"} or
            not isinstance(payload["repo_id"], str) or not payload["repo_id"]):
        raise ValueError("select one known repository id")
    paths = list(checkouts(payload["repo_id"]))
    if not paths:
        raise ValueError("repository has no locally observed checkout")
    return {"message": "Local security advice; cached refs, not action clearance.",
            "local_security": inspect_paths(((payload["repo_id"], path) for path in paths), settings_home=settings_home,
                                             expected_settings=expected_settings),
            "artifacts": []}


def render_advice(records):
    """Compact safe overview plus actionable masked findings; no raw source or native errors."""
    from Special.security._findings import render_record

    lines = ["Local security advice (cached refs; not action clearance):"]
    for entry in records:
        result = entry["security"]
        lines.append(f"  Checkout {entry['checkout']}: {result['check_status']}")
        for report in (result.get("working_tree"), (result.get("outgoing") or {}).get("security")):
            if report is not None and (report.get("findings") or report.get("gaps")):
                lines.append(render_record(report))
        outgoing = result.get("outgoing") or {}
        if outgoing.get("reason"):
            lines.append("  " + outgoing["reason"])
        for gap in result["gaps"]:
            lines.append("  " + gap["reason"])
    return "\n".join(lines)
