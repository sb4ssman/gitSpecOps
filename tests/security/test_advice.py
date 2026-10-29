"""Local security advice and sync integration in disposable Git repositories only.

No user settings, external scanner installation, host authentication or network is used.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup("sync")

from Special.security import _advice
from Special._settings.fleet import load_fleet_settings
from fleet_observer import IncrementalObserver
from observer import observe_paths
from advice import render_table
import sync_suggester as cli
from local_dashboard import make_local_server
from local_view import display_from_manifests
from manifest import build_manifest, fleet_id_for


class SecurityAdviceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-advice-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.home = self.root / "checkout", self.root / "profile"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                              "GITSPECOPS_HOME": str(self.home), "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.git(self.root, "init", "-q", "-b", "main", str(self.repo))
        self.git(self.repo, "config", "user.name", "orbit-user")
        self.git(self.repo, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(self.repo, "config", "commit.gpgsign", "false")
        self.git(self.repo, "config", "core.autocrlf", "false")
        self.commit("file.txt", "ordinary")
        self.remote = self.root / "remote.git"
        self.git(self.root, "clone", "-q", "--bare", str(self.repo), str(self.remote))
        self.git(self.repo, "remote", "add", "origin", str(self.remote))
        self.git(self.repo, "fetch", "-q", "origin")
        self.git(self.repo, "branch", "--set-upstream-to=origin/main")
        self.document = {"schema_version": 2, "defaults": {"security": {"never_publish": ["private-marker"]}}}
        self.save()

    def git(self, repo, *arguments):
        return subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True,
                              text=True, encoding="utf-8", timeout=30).stdout.strip()

    def commit(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git(self.repo, "add", "--", name)
        self.git(self.repo, "commit", "-qm", "fixture change")

    def save(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def check(self):
        return _advice.inspect_advice(self.repo, settings_home=self.home)

    def test_clean_advice_reads_cached_refs_without_network_or_writes(self):
        index = (self.repo / ".git/index").read_bytes()
        settings = (self.home / "settings.json").read_bytes()
        result = self.check()
        self.assertEqual(result["check_status"], "passed", result)
        self.assertFalse(result["action_clearance"])
        self.assertEqual(result["outgoing"]["basis"], "cached-upstream")
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual((self.home / "settings.json").read_bytes(), settings)
        self.assertEqual(sorted(path.name for path in self.home.iterdir()), ["settings.json"])

    def test_dirty_secret_and_ahead_facts_are_both_visible_and_masked(self):
        self.commit("ahead.txt", "ordinary")
        (self.repo / "file.txt").write_text("private-marker")
        observation = observe_paths([self.repo])
        records = _advice.inspect_paths([(observation.repositories[0]["repo_id"], self.repo)], settings_home=self.home)
        table = render_table({"repositories": observation.repositories}, observation.catalog, observation.branches,
                             security=records)
        self.assertIn("SECURITY blocked", table)
        self.assertIn("dirty", table)
        self.assertIn("ahead 1", table)
        self.assertNotIn("private-marker", json.dumps(records) + _advice.render_advice(records))
        self.assertTrue(records[0]["security"]["working_tree"]["findings"])

    def test_introduce_then_remove_is_still_outgoing_finding(self):
        self.commit("file.txt", "private-marker")
        self.commit("file.txt", "removed")
        result = self.check()
        self.assertEqual(result["working_tree"]["check_status"], "passed")
        self.assertEqual(result["outgoing"]["check_status"], "blocked")

    def test_missing_upstream_retains_tree_findings_without_claiming_outgoing_checked(self):
        self.git(self.repo, "branch", "--unset-upstream")
        (self.repo / "file.txt").write_text("private-marker")
        result = self.check()
        self.assertEqual(result["check_status"], "incomplete")
        self.assertEqual(result["outgoing"]["check_status"], "not-checked")
        self.assertEqual(result["working_tree"]["check_status"], "blocked", result)

    def test_missing_selected_engine_is_incomplete(self):
        self.document["defaults"]["security"]["engines"] = ["gitleaks"]
        self.save()
        with patch("Special.security._engines.shutil.which", return_value=None):
            self.assertEqual(self.check()["check_status"], "incomplete")

    def test_invalid_policy_prevents_material_reads(self):
        (self.home / "settings.json").write_text("broken")
        with patch.object(_advice, "scan", side_effect=AssertionError("unexpected material read")):
            self.assertEqual(self.check()["check_status"], "incomplete")

    def test_excluded_repo_prevents_material_reads(self):
        self.document["defaults"]["scope"] = {"exclude_paths": [str(self.repo)]}
        self.save()
        with patch.object(_advice, "scan", side_effect=AssertionError("unexpected material read")):
            self.assertEqual(self.check()["check_status"], "incomplete")

    def test_policy_loss_during_check_preserves_findings_and_marks_incomplete(self):
        (self.repo / "file.txt").write_text("private-marker")
        real_scan = _advice.scan
        def changing(*args, **kwargs):
            result = real_scan(*args, **kwargs)
            (self.home / "settings.json").unlink(missing_ok=True)
            return result
        with patch.object(_advice, "scan", side_effect=changing):
            result = self.check()
        self.assertEqual(result["check_status"], "incomplete")
        self.assertEqual(result["working_tree"]["check_status"], "blocked", result)

    def test_known_common_profile_loss_before_advice_never_uses_fresh_defaults(self):
        snapshot = load_fleet_settings(self.home)
        (self.home / "settings.json").unlink()
        with patch.object(_advice, "scan", side_effect=AssertionError("unexpected default-policy scan")):
            result = _advice.inspect_advice(self.repo, settings_home=self.home, expected_settings=snapshot)
        self.assertEqual(result["check_status"], "incomplete")
        self.assertIsNone(result["working_tree"])

    def test_duplicate_checkout_ids_are_not_dropped(self):
        records = _advice.inspect_paths([("same-id", self.repo), ("same-id", self.repo)], settings_home=self.home)
        self.assertEqual([entry["checkout"] for entry in records], [1, 2])

    def test_incremental_lookup_keeps_all_local_copies(self):
        observer = IncrementalObserver({})
        other = self.root / "second-copy"
        observer._repos = {self.repo: {"repo_id": "same-id"}, other: {"repo_id": "same-id"}}
        self.assertEqual(observer.local_checkouts("same-id"), (self.repo, other))
        self.assertEqual(observer.local_checkouts("unknown"), ())

    def test_json_local_findings_never_enter_published_manifest(self):
        (self.repo / "file.txt").write_text("private-marker")
        secret = "ab" * 32
        observation = observe_paths([self.repo], secret)
        transport = Mock()
        transport.write_own_manifest.return_value = None
        resolved = cli.Resolution(self.root / "state", {"fleet_secret": secret}, [], "test roots",
                                  "machine-a", "workstation-a", None, transport=transport)
        args = cli.build_parser().parse_args(["check", "--local-only", "--json", "--no-catalog"])
        args.settings_home = self.home
        output = io.StringIO()
        with patch.object(cli, "_resolve", return_value=resolved), \
             patch.object(cli, "observe_roots", return_value=observation), \
             patch.object(cli, "load_catalog", return_value={}), patch.object(cli, "load_branches", return_value={}), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.command_check(args), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["local_security"][0]["security"]["check_status"], "blocked")
        published = transport.write_own_manifest.call_args.args[1]
        self.assertEqual(published, result["manifest"])
        self.assertNotIn("local_security", published)
        self.assertNotIn("findings", json.dumps(published))
        self.assertNotIn("private-marker", output.getvalue())

    def test_registered_ui_scope_rejects_paths_and_unknown_ids_before_scan(self):
        with patch.object(_advice, "inspect_paths", side_effect=AssertionError("unexpected scan")):
            for payload in ({"path": str(self.repo)}, {"repo_id": "x", "path": str(self.repo)}, {"repo_id": 3}, {}):
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    _advice.inspect_registered(payload, lambda _: [self.repo], settings_home=self.home)
            with self.assertRaises(ValueError):
                _advice.inspect_registered({"repo_id": "unknown"}, lambda _: [], settings_home=self.home)

    def test_registered_ui_checks_all_local_copies_through_shared_function(self):
        calls = [("same-id", self.repo), ("same-id", self.repo)]
        with patch.object(_advice, "inspect_paths", return_value=[]) as checking:
            result = _advice.inspect_registered({"repo_id": "same-id"}, lambda _: [self.repo, self.repo], settings_home=self.home)
        self.assertEqual(list(checking.call_args.args[0]), calls)
        self.assertEqual(checking.call_args.kwargs["settings_home"], self.home)
        self.assertEqual(result["artifacts"], [])

    def test_clean_fleet_row_with_security_finding_remains_in_exceptions_view(self):
        observation = observe_paths([self.repo])
        manifest = build_manifest("preview", "machine-a", "workstation-a", observation.repositories)
        repo_id = observation.repositories[0]["repo_id"]
        records = [{"repo_id": repo_id, "security": {"check_status": "blocked"}}]
        with patch.object(cli, "load_manifests", return_value=([manifest], [])):
            text = cli._dashboard_text(Mock(), None, observation.catalog, own=manifest, local_security=records)
        self.assertIn("SECURITY blocked", text)
        self.assertNotIn("(nothing needs attention)", text)

    def test_security_button_is_available_only_for_local_observed_copies(self):
        observation = observe_paths([self.repo])
        fleet = fleet_id_for("ab" * 32)
        manifest = build_manifest(fleet, "machine-a", "workstation-a", observation.repositories)
        repo_id = observation.repositories[0]["repo_id"]
        view = display_from_manifests([manifest], settings={"local_repo_ids": [repo_id], "security_available": True})
        self.assertTrue(view["rows"][0]["security_action"]["available"])
        view = display_from_manifests([manifest], settings={"security_available": True})
        self.assertFalse(view["rows"][0]["security_action"]["available"])

    def test_local_security_endpoint_requires_origin_token_and_known_scope(self):
        handler = lambda action, payload: _advice.inspect_registered(payload,
            lambda repo_id: [self.repo] if repo_id == "known" else [], settings_home=self.home)
        server = make_local_server(("127.0.0.1", 0), lambda: {"rows": []}, {}, fleet_action=handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = build_opener(ProxyHandler({}))
        def request(path, payload=None, headers=None):
            request = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                              headers=headers or {})
            try:
                response = opener.open(request, timeout=20)
            except HTTPError as exc:
                response = exc
            with response:
                return response.status, json.loads(response.read())
        try:
            token = request("/v1/dashboard")[1]["local_actions"]["token"]
            headers = {"Content-Type": "application/json", "Origin": base, "X-GitSpecOps-Token": token}
            self.assertEqual(request("/v1/security-preview", {"repo_id": "known"})[0], 403)
            self.assertEqual(request("/v1/security-preview", {"repo_id": "known"}, {**headers, "Origin": "https://invalid.example"})[0], 403)
            self.assertEqual(request("/v1/security-preview", {"repo_id": "unknown"}, headers)[0], 400)
            code, result = request("/v1/security-preview", {"repo_id": "known"}, headers)
            self.assertEqual(code, 200)
            self.assertEqual(result["local_security"][0]["security"]["check_status"], "passed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
