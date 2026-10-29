"""Internal per-invocation Git hook worker; never install this as a persistent user hook.

The operation supplies GITSO_COMMIT_CONTEXT and a temporary relay. Existing traditional
hooks run through `git hook run` at their original path. The final commit-msg guard checks
the actual active index and message after the user's hooks. Raw native output is captured
by the parent operation, never emitted by the public CLI. Without context, do nothing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from Basic._facts import next_commit_identity
from Basic._run import run
from Special._settings import SettingsError
from Special.security._commit import state
from Special.security._commit.operation import _check
from Special.security._me import load_policy


def _fresh(context, repo):
    proposal = context["state"]
    state.constraints(repo)
    policy = load_policy(repo, home=Path(context["home"]), legacy_policy=context["legacy_policy"])
    if (state.head(repo) != proposal["head"] or state.policy_revision(policy) != proposal["policy"] or
            state.digest(next_commit_identity(repo)) != state.digest(proposal["identities"]) or
            state.hook_state(repo, proposal["hooks"])[1] != proposal["hook_revisions"]):
        raise SettingsError("proposal state changed")
    return policy


def _fail(path, context, status, event, reason):
    context["failure"] = {"status": status, "event": event}
    report = context.get("report")
    if report is not None:
        report["gaps"].append({"where": "commit guard", "reason": reason})
        report["coverage"], report["check_status"] = "incomplete", "incomplete"
    state.write_context(path, context)
    return 1


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    context = None
    selected = os.environ.get(state.CONTEXT_ENV)
    if not selected or not arguments or arguments[0] not in state.HOOKS:
        return 2
    path, event = Path(selected), arguments[0]
    try:
        context = state.read_context(path)
        repo = Path(context["state"]["repo"])
        if Path.cwd().resolve() != repo.resolve():
            raise SettingsError("unexpected hook working directory")
        if event != "post-commit":
            _fresh(context, repo)
            if event == "pre-commit" and state.index(repo) != context["expected_index"]:
                return _fail(path, context, "stale", event, "proposed index changed before hooks; preview again")
        original = run(["git", "-c", "core.hooksPath=" + context["state"]["hooks"],
                        "hook", "run", "--ignore-missing", event, "--", *arguments[1:]],
                       cwd=repo, timeout=120)
        # These streams terminate inside Basic.run's captured result in the parent process.
        sys.stdout.write(original.stdout)
        sys.stderr.write(original.stderr)
        if original.returncode:
            if event == "post-commit":
                context["post_hook_failed"] = True
                state.write_context(path, context)
                return original.returncode
            context["failure"] = {"status": "hook-rejected", "event": event}
            state.write_context(path, context)
            return 1
        if event == "commit-msg":
            policy = _fresh(context, repo)
            if len(arguments) != 2:
                raise SettingsError("missing native message file")
            message = Path(arguments[1]).read_bytes().decode("utf-8")
            manifest = state.index(repo)
            report = _check(repo, policy, state.index_files(repo, context["state"]["paths"], manifest),
                            message, next_commit_identity(repo))
            context["report"] = report.record()
            if report.check_status != "passed":
                context["failure"] = {"status": report.check_status, "event": event}
                state.write_context(path, context)
                return 1
            _fresh(context, repo)
            if state.index(repo) != manifest:
                return _fail(path, context, "stale", event, "index changed during checking; preview again")
            if manifest != context["expected_index"] or state.digest(message) != context["expected_message"]:
                return _fail(path, context, "stale", event, "a hook changed approved contents or message; preview again")
            context["guard_seen"] = True
            state.write_context(path, context)
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        if context is not None:
            try:
                return _fail(path, context, "incomplete", event, "commit guard could not revalidate state; commit held")
            except (OSError, ValueError, TypeError, KeyError):
                pass
        sys.stderr.write("Commit check could not finish.\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
