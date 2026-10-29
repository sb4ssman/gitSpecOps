"""Policy-aware publication of one approved branch snapshot, composed over Basic.

read_push_snapshot() reads local target facts only. publish_checked(snapshot, ...) is the
explicit action: load policy, recheck, fetch the selected remote, inspect its actual base,
scan base..tip, recheck source/target/policy, then push only that immutable tip and branch.
It never commits, forces, installs a hook or saves settings/reports. Existing hooks still run.

This first supported mapping is a single endpoint with matching upstream/push destination.
Triangular/multiple endpoints, missing bases and unsupported configurations require review.
Results are masked; raw Git/engine errors and endpoint credentials never enter presentation.
Remote and policy rechecks are optimistic, not an atomic transaction with external writers.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from Basic._objects import git_output
from Basic._run import CommandFailed, run_git
from Basic.fetch import fetch
from Basic.push import push_snapshot
from Special._settings import SettingsError, select_home
from Special.security._findings import Report
from Special.security._material import _history_limits, scan
from Special.security._me import load_policy, policy_revision

_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


@dataclass(frozen=True)
class PushSnapshot:
    """Private exact action scope. Equality detects branch/tip/target changes, not just counts."""

    repo: Path = field(repr=False)
    branch: str = field(repr=False)
    tip: str
    remote: str = field(repr=False)
    destination: str = field(repr=False)
    endpoint: str = field(repr=False)


def read_push_snapshot(repo) -> PushSnapshot:
    """Read one local branch's single matching fetch/push mapping; no remote query or writes."""
    repo = Path(repo).absolute()
    branch = git_output(repo, ["symbolic-ref", "-q", "HEAD"]).strip()
    if not branch.startswith("refs/heads/"):
        raise ValueError("a local branch is required")
    fields = git_output(repo, ["for-each-ref", "--format=%(objectname)%00%(upstream:remotename)%00"
                               "%(upstream:remoteref)%00%(push:remotename)%00%(push:remoteref)%00"
                               "%(upstream)%00%(push)", branch]).rstrip("\n").split("\0")
    if len(fields) != 7:
        raise ValueError("a single push mapping is required")
    tip, remote, destination, push_remote, push_destination, upstream_ref, push_ref = fields
    # Some Git versions leave push:remoteref empty in default simple mode, while reporting
    # the exact push tracking ref. Accept that only when it equals the known upstream ref.
    same_destination = push_destination == destination or (not push_destination and
                                                           bool(push_ref) and push_ref == upstream_ref)
    if (_OID.fullmatch(tip) is None or not remote or remote == "." or remote.startswith("-") or
            not destination.startswith("refs/heads/") or
            remote != push_remote or not same_destination):
        raise ValueError("upstream and push destinations must identify the same branch")
    fetch_urls = git_output(repo, ["remote", "get-url", "--all", remote]).splitlines()
    push_urls = git_output(repo, ["remote", "get-url", "--push", "--all", remote]).splitlines()
    if len(fetch_urls) != 1 or fetch_urls != push_urls:
        raise ValueError("one matching fetch/push endpoint is required")
    endpoint = push_urls[0]
    if not endpoint or endpoint.startswith("-") or any(char in endpoint for char in "\0\r\n"):
        raise ValueError("invalid push endpoint")
    # Git interprets a bare relative path as a remote name if a name happens to match it.
    # Pin local paths absolutely; URI and scp-style transports keep their resolved spelling.
    if ":" not in endpoint:
        endpoint = str((repo / endpoint).absolute())
    rewrites = run_git(repo, ["config", "-z", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$"])
    if rewrites.returncode not in (0, 1):
        raise CommandFailed("URL rewrite configuration could not be checked")
    for entry in rewrites.stdout.split("\0"):
        _, separator, prefix = entry.partition("\n")
        if separator and prefix and endpoint.startswith(prefix):
            # get-url already expanded the selected remote. Sending that expansion as an
            # explicit endpoint must not trigger a second rewrite to a different repository.
            raise ValueError("resolved endpoint matches another URL rewrite; review target configuration")
    return PushSnapshot(repo, branch, tip, remote, destination, endpoint)


def _remote_tip(snapshot):
    lines = git_output(snapshot.repo, ["ls-remote", "--refs", "--", snapshot.endpoint,
                                       snapshot.destination], timeout=60).splitlines()
    if len(lines) != 1:
        raise ValueError("an existing destination branch is required")
    fields = lines[0].split("\t")
    if len(fields) != 2 or fields[1] != snapshot.destination or _OID.fullmatch(fields[0]) is None:
        raise ValueError("destination could not be verified")
    return fields[0]


def _same_policy(left, right):
    return policy_revision(left) == policy_revision(right)


@dataclass(frozen=True)
class PushResult:
    """Presentation-safe outcome; callers may separately render the masked scan record."""

    status: str
    message: str
    report: Report | None = field(default=None, repr=False)
    plan_id: str | None = None

    def record(self):
        return {"schema_version": 1, "status": self.status, "message": self.message,
                "security": self.report.record() if self.report is not None else None,
                "plan_id": self.plan_id, "artifacts": []}


def push_checked(repo, *, settings_home=None, legacy_policy=False, apply=False, approve=None):
    """Preview one local push mapping; apply its exact plan through publish_checked.

    Preview reads local scope/policy only, with no fetch, network, file writes or security
    clearance. Apply re-reads the plan before remote access, then the shared publication gate
    checks the actual destination and outgoing history. No arbitrary refspec/force/bypass.
    """
    try:
        home = select_home(settings_home, component="security")[0]
        repo = Path(repo).absolute()
        top = Path(git_output(repo, ["rev-parse", "--show-toplevel"]).strip())
        if repo.resolve() != top.resolve():
            raise SettingsError("select the repository root explicitly")
        policy = load_policy(repo, home=home, legacy_policy=legacy_policy)
        snapshot = read_push_snapshot(repo)
        if policy.gaps:
            return PushResult("incomplete", "Security policy is incomplete; no push plan approved.")
        binding = {"scope": asdict(snapshot), "home": str(home), "legacy_policy": legacy_policy,
                   "policy": {name: getattr(policy, name) for name in
                              ("identities", "safe", "logins", "engines", "exclude_paths", "sources")}}
        plan_id = hashlib.sha256(json.dumps(binding, sort_keys=True, default=str).encode()).hexdigest()
        if not apply:
            return PushResult("planned", "Local push scope selected; outgoing security is not checked until apply.",
                              plan_id=plan_id)
        if approve != plan_id:
            return PushResult("approval-required", "No push: approve the exact current local plan.", plan_id=plan_id)
        result = publish_checked(snapshot, settings_home=home, legacy_policy=legacy_policy, expected_policy=policy)
        return PushResult(result.status, result.message, result.report, plan_id)
    except SettingsError as exc:
        return PushResult("incomplete", str(exc))
    except (CommandFailed, OSError, ValueError):
        return PushResult("incomplete", "Push scope or security settings could not be read; no push performed.")


def publish_checked(snapshot: PushSnapshot, *, settings_home=None, legacy_policy=False, expected_policy=None) -> PushResult:
    """Execute the approved snapshot only after current selected checks pass.

    Uncertain findings hold the push for review; resolve scoped policy and rerun. There is no
    bypass flag. None remains a valid external-engine selection; required selected failures
    are incomplete. Policy loading precedes fetch and other remote access. No raw values print.
    """
    report = None
    try:
        policy = load_policy(snapshot.repo, home=settings_home, legacy_policy=legacy_policy)
        if expected_policy is not None and not _same_policy(expected_policy, policy):
            return PushResult("stale", "Security policy changed after plan approval; preview again.")
        if policy.gaps:
            return PushResult("incomplete", "failed: security policy is incomplete; push held")
        if read_push_snapshot(snapshot.repo) != snapshot:
            return PushResult("stale", "failed: source or destination changed; rebuild the publish plan")
        fetched = fetch(snapshot.repo, snapshot.remote)
        if fetched.returncode != 0:
            return PushResult("incomplete", "failed: fetch failed; push held")
        if read_push_snapshot(snapshot.repo) != snapshot:
            return PushResult("stale", "failed: source or destination changed during fetch; rebuild the publish plan")
        base = _remote_tip(snapshot)
        if base == snapshot.tip:
            return PushResult("already-current", "already current")
        report = scan(snapshot.repo, policy, material="outgoing", refs=[base, snapshot.tip],
                      reference_names=(snapshot.branch, snapshot.destination))
        if report.gaps:
            return PushResult("incomplete", "failed: security checking incomplete; push held", report)
        if report.actionable:
            return PushResult(report.check_status,
                              "failed: security findings block push" if report.check_status == "blocked" else
                              "failed: security findings require review before push", report)
        current_policy = load_policy(snapshot.repo, home=settings_home, legacy_policy=legacy_policy)
        if (not _same_policy(policy, current_policy) or read_push_snapshot(snapshot.repo) != snapshot or
                _remote_tip(snapshot) != base):
            report.gap("publication", "source, destination or policy changed after checking; rerun required")
            return PushResult("stale", "failed: source, destination or policy changed; rerun security checking", report)
        _history_limits(report, snapshot.repo)
        if report.gaps:
            return PushResult("incomplete", "failed: ancestry coverage changed or became incomplete; push held", report)
        pushed = push_snapshot(snapshot.repo, snapshot.endpoint, snapshot.tip, snapshot.destination)
        if pushed.returncode != 0:
            return PushResult("failed", "failed: push refused or failed; inspect Git locally", report)
        return PushResult("pushed", f"pushed {report.commits}", report)
    except SettingsError as exc:
        if report is not None:
            report.gap("policy", "security settings could not be revalidated; push held")
        return PushResult("incomplete", "failed: " + str(exc) + "; push held", report)
    except (CommandFailed, OSError, ValueError):
        return PushResult("incomplete", "failed: push scope or security settings could not be verified; no clean result", report)
