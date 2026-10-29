"""Policy-gated publication against disposable local bare repositories only.

    python tests/security/test_push_gate.py

Real Git commits/fetches/pushes stay inside the temporary fixture. No host authentication,
network endpoint, installed scanner, live hook installation or actual user settings are involved.
"""
from __future__ import annotations

import io
import json
import os
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

from Basic._run import CommandFailed, Result
from Basic.push import push_snapshot
from Special._archive.plan import build_publish_plan
from Special._archive.sync import apply_publish, collect_publish_candidates
from Special.security import _push
import gitso


class PushGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="push-gate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.archive = self.root / "archive"
        self.repo = self.archive / "project"
        self.bare = self.root / "remote.git"
        self.home = self.root / "profile"
        self.home.mkdir()
        self.archive.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home),
                                              "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                              "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.git(self.root, "clone", "-q", str(self.bare), str(self.repo))
        self.identity(self.repo)
        self.commit("base.txt", "ordinary baseline")
        self.git(self.repo, "push", "-qu", "origin", "main")
        self.base = self.tip(self.bare)
        self.document = {"schema_version": 2, "defaults": {"security": {
            "never_publish": ["private-marker"], "local_never_publish": ["machine-marker"]}}}
        self.save_settings()

    def git(self, repo, *arguments):
        result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def identity(self, repo):
        self.git(repo, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(repo, "config", "user.name", "orbit-user")
        self.git(repo, "config", "commit.gpgsign", "false")
        self.git(repo, "config", "core.autocrlf", "false")

    def commit(self, name, text, message="fixture change", repo=None):
        repo = repo or self.repo
        path = repo / name
        path.write_text(text, encoding="utf-8")
        self.git(repo, "add", "--", name)
        self.git(repo, "commit", "-qm", message)

    def tip(self, repo=None):
        return self.git(repo or self.repo, "rev-parse", "refs/heads/main")

    def save_settings(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def publish(self, snapshot=None):
        return _push.publish_checked(snapshot or _push.read_push_snapshot(self.repo), settings_home=self.home)

    def advance_remote(self):
        peer = self.root / "peer"
        self.git(self.root, "clone", "-q", str(self.bare), str(peer))
        self.identity(peer)
        self.commit("peer.txt", "peer change", repo=peer)
        self.git(peer, "push", "-q", "origin", "main")

    def test_clean_outgoing_snapshot_reaches_only_its_destination(self):
        self.commit("clean.txt", "ordinary new work")
        snapshot = _push.read_push_snapshot(self.repo)
        result = self.publish(snapshot)
        self.assertEqual(result.status, "pushed", result.record())
        self.assertEqual(self.tip(self.bare), snapshot.tip)
        self.assertEqual(result.report.commits, 1)
        self.assertEqual(result.report.refs, {"base": self.base, "tip": snapshot.tip})
        self.assertNotIn(snapshot.endpoint, repr(snapshot))

    def test_exact_master_and_machine_blocks_hold_publication_without_disclosure(self):
        for marker in ("private-marker", "machine-marker"):
            self.commit("data.txt", marker)
            result = self.publish()
            self.assertEqual(result.status, "blocked")
            self.assertEqual(self.tip(self.bare), self.base)
            self.assertNotIn(marker, json.dumps(result.record()))
            self.assertNotIn(marker, result.report.summary())

    def test_introduce_then_remove_is_still_outgoing_history(self):
        self.commit("data.txt", "private-marker")
        self.commit("data.txt", "ordinary now")
        result = self.publish()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.report.commits, 2)
        self.assertEqual(self.tip(self.bare), self.base)

    def test_removal_of_value_already_in_remote_baseline_can_be_published(self):
        self.commit("legacy.txt", "private-marker")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.commit("legacy.txt", "removed")
        result = self.publish()
        self.assertEqual(result.status, "pushed", result.record())
        self.assertFalse(result.report.actionable)

    def test_unrelated_private_branch_is_not_part_of_outgoing_range(self):
        self.git(self.repo, "checkout", "-qb", "private-only")
        self.commit("other.txt", "private-marker")
        self.git(self.repo, "checkout", "-q", "main")
        self.commit("clean.txt", "ordinary")
        result = self.publish()
        self.assertEqual(result.status, "pushed", result.record())
        self.assertEqual(self.git(self.bare, "for-each-ref", "--format=%(refname)"), "refs/heads/main")

    def test_high_confidence_credential_pattern_blocks(self):
        value = "ghp_" + "aB12" * 9
        self.commit("data.txt", value)
        result = self.publish()
        self.assertEqual(result.status, "blocked")
        self.assertIn("high", {finding["severity"] for finding in result.record()["security"]["findings"]})
        self.assertNotIn(value, json.dumps(result.record()))
        self.assertEqual(self.tip(self.bare), self.base)

    def test_uncertain_candidate_requires_review_instead_of_silent_push(self):
        self.commit("data.txt", '{} = "{}"'.format("password", "synthetic-candidate-123"))
        result = self.publish()
        self.assertEqual(result.status, "review-required")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_reviewed_safe_value_allows_a_known_fixture_candidate(self):
        self.commit("data.txt", '{} = "{}"'.format("password", "synthetic-candidate-123"))
        self.document["defaults"]["security"]["safe_values"] = ["synthetic-candidate-123"]
        self.save_settings()
        result = self.publish()
        self.assertEqual(result.status, "pushed", result.record())

    def test_quiet_generic_path_does_not_block(self):
        # Deliberately invented documentation path, not an actual user identity.
        self.commit("readme.txt", "/".join(("", "home", "documentation-fixture")))
        result = self.publish()
        self.assertEqual(result.status, "pushed", result.record())
        self.assertTrue(any(item.classification == "quiet" for item in result.report.findings))

    def test_selected_missing_engine_is_incomplete_and_none_needs_no_engine(self):
        self.commit("clean.txt", "ordinary")
        self.document["defaults"]["security"]["engines"] = ["gitleaks"]
        self.save_settings()
        with patch("Special.security._engines.shutil.which", return_value=None):
            result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.tip(self.bare), self.base)
        self.document["defaults"]["security"]["engines"] = []
        self.save_settings()
        with patch("Special.security._engines._execute", side_effect=AssertionError("unexpected scanner")):
            self.assertEqual(self.publish().status, "pushed")

    def test_failed_selected_engine_is_incomplete_without_error_disclosure(self):
        self.commit("clean.txt", "ordinary")
        self.document["defaults"]["security"]["engines"] = ["gitleaks"]
        self.save_settings()
        with patch("Special.security._engines.shutil.which", return_value=sys.executable), \
             patch("Special.security._engines._execute", side_effect=CommandFailed("private-marker raw stderr")):
            result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.tip(self.bare), self.base)
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_binary_coverage_gap_holds_publication(self):
        (self.repo / "binary.bin").write_bytes(b"\0encoded fixture")
        self.git(self.repo, "add", "--", "binary.bin")
        self.git(self.repo, "commit", "-qm", "binary fixture")
        result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertTrue(result.report.gaps)
        self.assertEqual(self.tip(self.bare), self.base)

    def test_selected_remote_need_not_be_named_origin(self):
        self.git(self.repo, "remote", "rename", "origin", "primary")
        self.commit("clean.txt", "ordinary")
        self.assertEqual(self.publish().status, "pushed")
        self.assertEqual(self.tip(self.bare), self.tip())

    def test_existing_push_hook_is_respected(self):
        self.commit("clean.txt", "ordinary")
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = self.publish()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_partial_clone_gap_stops_material_reads(self):
        self.commit("clean.txt", "ordinary")
        self.git(self.repo, "config", "remote.origin.promisor", "true")
        with patch.object(_push, "fetch", return_value=Result([], 0)), \
             patch("Special.security._material.read_blobs", side_effect=AssertionError("unexpected blob read")):
            result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_invalid_or_excluded_policy_stops_before_fetch(self):
        self.commit("clean.txt", "ordinary")
        snapshot = _push.read_push_snapshot(self.repo)
        for document in ("private-invalid-json", {"schema_version": 2, "defaults": {
                "scope": {"exclude_paths": [str(self.repo)]}}}):
            (self.home / "settings.json").write_text(document if isinstance(document, str) else json.dumps(document))
            with patch.object(_push, "fetch", side_effect=AssertionError("unexpected remote access")):
                result = self.publish(snapshot)
            self.assertEqual(result.status, "incomplete")
            self.assertNotIn("private-invalid-json", json.dumps(result.record()))
        self.assertEqual(self.tip(self.bare), self.base)

    def test_changed_head_since_plan_is_refused_before_fetch(self):
        self.commit("clean.txt", "ordinary")
        snapshot = _push.read_push_snapshot(self.repo)
        self.commit("newer.txt", "unreviewed")
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            result = self.publish(snapshot)
        self.assertEqual(result.status, "stale")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_changed_endpoint_since_plan_is_refused_before_fetch(self):
        self.commit("clean.txt", "ordinary")
        snapshot = _push.read_push_snapshot(self.repo)
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "different.git"))
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            self.assertEqual(self.publish(snapshot).status, "stale")

    def test_source_changed_during_check_is_refused(self):
        self.commit("clean.txt", "ordinary")
        original_scan = _push.scan

        def scan(*args, **kwargs):
            report = original_scan(*args, **kwargs)
            self.commit("newer.txt", "private-marker")
            return report

        with patch.object(_push, "scan", side_effect=scan):
            result = self.publish()
        self.assertEqual(result.status, "stale")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_replacement_ancestry_added_during_check_holds_publication(self):
        self.commit("clean.txt", "ordinary")
        original_scan = _push.scan

        def scan(*args, **kwargs):
            report = original_scan(*args, **kwargs)
            self.git(self.repo, "replace", self.tip(), self.base)
            return report

        with patch.object(_push, "scan", side_effect=scan):
            result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_policy_changed_during_check_is_refused_even_with_same_counts(self):
        self.commit("clean.txt", "ordinary")
        original_scan = _push.scan

        def scan(*args, **kwargs):
            report = original_scan(*args, **kwargs)
            self.document["defaults"]["security"]["never_publish"] = ["different-marker"]
            self.save_settings()
            return report

        with patch.object(_push, "scan", side_effect=scan):
            result = self.publish()
        self.assertEqual(result.status, "stale")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_deleted_settings_after_check_cannot_silently_become_fresh_defaults(self):
        self.document = {"schema_version": 2}
        self.save_settings()
        self.commit("clean.txt", "ordinary")
        original_scan = _push.scan

        def scan(*args, **kwargs):
            report = original_scan(*args, **kwargs)
            (self.home / "settings.json").unlink()
            return report

        with patch.object(_push, "scan", side_effect=scan):
            result = self.publish()
        self.assertEqual(result.status, "stale")
        self.assertTrue(result.report.gaps)
        self.assertEqual(self.tip(self.bare), self.base)

    def test_remote_changed_during_check_is_refused(self):
        self.commit("clean.txt", "ordinary")
        original_scan = _push.scan

        def scan(*args, **kwargs):
            report = original_scan(*args, **kwargs)
            self.advance_remote()
            return report

        with patch.object(_push, "scan", side_effect=scan):
            result = self.publish()
        self.assertEqual(result.status, "stale")
        self.assertNotEqual(self.tip(self.bare), self.tip())

    def test_diverged_remote_before_check_is_incomplete_not_forced(self):
        self.commit("clean.txt", "ordinary")
        snapshot = _push.read_push_snapshot(self.repo)
        self.advance_remote()
        remote_tip = self.tip(self.bare)
        self.assertEqual(self.publish(snapshot).status, "incomplete")
        self.assertEqual(self.tip(self.bare), remote_tip)

    def test_different_push_url_or_multiple_destinations_require_review(self):
        self.git(self.repo, "remote", "set-url", "--push", "origin", str(self.root / "other.git"))
        with self.assertRaises((CommandFailed, ValueError)):
            _push.read_push_snapshot(self.repo)
        self.git(self.repo, "config", "--unset-all", "remote.origin.pushurl")
        self.git(self.repo, "remote", "set-url", "--add", "origin", str(self.root / "other.git"))
        with self.assertRaises((CommandFailed, ValueError)):
            _push.read_push_snapshot(self.repo)

    def test_a_second_url_rewrite_cannot_redirect_the_pinned_endpoint(self):
        self.git(self.repo, "config", f"url.{self.bare}.insteadOf", "fixture-alias:")
        self.git(self.repo, "remote", "set-url", "origin", "fixture-alias:")
        self.assertEqual(_push.read_push_snapshot(self.repo).endpoint, str(self.bare))
        self.git(self.repo, "config", f"url.{self.root / 'other.git'}.insteadOf", str(self.bare))
        with self.assertRaisesRegex(ValueError, "another URL rewrite"):
            _push.read_push_snapshot(self.repo)

    def test_detached_branch_is_not_an_action_snapshot(self):
        self.git(self.repo, "checkout", "--detach", "-q")
        with self.assertRaises((CommandFailed, ValueError)):
            _push.read_push_snapshot(self.repo)

    def test_snapshot_primitive_does_not_publish_matching_branches_or_followed_tags(self):
        self.commit("clean.txt", "ordinary")
        approved_tip = self.tip()
        self.git(self.repo, "tag", "-am", "private-marker", "private-tag")
        self.git(self.repo, "branch", "other")
        self.git(self.repo, "config", "push.default", "matching")
        self.git(self.repo, "config", "push.followTags", "true")
        self.git(self.repo, "config", "remote.origin.mirror", "true")
        self.git(self.repo, "config", "remote.origin.push", "refs/heads/*:refs/heads/*")
        result = push_snapshot(self.repo, str(self.bare), approved_tip, "refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.bare, "for-each-ref", "--format=%(refname)"), "refs/heads/main")

    def test_fixed_tip_survives_a_last_moment_local_branch_change(self):
        self.commit("clean.txt", "ordinary")
        snapshot = _push.read_push_snapshot(self.repo)
        original_push = _push.push_snapshot

        def push(*args, **kwargs):
            self.commit("newer.txt", "private-marker")
            return original_push(*args, **kwargs)

        with patch.object(_push, "push_snapshot", side_effect=push):
            result = self.publish(snapshot)
        self.assertEqual(result.status, "pushed", result.record())
        self.assertEqual(self.tip(self.bare), snapshot.tip)
        self.assertNotEqual(self.tip(), snapshot.tip)

    def test_raw_fetch_errors_never_enter_results(self):
        self.commit("clean.txt", "ordinary")
        with patch.object(_push, "fetch", return_value=Result([], 1, "", "private-marker password")):
            result = self.publish()
        self.assertEqual(result.status, "incomplete")
        self.assertNotIn("private-marker", json.dumps(result.record()))

    def test_archive_entry_point_automatically_uses_gate_and_shows_masked_findings(self):
        self.commit("data.txt", "private-marker")
        plan = build_publish_plan(collect_publish_candidates(self.archive))
        issues, records = [], []
        count = apply_publish(self.archive, plan, issues, pause=0, settings_home=self.home, results=records)
        self.assertEqual(count, 0)
        self.assertEqual(len(issues), 1)
        self.assertIn("finding-", json.dumps(records))
        self.assertNotIn("private-marker", json.dumps(records))
        self.assertEqual(self.tip(self.bare), self.base)

    def test_gitso_publish_yes_does_not_bypass_the_security_gate(self):
        self.commit("data.txt", "private-marker")
        output = io.StringIO()
        with redirect_stdout(output):
            result = gitso.main(["archive-sync", "--root", str(self.archive), "--publish", "--yes",
                                 "--no-report", "--approved-remote-prefix", str(self.root),
                                 "--settings-home", str(self.home)])
        self.assertEqual(result, 1)
        self.assertEqual(self.tip(self.bare), self.base)
        self.assertNotIn("private-marker", output.getvalue())

    def test_legacy_profile_requires_explicit_selection(self):
        self.commit("clean.txt", "ordinary")
        (self.home / "settings.json").unlink()
        (self.home / "security").mkdir()
        (self.home / "security/never_publish.txt").write_text("private-marker\n")
        snapshot = _push.read_push_snapshot(self.repo)
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            self.assertEqual(self.publish(snapshot).status, "incomplete")
        result = _push.publish_checked(snapshot, settings_home=self.home, legacy_policy=True)
        self.assertEqual(result.status, "pushed", result.record())

    def test_direct_preview_is_local_and_has_no_clearance(self):
        self.commit("next.txt", "ordinary")
        before = self.tip(self.bare)
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")), \
             patch.object(_push, "_remote_tip", side_effect=AssertionError("unexpected remote query")), \
             patch.object(_push, "scan", side_effect=AssertionError("unexpected scan")):
            result = _push.push_checked(self.repo, settings_home=self.home)
        self.assertEqual(result.status, "planned", result.record())
        self.assertIsNone(result.record()["security"])
        self.assertEqual(len(result.plan_id), 64)
        self.assertEqual(self.tip(self.bare), before)

    def test_direct_apply_requires_current_plan_before_fetch(self):
        self.commit("next.txt", "ordinary")
        preview = _push.push_checked(self.repo, settings_home=self.home)
        self.commit("later.txt", "another change")
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            result = _push.push_checked(self.repo, settings_home=self.home, apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "approval-required")
        self.assertNotEqual(result.plan_id, preview.plan_id)
        self.assertEqual(self.tip(self.bare), self.base)

    def test_direct_policy_change_invalidates_approval(self):
        self.commit("next.txt", "ordinary")
        preview = _push.push_checked(self.repo, settings_home=self.home)
        self.document["defaults"]["security"]["never_publish"].append("another-marker")
        self.save_settings()
        with patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            result = _push.push_checked(self.repo, settings_home=self.home, apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "approval-required")

    def test_direct_apply_uses_actual_outgoing_gate(self):
        self.commit("next.txt", "private-marker")
        preview = _push.push_checked(self.repo, settings_home=self.home)
        result = _push.push_checked(self.repo, settings_home=self.home, apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "blocked", result.record())
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertEqual(self.tip(self.bare), self.base)

    def test_direct_clean_push_through_launcher(self):
        self.commit("next.txt", "ordinary")
        args = ["push", str(self.repo), "--settings-home", str(self.home), "--json"]
        preview_output, applied_output = io.StringIO(), io.StringIO()
        with redirect_stdout(preview_output):
            self.assertEqual(gitso.main(args), 0)
        preview = json.loads(preview_output.getvalue())
        with redirect_stdout(applied_output):
            self.assertEqual(gitso.main([*args, "--apply", "--approve", preview["plan_id"]]), 0)
        self.assertEqual(json.loads(applied_output.getvalue())["status"], "pushed")
        self.assertEqual(self.tip(self.bare), self.tip())

    def test_direct_policy_change_between_approval_and_gate_holds_before_fetch(self):
        self.commit("next.txt", "ordinary")
        preview = _push.push_checked(self.repo, settings_home=self.home)
        real_publish = _push.publish_checked
        def changed(snapshot, **kwargs):
            self.document["defaults"]["security"]["never_publish"].append("another-marker")
            self.save_settings()
            return real_publish(snapshot, **kwargs)
        with patch.object(_push, "publish_checked", side_effect=changed), \
             patch.object(_push, "fetch", side_effect=AssertionError("unexpected fetch")):
            result = _push.push_checked(self.repo, settings_home=self.home, apply=True, approve=preview.plan_id)
        self.assertEqual(result.status, "stale")
        self.assertEqual(self.tip(self.bare), self.base)

    def test_invalid_fixed_push_scope_is_rejected_without_publication(self):
        for repository, tip, destination in (("-danger", self.base, "refs/heads/main"),
                                              (str(self.bare), "HEAD", "refs/heads/main"),
                                              (str(self.bare), self.base, "refs/tags/other")):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                push_snapshot(self.repo, repository, tip, destination)
        self.assertEqual(self.tip(self.bare), self.base)


if __name__ == "__main__":
    unittest.main()
