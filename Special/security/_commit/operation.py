"""Checked named-file commit operation. Preview is read-only; apply needs its exact plan id.

commit_checked(repo, paths, message, ...) scans raw inputs, then exact staged blobs and native
commit-hook inputs. Basic.commit still owns Git staging/commit semantics. A per-invocation
relay preserves traditional hooks and refuses unreviewed index/message changes. No persistent
Git settings/hooks, reports or logs are installed. Raw native output remains private backend
data; record()/summary() are the normal human/agent presentation channels.
"""
from __future__ import annotations

import os
import shlex
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from Basic._objects import commits
from Basic._run import CommandFailed
from Basic.commit import COMMITTED, NOTHING_TO_COMMIT, commit
from Special._settings import SettingsError, select_home
from Special.security._commit import state
from Special.security._findings import render_record
from Special.security._material import scan
from Special.security._me import load_policy


@dataclass
class CommitResult:
    """Safe presentation plus intentionally private diagnostics for a local human channel."""

    status: str
    message: str
    plan_id: str | None = None
    committed: bool | None = False
    security: dict | None = field(default=None, repr=False)
    private_native_output: str = field(default="", repr=False)
    failed_hook: str | None = None

    def record(self):
        return {"schema_version": 1, "status": self.status, "message": self.message,
                "plan_id": self.plan_id, "committed": self.committed, "security": self.security,
                "failed_hook": self.failed_hook, "artifacts": []}

    def summary(self):
        return (render_record(self.security) + "\n" if self.security is not None else "") + self.message + (
            "\nPlan: " + self.plan_id if self.plan_id is not None else "") + (
            "\nHook: " + self.failed_hook if self.failed_hook is not None else "")


class Held(Exception):
    def __init__(self, status, message, report=None):
        self.status, self.message, self.report = status, message, report


def _check(repo, policy, files, message, identities):
    return scan(repo, policy, material="proposed", proposal={
        "files": files, "message": message, "identities": identities})


def _hold(report):
    if report.check_status != "passed":
        raise Held(report.check_status, "Commit held: resolve security findings or incomplete checking.", report.record())


def _relay(directory):
    worker = Path(__file__).with_name("hook.py").as_posix()
    for event in state.HOOKS:
        path = directory / event
        command = " ".join(shlex.quote(value) for value in (Path(sys.executable).as_posix(), "-B", worker, event))
        path.write_bytes(("#!/bin/sh\nexec " + command + ' "$@"\n').encode("utf-8"))
        path.chmod(0o700)


def _execute(repo, selected, message, policy, snapshot, home, legacy_policy, plan_id, initial):
    context = {}
    native_output = ""
    with tempfile.TemporaryDirectory(prefix="gitso-commit-") as temporary:
        directory = Path(temporary)
        hooks = directory / "hooks"
        hooks.mkdir()
        _relay(hooks)
        context_path = directory / "context.json"
        env = {state.CONTEXT_ENV: str(context_path)}
        for role, (name, email) in snapshot["identities"].items():
            env[f"GIT_{role.upper()}_NAME"], env[f"GIT_{role.upper()}_EMAIL"] = name, email

        def before_commit():
            current = load_policy(repo, home=home, legacy_policy=legacy_policy)
            state.constraints(repo)
            if (state.head(repo) != snapshot["head"] or state.file_revisions(repo, selected) != snapshot["files"] or
                    state.policy_revision(current) != snapshot["policy"] or
                    state.hook_state(repo) != (snapshot["hooks"], snapshot["hook_revisions"])):
                raise Held("stale", "Commit held: source, policy or hooks changed; preview again.")
            entries = state.index(repo)
            if {key: value for key, value in entries.items() if key not in selected} != {
                    key: value for key, value in snapshot["index"].items() if key not in selected}:
                raise Held("stale", "Commit held: unrelated staged work changed; preview again.")
            report = _check(repo, current, state.index_files(repo, selected, entries), message, snapshot["identities"])
            _hold(report)
            if (state.index(repo) != entries or state.head(repo) != snapshot["head"] or
                    state.policy_revision(load_policy(repo, home=home, legacy_policy=legacy_policy)) != snapshot["policy"]):
                report.gap("proposal", "staged inputs or policy changed while checking")
                raise Held("stale", "Commit held: staged inputs or policy changed.", report.record())
            expected = state.tree(repo, snapshot["head"][1])
            for name in selected:
                expected.pop(name, None)
                if name in entries:
                    expected[name] = entries[name]
            if expected == state.tree(repo, snapshot["head"][1]):
                raise Held("nothing-to-commit", "No selected changes to commit.", report.record())
            context.update(schema_version=1, state=snapshot, home=str(home), legacy_policy=legacy_policy,
                           expected_index=expected, expected_message=state.digest(message if message.endswith("\n") else message + "\n"),
                           guard_seen=False, failure=None, report=report.record())
            state.write_context(context_path, context)

        try:
            native_output = commit(repo, selected, message, env=env, before_commit=before_commit,
                                   hooks_path=hooks, verbatim=True, literal_paths=True, timeout=1800)
        except Held as held:
            security = held.report or initial.record()
            if held.status == "stale":
                security["gaps"].append({"where": "proposal", "reason": held.message})
                security["coverage"], security["check_status"] = "incomplete", "incomplete"
            return CommitResult(held.status, held.message, security=security)
        except (CommandFailed, OSError, ValueError, KeyboardInterrupt):
            try:
                created = state.head(repo) != snapshot["head"]
            except (CommandFailed, OSError, ValueError):
                created = None
            return CommitResult("partial" if created is not False else "incomplete",
                                "Commit invocation could not finish; inspect Git state before retrying.",
                                committed=created, security=initial.record())
        try:
            if context_path.exists():
                context = state.read_context(context_path)
            after = state.head(repo)
        except (CommandFailed, OSError, ValueError):
            return CommitResult("partial", "Commit invocation returned but state could not be verified; inspect locally.",
                                committed=True if native_output == COMMITTED else None,
                                security=initial.record(), private_native_output=native_output)
        changed = after != snapshot["head"]
        if native_output == NOTHING_TO_COMMIT and not changed:
            return CommitResult("nothing-to-commit", "No selected changes to commit.", security=initial.record())
        report = context.get("report", initial.record())
        if native_output != COMMITTED:
            if changed:
                return CommitResult("partial", "Git changed HEAD while reporting failure; inspect locally.",
                                    committed=True, security=report, private_native_output=native_output)
            failure = context.get("failure") or {}
            status = failure.get("status", "failed")
            if status not in ("blocked", "review-required", "incomplete", "stale", "hook-rejected"):
                status = "failed"
            return CommitResult(status, "Commit held by checking, a Git hook or Git; inspect the masked result.",
                                security=report, private_native_output=native_output,
                                failed_hook=failure.get("event") if failure.get("event") in state.HOOKS else None)
        expected_parents = [snapshot["head"][1]] if snapshot["head"][1] is not None else []
        try:
            made = commits(repo, [after[1], "--max-count=1"]) if after[1] is not None else []
            final_tree = state.tree(repo, after[1])
            # Pretty-log parsing trims whitespace; prove the actual stored message.
            stored_message = state.git(repo, ["cat-file", "commit", after[1]]).partition("\n\n")[2]
            expected_message = message if message.endswith("\n") else message + "\n"
        except (CommandFailed, OSError, ValueError):
            return CommitResult("partial", "Git reported a commit but final verification failed; inspect locally.",
                                committed=True if changed else None, security=report, private_native_output=native_output)
        valid = (context.get("guard_seen") is True and after[0] == snapshot["head"][0] and changed and
                 len(made) == 1 and list(made[0].parents) == expected_parents and
                 stored_message == expected_message.replace("\r\n", "\n") and
                 [made[0].author.name, made[0].author.email] == list(snapshot["identities"]["author"]) and
                 [made[0].committer.name, made[0].committer.email] == list(snapshot["identities"]["committer"]) and
                 final_tree == context.get("expected_index"))
        if not valid:
            return CommitResult("partial", "Git created a commit whose final state needs review; nothing was undone.",
                                committed=True if changed else None, security=report, private_native_output=native_output)
        message_result = "Committed the checked named files." + (" Post-commit hook reported a failure." if context.get("post_hook_failed") else "")
        return CommitResult("committed", message_result, plan_id, True, report,
                            private_native_output=native_output)


def commit_checked(repo, paths, message, *, settings_home=None, legacy_policy=False,
                   apply=False, approve=None) -> CommitResult:
    """Preview/execute only explicit files with content-bound approval and shared checks.

    Failed raw preflight leaves the index unchanged. Once apply stages the named paths,
    refusal preserves Basic.commit's staged-on-failure behavior; other staged work is retained.
    Hook changes require a new preview. No commit is pushed or rolled back automatically.
    """
    report = None
    try:
        if any(os.environ.get(key) for key in ("GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                                               "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS",
                                               "GIT_REPLACE_REF_BASE", "GIT_GRAFT_FILE")):
            raise SettingsError("custom Git index/object/pathspec/history environments require compatibility review")
        home = select_home(settings_home, component="security")[0]
        repo = Path(repo).absolute()
        policy = load_policy(repo, home=home, legacy_policy=legacy_policy)
        top = Path(state.git(repo, ["rev-parse", "--show-toplevel"]).strip())
        if top.resolve() != repo.resolve():
            raise SettingsError("select the repository root explicitly")
        selected = state.paths(repo, paths)
        if not isinstance(message, str) or not message.strip() or "\0" in message:
            raise SettingsError("a nonempty text commit message is required")
        snapshot = state.proposal_state(repo, selected, message, policy)
        report = _check(repo, policy, state.raw_files(repo, selected), message, snapshot["identities"])
        _hold(report)
        if state.proposal_state(repo, selected, message, load_policy(repo, home=home, legacy_policy=legacy_policy)) != snapshot:
            report.gap("proposal", "state changed during checking; preview again")
            return CommitResult("stale", "Commit held: proposal changed during checking.", security=report.record())
        plan_id = state.digest(snapshot)
        if not apply:
            return CommitResult("ready", "Selected proposal passed checking; no commit created.", plan_id, security=report.record())
        if approve != plan_id:
            return CommitResult("approval-required", "No commit created: approve this exact current plan.", plan_id, security=report.record())
        return _execute(repo, selected, message, policy, snapshot, home, legacy_policy, plan_id, report)
    except Held as held:
        return CommitResult(held.status, held.message, security=held.report)
    except SettingsError as exc:
        return CommitResult("incomplete", str(exc), security=report.record() if report else None)
    except (CommandFailed, OSError, ValueError, UnicodeError):
        return CommitResult("incomplete", "Commit checking could not finish; no clean result.",
                            security=report.record() if report else None)
