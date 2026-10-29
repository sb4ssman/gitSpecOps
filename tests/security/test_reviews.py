"""Scoped example decisions across real disposable scans, commits and pushes.

All identities, candidates, settings and Git remotes are invented temporary fixtures. These
tests prove exact content/location/repository binding, revocation and refusal of incomplete or
prohibited material without global allowlists or real settings/history/network changes.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()

from Special.security import _material, _push, _reviews
from Special.security._commit.operation import commit_checked
from Special.security._findings import write_report
from Special.security._material import scan
from Special.security._me import load_policy
from Special.security._review_operation import review_finding
import gitso


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="example-reviews-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.bare, self.home = (self.root / name for name in ("repo", "remote.git", "profile"))
        self.home.mkdir()
        env = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home), "GIT_CONFIG_GLOBAL": os.devnull,
                                     "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.git(self.root, "clone", "-q", str(self.bare), str(self.repo))
        for key, value in (("user.name", "orbit-user"), ("user.email", "123+orbit-user@users.noreply.github.com"),
                           ("commit.gpgsign", "false")):
            self.git(self.repo, "config", key, value)
        (self.repo / "base.txt").write_text("ordinary", encoding="utf-8")
        self.git(self.repo, "add", "--", "base.txt")
        self.git(self.repo, "commit", "-qm", "fixture base")
        self.git(self.repo, "push", "-q", "-u", "origin", "main")
        self.base = self.git(self.bare, "rev-parse", "main")
        self.document = {"schema_version": 2, "defaults": {"security": {"never_publish": ["private-marker"]}}}
        self.save_settings()
        self.value = "example-agent" + "@" + "public-domain.org"
        self.body = "Contact: " + self.value + "\n"
        (self.repo / "contact.txt").write_text(self.body, encoding="utf-8")
        self.counter = 0

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()

    def save_settings(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def scan(self, **kwargs):
        return scan(self.repo, load_policy(self.repo, home=self.home), **kwargs)

    def report(self, report=None, check="email address"):
        report = report or self.scan()
        self.counter += 1
        path = self.home / "reports" / f"scan-{self.counter}.json"
        write_report(path, report)
        finding = next(row["finding_id"] for row in report.record()["findings"] if row["check"] == check)
        return path, finding

    def accept(self, source=None, *, reason="Reviewed invented fixture"):
        source = source or self.report()
        plan = review_finding(*source, reason, home=self.home)
        self.assertEqual(plan.status, "planned", plan.record())
        saved = review_finding(*source, reason, home=self.home, apply=True, approve=plan.plan_id)
        self.assertEqual(saved.status, "accepted", saved.record())
        return saved, source

    def revoke(self, source, review_id):
        plan = review_finding(source[0], reason="No longer accepted", home=self.home, revoke=review_id)
        self.assertEqual(plan.status, "planned", plan.record())
        result = review_finding(source[0], reason="No longer accepted", home=self.home,
                                revoke=review_id, apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "revoked", result.record())

    def test_preview_is_masked_and_has_no_writes_or_secret_fingerprint(self):
        source = self.report()
        before = set(self.home.rglob("*"))
        plan = review_finding(*source, "private reason " + self.value, home=self.home)
        self.assertEqual(plan.status, "planned", plan.record())
        self.assertEqual(set(self.home.rglob("*")), before)
        self.assertNotIn(self.value, json.dumps(plan.record()) + repr(plan))
        self.assertNotIn("content_id", json.dumps(self.scan().record()))
        raw = json.loads(source[0].read_text())
        self.assertTrue(raw["findings"][0]["content_id"])

    def test_acceptance_preserves_finding_and_reports_exact_review_not_global_allowance(self):
        saved, _ = self.accept()
        result = self.scan()
        self.assertEqual(result.check_status, "passed", result.record())
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].classification, "review")
        self.assertEqual(result.findings[0].review_id, saved.review_id)
        self.assertIn("accepted example", result.summary())
        self.assertEqual(load_policy(self.repo, home=self.home).safe.count(self.value), 0)
        self.assertNotIn(self.value, result.summary())

    def test_changed_bytes_location_or_repository_do_not_inherit_review(self):
        self.accept()
        (self.repo / "contact.txt").write_text(self.body + "changed elsewhere\n", encoding="utf-8")
        self.assertEqual(self.scan().check_status, "review-required")
        (self.repo / "contact.txt").write_text(self.body, encoding="utf-8")
        (self.repo / "other.txt").write_text(self.body, encoding="utf-8")
        self.assertEqual(len(self.scan().actionable), 1)
        other = self.root / "other-repo"
        self.git(self.root, "init", "-q", str(other))
        (other / "contact.txt").write_text(self.body, encoding="utf-8")
        result = scan(other, load_policy(other, home=self.home))
        self.assertEqual(result.check_status, "review-required")

    def test_exact_original_content_can_be_recognized_after_revert(self):
        self.accept()
        (self.repo / "contact.txt").write_text("changed\n" + self.body, encoding="utf-8")
        self.assertEqual(self.scan().check_status, "review-required")
        (self.repo / "contact.txt").write_text(self.body, encoding="utf-8")
        self.assertEqual(self.scan().check_status, "passed")

    def test_identical_candidates_on_one_line_require_separate_decisions(self):
        (self.repo / "contact.txt").write_text(self.value + " " + self.value + "\n", encoding="utf-8")
        self.accept()
        result = self.scan()
        self.assertEqual(len(result.findings), 2)
        self.assertEqual(len(result.actionable), 1)
        self.assertEqual(result.check_status, "review-required")
        self.assertEqual([item.occurrence for item in result.findings], [1, 2])

    def test_filename_review_is_invalidated_when_its_file_contents_change(self):
        target = self.repo / (self.value + ".txt")
        (self.repo / "contact.txt").unlink()
        target.write_text("ordinary", encoding="utf-8")
        self.accept()
        self.assertEqual(self.scan().check_status, "passed")
        target.write_text("changed", encoding="utf-8")
        self.assertEqual(self.scan().check_status, "review-required")

    def test_documented_incident_description_can_be_reviewed_only_in_exact_context(self):
        body = "Documentation describes a purge near commit " + "a" * 12 + ".\n"
        path = self.repo / "contact.txt"
        path.write_text(body, encoding="utf-8")
        self.accept(self.report(check="leak-description near commit id"))
        self.assertEqual(self.scan().check_status, "passed")
        path.write_text(body + "changed context\n", encoding="utf-8")
        self.assertEqual(self.scan().check_status, "review-required")

    def test_invalid_utf8_changes_do_not_reuse_decoded_text_binding(self):
        path = self.repo / "contact.txt"
        path.write_bytes(self.body.encode() + bytes([255]))
        self.accept()
        path.write_bytes(self.body.encode() + bytes([254]))
        self.assertEqual(self.scan().check_status, "review-required")

    def test_wrong_approval_or_changed_reason_saves_nothing(self):
        source = self.report()
        plan = review_finding(*source, "first reason", home=self.home)
        for reason, token in (("first reason", "wrong-plan"), ("different reason", plan.plan_id)):
            result = review_finding(*source, reason, home=self.home, apply=True, approve=token)
            self.assertEqual(result.status, "approval-required", result.record())
        self.assertFalse(_reviews.directory(self.home, self.repo).exists())

    def test_changed_report_after_preview_requires_new_approval(self):
        source = self.report()
        plan = review_finding(*source, "fixture", home=self.home)
        raw = json.loads(source[0].read_text())
        raw["scope_note"] += " changed"
        source[0].write_text(json.dumps(raw), encoding="utf-8")
        result = review_finding(*source, "fixture", home=self.home, apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "approval-required", result.record())
        self.assertFalse(_reviews.directory(self.home, self.repo).exists())

    def test_prohibited_values_and_strong_credentials_cannot_be_accepted(self):
        for value, check in (("private-marker", "never-publish"), ("ghp_" + "Ab12" * 9, "GitHub token")):
            (self.repo / "contact.txt").write_text(value, encoding="utf-8")
            source = self.report(check=check)
            result = review_finding(*source, "claimed fixture", home=self.home)
            self.assertEqual(result.status, "refused", result.record())
        self.assertFalse(_reviews.directory(self.home, self.repo).exists())

    def test_new_prohibition_overrides_previously_accepted_example(self):
        self.accept()
        self.document["defaults"]["security"]["never_publish"].append(self.value)
        self.save_settings()
        result = self.scan()
        self.assertEqual(result.check_status, "blocked", result.record())
        self.assertTrue(any(item.check == "never-publish" and not item.review_id for item in result.findings))

    def test_missing_common_settings_cannot_reactivate_reviews_under_fresh_defaults(self):
        self.accept()
        (self.home / "settings.json").unlink()
        with patch.object(_push, "fetch", side_effect=AssertionError("missing settings must hold before fetch")):
            plan = _push.push_checked(self.repo, settings_home=self.home)
        self.assertEqual(plan.status, "incomplete", plan.record())
        self.assertEqual(self.scan().check_status, "incomplete")

    def test_new_prohibition_between_preview_and_apply_prevents_acceptance(self):
        source = self.report()
        plan = review_finding(*source, "fixture", home=self.home)
        self.document["defaults"]["security"]["never_publish"].append(self.value)
        self.save_settings()
        result = review_finding(*source, "fixture", home=self.home, apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "refused", result.record())

    def test_enclosing_safe_value_cannot_override_an_explicit_prohibited_substring(self):
        source = self.report()
        self.document["defaults"]["security"]["never_publish"].append("example-agent")
        self.document["defaults"]["security"]["safe_values"] = [self.value]
        self.save_settings()
        result = self.scan()
        self.assertEqual(result.check_status, "blocked", result.record())
        self.assertTrue(any(item.check == "never-publish" for item in result.findings))
        review = review_finding(*source, "claimed fixture", home=self.home)
        self.assertEqual(review.status, "refused", review.record())

    def test_revocation_keeps_history_and_restores_review_required(self):
        saved, source = self.accept()
        self.revoke(source, saved.review_id)
        folder = _reviews.directory(self.home, self.repo)
        self.assertTrue((folder / (saved.review_id + ".json")).exists())
        self.assertTrue((folder / (saved.review_id + ".revoke.json")).exists())
        self.assertEqual(self.scan().check_status, "review-required")

    def test_duplicate_acceptance_does_not_create_another_record(self):
        saved, source = self.accept()
        again = review_finding(*source, "another reason", home=self.home)
        self.assertEqual(again.status, "already-reviewed")
        self.assertEqual(again.review_id, saved.review_id)
        self.assertEqual(len(list(_reviews.directory(self.home, self.repo).iterdir())), 1)

    def test_corrupt_review_state_is_incomplete_not_silently_ignored(self):
        self.accept()
        (_reviews.directory(self.home, self.repo) / "bad.json").write_text("{broken", encoding="utf-8")
        result = self.scan()
        self.assertEqual(result.check_status, "incomplete", result.record())
        self.assertTrue(any(item["where"] == "review records" for item in result.gaps))

    def test_coverage_gaps_remain_after_example_review(self):
        self.accept()
        (self.repo / "uninspected.pdf").write_bytes(b"unrecognized payload")
        result = self.scan()
        self.assertEqual(result.check_status, "incomplete", result.record())
        self.assertTrue(result.findings[0].review_id)

    def test_excluded_review_storage_is_not_read_or_written(self):
        saved, source = self.accept()
        folder = _reviews.directory(self.home, self.repo)
        self.document["defaults"]["scope"] = {"exclude_paths": [str(folder)]}
        self.save_settings()
        with patch.object(_reviews, "load", side_effect=AssertionError("excluded records were read")):
            self.assertEqual(self.scan().check_status, "review-required")
            result = review_finding(*source, "fixture", home=self.home)
        self.assertEqual(result.status, "refused", result.record())
        self.assertEqual(len(list(folder.iterdir())), 1)

    def test_excluded_private_report_is_refused_before_reading(self):
        source = self.report()
        self.document["defaults"]["scope"] = {"exclude_paths": [str(source[0])]}
        self.save_settings()
        with patch("Special.security._review_operation.read_private_json", side_effect=AssertionError("excluded report read")):
            result = review_finding(*source, "fixture", home=self.home)
        self.assertEqual(result.status, "refused", result.record())

    def test_malformed_or_forged_strong_review_binding_makes_policy_incomplete(self):
        saved, _ = self.accept()
        path = _reviews.directory(self.home, self.repo) / (saved.review_id + ".json")
        original = json.loads(path.read_text())
        for replacement in ([], "GitHub token", "never-publish"):
            record = json.loads(json.dumps(original))
            record["evidence"]["check"] = replacement
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.scan().check_status, "incomplete")

    def test_review_destination_failure_returns_finite_error_without_fallback(self):
        source = self.report()
        plan = review_finding(*source, "fixture", home=self.home)
        with patch("Special.security._review_operation.write_private_json", side_effect=OSError("private diagnostic " + self.value)):
            result = review_finding(*source, "fixture", home=self.home, apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.saved)
        self.assertEqual(result.artifacts, [])
        self.assertNotIn(self.value, json.dumps(result.record()))
        self.assertFalse(_reviews.directory(self.home, self.repo).exists())

    def test_same_exact_example_flows_through_real_checked_commit_and_push(self):
        saved, _ = self.accept()
        before = self.git(self.repo, "rev-parse", "HEAD")
        plan = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home)
        self.assertEqual(plan.status, "ready", plan.record())
        result = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home,
                                apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "committed", result.record())
        self.assertNotEqual(self.git(self.repo, "rev-parse", "HEAD"), before)
        push_plan = _push.push_checked(self.repo, settings_home=self.home)
        self.assertEqual(push_plan.status, "planned", push_plan.record())
        pushed = _push.push_checked(self.repo, settings_home=self.home, apply=True, approve=push_plan.plan_id)
        self.assertEqual(pushed.status, "pushed", pushed.record())
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), self.git(self.repo, "rev-parse", "HEAD"))
        self.assertIn(saved.review_id, json.dumps(pushed.record()))
        self.assertNotIn(self.value, json.dumps(pushed.record()))

    def test_staged_scan_reads_index_bytes_without_working_bytes_or_index_changes(self):
        self.git(self.repo, "add", "--", "contact.txt")
        (self.repo / "contact.txt").write_text("private-marker", encoding="utf-8")
        before = (self.repo / ".git/index").read_bytes()
        result = self.scan(material="index")
        self.assertEqual(result.material, "index")
        self.assertTrue(any(item.check == "email address" for item in result.findings))
        self.assertFalse(any(item.check == "never-publish" for item in result.findings))
        self.assertEqual(result.files, 1)
        self.assertEqual((self.repo / ".git/index").read_bytes(), before)
        self.assertEqual((self.repo / "contact.txt").read_text(), "private-marker")

    def test_empty_or_deleted_only_staged_scope_does_not_scan_old_or_working_bytes(self):
        self.assertEqual(self.scan(material="index").files, 0)
        self.git(self.repo, "add", "--", "contact.txt")
        self.git(self.repo, "commit", "-qm", "fixture contact")
        (self.repo / "contact.txt").unlink()
        self.git(self.repo, "add", "--", "contact.txt")
        result = self.scan(material="index")
        self.assertEqual(result.files, 0)
        self.assertEqual(result.check_status, "passed")

    def test_line_ending_conversion_can_be_reviewed_without_changing_working_file(self):
        self.git(self.repo, "config", "core.autocrlf", "true")
        path = self.repo / "contact.txt"
        original = self.body.replace("\n", "\r\n").encode("utf-8")
        path.write_bytes(original)
        self.accept()
        plan = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home)
        self.assertEqual(plan.status, "ready", plan.record())
        held = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home,
                              apply=True, approve=plan.plan_id)
        self.assertEqual(held.status, "review-required", held.record())
        self.accept(self.report(self.scan(material="index")))
        fresh = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home)
        self.assertEqual(fresh.status, "ready", fresh.record())
        committed = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home,
                                   apply=True, approve=fresh.plan_id)
        self.assertEqual(committed.status, "committed", committed.record())
        self.assertEqual(path.read_bytes(), original)

    def test_staged_cli_uses_same_masked_report_and_explicit_private_output(self):
        self.git(self.repo, "add", "--", "contact.txt")
        destination = self.home / "staged.json"
        output = io.StringIO()
        with redirect_stdout(output):
            code = gitso.main(["scan-tree", str(self.repo), "--staged", "--json", "--out", str(destination),
                               "--settings-home", str(self.home)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["material"], "index")
        self.assertNotIn(self.value, output.getvalue())
        self.assertIn(self.value, destination.read_text())

    def test_index_change_during_staged_scan_is_incomplete(self):
        self.git(self.repo, "add", "--", "contact.txt")
        original = _material._history_versions
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.repo / "later.txt").write_text("ordinary", encoding="utf-8")
            self.git(self.repo, "add", "--", "later.txt")
            return result
        with patch.object(_material, "_history_versions", side_effect=changed):
            result = self.scan(material="index")
        self.assertEqual(result.check_status, "incomplete", result.record())
        self.assertTrue(any(item["where"] == "index" for item in result.gaps))

    def test_unmerged_index_entries_are_coverage_gaps_without_index_writes(self):
        self.git(self.repo, "checkout", "-qb", "fixture-side")
        (self.repo / "base.txt").write_text("side", encoding="utf-8")
        self.git(self.repo, "commit", "-qam", "side fixture")
        self.git(self.repo, "checkout", "-q", "main")
        (self.repo / "base.txt").write_text("main", encoding="utf-8")
        self.git(self.repo, "commit", "-qam", "main fixture")
        merged = subprocess.run(["git", "-C", str(self.repo), "merge", "fixture-side"], capture_output=True, text=True)
        self.assertEqual(merged.returncode, 1)
        before = (self.repo / ".git/index").read_bytes()
        result = self.scan(material="index")
        self.assertEqual(result.check_status, "incomplete", result.record())
        self.assertTrue(any("unmerged" in item["reason"] for item in result.gaps))
        self.assertEqual((self.repo / ".git/index").read_bytes(), before)

    def test_revocation_during_push_check_holds_publication(self):
        saved, source = self.accept()
        self.git(self.repo, "add", "--", "contact.txt")
        self.git(self.repo, "commit", "-qm", "fixture contact")
        original = _push.scan
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.revoke(source, saved.review_id)
            return result
        with patch.object(_push, "scan", side_effect=changed):
            result = _push.publish_checked(_push.read_push_snapshot(self.repo), settings_home=self.home)
        self.assertEqual(result.status, "stale", result.record())
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), self.base)

    def test_revocation_after_commit_preview_prevents_staging_or_commit(self):
        saved, source = self.accept()
        plan = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home)
        self.assertEqual(plan.status, "ready", plan.record())
        before = (self.repo / ".git/index").read_bytes()
        self.revoke(source, saved.review_id)
        result = commit_checked(self.repo, ["contact.txt"], "fixture contact", settings_home=self.home,
                                apply=True, approve=plan.plan_id)
        self.assertEqual(result.status, "review-required", result.record())
        self.assertEqual((self.repo / ".git/index").read_bytes(), before)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), self.base)

    def test_cli_and_catalog_preview_keep_reason_values_private_and_no_state(self):
        source = self.report()
        output = io.StringIO()
        reason = "private reason " + self.value
        with redirect_stdout(output):
            code = gitso.main(["review-finding", str(source[0]), source[1], "--reason", reason,
                               "--settings-home", str(self.home), "--json"])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "planned")
        self.assertNotIn(self.value, output.getvalue())
        self.assertNotIn(reason, output.getvalue())
        self.assertFalse(_reviews.directory(self.home, self.repo).exists())

    def test_help_from_outside_checkout_never_reads_or_creates_settings(self):
        absent = self.root / "absent"
        done = subprocess.run([sys.executable, "-B", str(ROOT / "Special/security/review_finding.py"),
                               "--settings-home", str(absent), "--help"], cwd=self.root,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(absent.exists())


if __name__ == "__main__":
    unittest.main()
