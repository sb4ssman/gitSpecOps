"""Checked commits in disposable Git repositories only; no real repository commits or hooks.

    python tests/security/test_commit_gate.py

Native Git/hooks run in the temporary fixtures. Optional scanners are mocked when selected.
"""
from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special.security._commit import operation, state
from Special.security._commit.operation import commit_checked
import gitso


class CommitGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="commit-gate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.home = self.root / "repo", self.root / "profile"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home),
                                              "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                              "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "orbit-user")
        self.git("config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        for name in ("a.txt", "b.txt", "delete.txt"):
            self.write(name, "baseline\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial fixture")
        self.base = self.head()
        self.document = {"schema_version": 2, "defaults": {"security": {
            "never_publish": ["private-marker"], "local_never_publish": ["machine-marker"]}}}
        self.save_settings()

    def git(self, *arguments, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *arguments], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode() if isinstance(text, str) else text)

    def save_settings(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def check(self, paths=None, message="checked fixture", **kwargs):
        return commit_checked(self.repo, ["a.txt"] if paths is None else paths, message,
                              settings_home=self.home, **kwargs)

    def apply(self, paths=None, message="checked fixture"):
        preview = self.check(paths, message)
        self.assertEqual(preview.status, "ready", preview.record())
        return self.check(paths, message, apply=True, approve=preview.plan_id)

    def hook(self, event, body, directory=None):
        path = (directory or self.repo / ".git/hooks") / event
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("#!/bin/sh\n" + body + "\n").encode())
        path.chmod(0o755)

    def test_clean_commit_uses_checked_named_contents(self):
        self.write("a.txt", "ordinary new contents\n")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertTrue(result.committed)
        self.assertNotEqual(self.head(), self.base)
        self.assertEqual(self.git("show", "HEAD:a.txt"), "ordinary new contents")
        self.assertEqual(self.git("show", "-s", "--format=%s", "HEAD"), "checked fixture")
        self.assertFalse(self.git("status", "--porcelain"))

    def test_unrelated_staged_work_is_preserved_and_not_committed(self):
        self.write("b.txt", "unrelated staged work\n")
        self.git("add", "--", "b.txt")
        self.write("a.txt", "selected whole working file\n")
        before = state.index(self.repo)["b.txt"]
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(self.git("show", "HEAD:b.txt"), "baseline")
        self.assertEqual(state.index(self.repo)["b.txt"], before)
        self.assertIn("b.txt", self.git("diff", "--cached", "--name-only"))

    def test_preview_creates_no_commit_index_objects_or_hook_configuration(self):
        self.write("a.txt", "ordinary proposal")
        index = (self.repo / ".git/index").read_bytes()
        config = (self.repo / ".git/config").read_bytes()
        objects = set((self.repo / ".git/objects").rglob("*"))
        hooks = set((self.repo / ".git/hooks").iterdir())
        result = self.check()
        self.assertEqual(result.status, "ready", result.record())
        self.assertFalse(result.committed)
        self.assertEqual(self.head(), self.base)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual((self.repo / ".git/config").read_bytes(), config)
        self.assertEqual(set((self.repo / ".git/objects").rglob("*")), objects)
        self.assertEqual(set((self.repo / ".git/hooks").iterdir()), hooks)

    def test_raw_prohibited_values_block_before_staging_and_remain_masked(self):
        original = (self.repo / ".git/index").read_bytes()
        for marker in ("private-marker", "machine-marker"):
            self.write("a.txt", marker)
            result = self.check()
            self.assertEqual(result.status, "blocked")
            self.assertIsNone(result.plan_id)
            self.assertNotIn(marker, json.dumps(result.record()))
            self.assertNotIn(marker, result.summary())
            self.assertEqual(self.head(), self.base)
            self.assertEqual((self.repo / ".git/index").read_bytes(), original)

    def test_prohibited_message_is_checked_before_staging(self):
        self.write("a.txt", "ordinary")
        result = self.check(message="private-marker")
        self.assertEqual(result.status, "blocked")
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertEqual(self.head(), self.base)

    def test_effective_author_and_committer_identity_are_checked(self):
        self.write("a.txt", "ordinary")
        with patch.dict(os.environ, {"GIT_AUTHOR_EMAIL": "private-marker@fixture.test"}):
            result = self.check()
        self.assertEqual(result.status, "blocked")
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertEqual(self.head(), self.base)

    def test_unrelated_staged_private_bytes_are_not_scanned_or_committed(self):
        self.write("b.txt", "private-marker")
        self.git("add", "b.txt")
        before = state.index(self.repo)["b.txt"]
        self.write("a.txt", "ordinary selected data")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(self.git("show", "HEAD:b.txt"), "baseline")
        self.assertEqual(state.index(self.repo)["b.txt"], before)

    def test_partly_staged_selected_file_uses_whole_working_tree_content(self):
        self.write("a.txt", "earlier staged selection")
        self.git("add", "a.txt")
        self.write("a.txt", "whole current selected file")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(self.git("show", "HEAD:a.txt"), "whole current selected file")

    def test_add_modify_delete_share_the_named_scope(self):
        self.write("a.txt", "modified")
        self.write("new name.txt", "new file")
        (self.repo / "delete.txt").unlink()
        result = self.apply(["a.txt", "new name.txt", "delete.txt"])
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()),
                         {"a.txt", "new name.txt", "delete.txt"})

    def test_removing_a_prohibited_old_path_does_not_reintroduce_it(self):
        self.write("private-marker.txt", "old fixture")
        self.git("add", "private-marker.txt")
        self.git("commit", "-qm", "old fixture")
        (self.repo / "private-marker.txt").unlink()
        result = self.apply(["private-marker.txt"])
        self.assertEqual(result.status, "committed", result.record())
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_exact_approval_is_required_before_apply_changes_the_index(self):
        self.write("a.txt", "ordinary")
        before = (self.repo / ".git/index").read_bytes()
        result = self.check(apply=True, approve="wrong-id")
        self.assertEqual(result.status, "approval-required")
        self.assertEqual(self.head(), self.base)
        self.assertEqual((self.repo / ".git/index").read_bytes(), before)

    def test_source_message_policy_and_unrelated_staging_change_the_plan(self):
        self.write("a.txt", "ordinary")
        old = self.check().plan_id
        self.write("a.txt", "changed selected data")
        self.assertEqual(self.check(apply=True, approve=old).status, "approval-required")
        old = self.check().plan_id
        self.assertEqual(self.check(message="other message", apply=True, approve=old).status, "approval-required")
        old = self.check().plan_id
        self.document["defaults"]["security"]["never_publish"] = ["different-marker"]
        self.save_settings()
        self.assertEqual(self.check(apply=True, approve=old).status, "approval-required")
        old = self.check().plan_id
        self.write("b.txt", "other staged data")
        self.git("add", "b.txt")
        self.assertEqual(self.check(apply=True, approve=old).status, "approval-required")
        self.assertEqual(self.head(), self.base)

    def test_pre_commit_hook_can_reject_without_private_output_feedback(self):
        self.write("a.txt", "ordinary")
        self.hook("pre-commit", "echo private-marker >&2\nexit 1")
        result = self.apply()
        self.assertEqual(result.status, "hook-rejected", result.record())
        self.assertEqual(result.failed_hook, "pre-commit")
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertNotIn("private-marker", result.summary())
        self.assertEqual(self.head(), self.base)

    def test_prepare_message_hook_secret_is_checked_before_native_commit(self):
        self.write("a.txt", "ordinary")
        self.hook("prepare-commit-msg", 'printf "\\nprivate-marker\\n" >> "$1"')
        result = self.apply()
        self.assertEqual(result.status, "blocked", result.record())
        self.assertEqual(self.head(), self.base)
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_commit_message_hook_secret_is_checked_after_that_hook(self):
        self.write("a.txt", "ordinary")
        self.hook("commit-msg", 'printf "\\nprivate-marker\\n" >> "$1"')
        result = self.apply()
        self.assertEqual(result.status, "blocked", result.record())
        self.assertEqual(self.head(), self.base)

    def test_hook_staging_secret_in_named_file_is_checked(self):
        self.write("a.txt", "ordinary")
        self.hook("pre-commit", 'printf "private-marker" > a.txt\ngit add -- a.txt')
        result = self.apply()
        self.assertEqual(result.status, "blocked", result.record())
        self.assertEqual(self.head(), self.base)
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_safe_hook_formatting_requires_review_then_can_be_committed(self):
        self.write("a.txt", "unformatted")
        self.hook("pre-commit", 'printf "formatted" > a.txt\ngit add -- a.txt')
        result = self.apply()
        self.assertEqual(result.status, "stale", result.record())
        self.assertEqual(self.head(), self.base)
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(self.git("show", "HEAD:a.txt"), "formatted")

    def test_hook_cannot_add_an_unapproved_file_to_the_commit(self):
        self.write("a.txt", "ordinary")
        self.hook("pre-commit", 'printf "extra" > extra.txt\ngit add -- extra.txt')
        result = self.apply()
        self.assertEqual(result.status, "stale", result.record())
        self.assertEqual(self.head(), self.base)

    def test_all_traditional_hooks_keep_their_order_and_original_location(self):
        self.write("a.txt", "ordinary")
        for event in state.HOOKS:
            self.hook(event, f'printf "{event}\\n" >> hook-events.txt')
        config = (self.repo / ".git/config").read_bytes()
        revisions = state.hook_state(self.repo)
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual((self.repo / "hook-events.txt").read_text().splitlines(), list(state.HOOKS))
        self.assertEqual((self.repo / ".git/config").read_bytes(), config)
        self.assertEqual(state.hook_state(self.repo), revisions)

    def test_existing_custom_hooks_path_remains_configured(self):
        directory = self.root / "custom hooks"
        self.hook("pre-commit", 'printf "ran" > hook-observed.txt', directory)
        self.git("config", "core.hooksPath", str(directory))
        self.write("a.txt", "ordinary")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertTrue((self.repo / "hook-observed.txt").exists())
        self.assertEqual(self.git("config", "core.hooksPath"), str(directory))

    def test_post_commit_hook_failure_does_not_hide_created_commit(self):
        self.write("a.txt", "ordinary")
        self.hook("post-commit", "exit 1")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertTrue(result.committed)
        self.assertIn("Post-commit", result.message)

    def test_selected_missing_engine_holds_preview_without_staging(self):
        self.write("a.txt", "ordinary")
        self.document["defaults"]["security"]["engines"] = ["gitleaks"]
        self.save_settings()
        before = (self.repo / ".git/index").read_bytes()
        with patch("Special.security._engines.shutil.which", return_value=None):
            result = self.check()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual((self.repo / ".git/index").read_bytes(), before)

    def test_binary_gap_holds_preview_without_staging(self):
        self.write("a.txt", b"\0encoded bytes")
        result = self.check()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.head(), self.base)

    def test_literal_paths_do_not_expand_to_other_files(self):
        for path in (".", "../other", "/absolute", "a.txt/../b.txt", ":(glob)*", ".git/config", "missing.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.check([path]).status, "incomplete")
        self.assertEqual(self.head(), self.base)

    def test_merge_state_and_new_configured_hook_chains_are_refused(self):
        self.write("a.txt", "ordinary")
        marker = self.repo / ".git/MERGE_HEAD"
        marker.write_text(self.base + "\n")
        self.assertEqual(self.check().status, "incomplete")
        marker.unlink()
        self.git("config", "hook.fixture.event", "pre-commit")
        self.assertEqual(self.check().status, "incomplete")
        self.assertEqual(self.head(), self.base)

    def test_no_selected_change_is_not_an_empty_commit(self):
        result = self.apply()
        self.assertEqual(result.status, "nothing-to-commit", result.record())
        self.assertEqual(self.head(), self.base)

    def test_native_verification_failure_reports_a_created_commit(self):
        self.write("a.txt", "ordinary")
        preview = self.check()
        with patch.object(operation, "commits", side_effect=OSError("private-marker")):
            result = self.check(apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "partial", result.record())
        self.assertTrue(result.committed)
        self.assertNotEqual(self.head(), self.base)
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_gitso_route_previews_and_applies_the_same_operation(self):
        self.write("a.txt", "ordinary")
        arguments = ["commit", str(self.repo), "a.txt", "-m", "checked fixture", "--settings-home", str(self.home), "--json"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(gitso.main(arguments), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["status"], "ready")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(gitso.main([*arguments, "--apply", "--approve", preview["plan_id"]]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "committed")

    def test_message_whitespace_is_preserved_verbatim(self):
        self.write("a.txt", "ordinary")
        message = "  heading with spaces  \n\n    body indentation  "
        result = self.apply(message=message)
        self.assertEqual(result.status, "committed", result.record())
        raw = subprocess.run(["git", "-C", str(self.repo), "cat-file", "commit", "HEAD"],
                             check=True, capture_output=True).stdout
        self.assertEqual(raw.split(b"\n\n", 1)[1], (message + "\n").encode())

    def test_clean_filter_output_is_checked_not_just_raw_working_bytes(self):
        self.write("a.txt", "ordinary")
        self.write(".gitattributes", "a.txt filter=fixture\n")
        code = 'import sys; sys.stdin.read(); sys.stdout.write("private-marker")'
        command = shlex.quote(Path(sys.executable).as_posix()) + " -c " + shlex.quote(code)
        self.git("config", "filter.fixture.clean", command)
        preview = self.check()
        self.assertEqual(preview.status, "ready", preview.record())
        result = self.check(apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "blocked", result.record())
        self.assertEqual(self.head(), self.base)
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_settings_lost_during_hooks_do_not_fall_back_to_fresh_defaults(self):
        self.document = {"schema_version": 2}
        self.save_settings()
        self.write("a.txt", "ordinary")
        target = self.home / "settings.json"
        self.assertTrue(target.resolve().is_relative_to(self.root))
        self.hook("pre-commit", "rm -- " + shlex.quote(target.as_posix()))
        result = self.apply()
        self.assertEqual(result.status, "incomplete", result.record())
        self.assertEqual(self.head(), self.base)
        self.assertFalse(target.exists())

    def test_late_source_change_holds_commit_and_preserves_other_staging(self):
        self.write("a.txt", "ordinary")
        self.write("b.txt", "other staged")
        self.git("add", "b.txt")
        before = state.index(self.repo)["b.txt"]
        preview = self.check()
        native = operation.commit

        def changed(*args, **kwargs):
            self.write("a.txt", "private-marker")
            return native(*args, **kwargs)

        with patch.object(operation, "commit", side_effect=changed):
            result = self.check(apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "stale", result.record())
        self.assertEqual(result.security["coverage"], "incomplete")
        self.assertEqual(self.head(), self.base)
        self.assertEqual(state.index(self.repo)["b.txt"], before)

    def test_missing_final_guard_is_reported_as_partial_after_a_native_commit(self):
        self.write("a.txt", "ordinary")
        relay = operation._relay

        def incomplete(directory):
            relay(directory)
            (directory / "commit-msg").write_bytes(b"#!/bin/sh\nexit 0\n")

        with patch.object(operation, "_relay", side_effect=incomplete):
            result = self.apply()
        self.assertEqual(result.status, "partial", result.record())
        self.assertTrue(result.committed)
        self.assertNotEqual(self.head(), self.base)

    def test_native_line_ending_conversion_keeps_working_file_unchanged(self):
        self.git("config", "core.autocrlf", "true")
        self.write("a.txt", b"changed\r\nsecond line\r\n")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual((self.repo / "a.txt").read_bytes(), b"changed\r\nsecond line\r\n")
        stored = subprocess.run(["git", "-C", str(self.repo), "show", "HEAD:a.txt"],
                                capture_output=True, check=True).stdout
        self.assertEqual(stored, b"changed\nsecond line\n")

    def test_unborn_branch_can_create_its_first_checked_commit(self):
        empty = self.root / "empty"
        self.git("init", "-q", "-b", "main", str(empty), cwd=self.root)
        self.repo = empty
        self.git("config", "user.name", "orbit-user")
        self.git("config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git("config", "commit.gpgsign", "false")
        self.write("a.txt", "first content")
        result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")

    def test_detached_head_does_not_create_a_commit(self):
        self.git("checkout", "--detach", "-q")
        self.write("a.txt", "ordinary")
        self.assertEqual(self.check().status, "incomplete")
        self.assertEqual(self.head(), self.base)

    def test_invalid_common_and_explicit_legacy_selection_stay_distinct(self):
        self.write("a.txt", "ordinary")
        path = self.home / "settings.json"
        path.write_text("private-invalid-config")
        self.assertEqual(self.check().status, "incomplete")
        path.unlink()
        (self.home / "security").mkdir()
        (self.home / "security/never_publish.txt").write_text("private-marker\n")
        self.assertEqual(self.check().status, "incomplete")
        preview = self.check(legacy_policy=True)
        self.assertEqual(preview.status, "ready", preview.record())
        result = self.check(legacy_policy=True, apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "committed", result.record())

    def test_hook_edit_changes_the_required_approval(self):
        self.write("a.txt", "ordinary")
        self.hook("pre-commit", "exit 0")
        preview = self.check()
        self.hook("pre-commit", "# edited\nexit 0")
        self.assertEqual(self.check(apply=True, approve=preview.plan_id).status, "approval-required")
        self.assertEqual(self.head(), self.base)

    def test_custom_index_environment_is_not_silently_reinterpreted(self):
        self.write("a.txt", "ordinary")
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(self.root / "other-index")}):
            result = self.check()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.head(), self.base)

    def test_temporary_relay_is_removed_after_the_operation(self):
        self.write("a.txt", "ordinary")
        relay, created = operation._relay, []

        def observe(directory):
            created.append(directory.parent)
            relay(directory)

        with patch.object(operation, "_relay", side_effect=observe):
            result = self.apply()
        self.assertEqual(result.status, "committed", result.record())
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))


if __name__ == "__main__":
    unittest.main()
