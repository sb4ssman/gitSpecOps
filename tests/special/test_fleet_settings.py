"""Offline common fleet settings integration; every profile and repository root is temporary.

Run directly with Python. Network, tray startup, installation and real enrollment are mocked.
"""
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup("sync")

import config as cli_config
import fleet_app
import fleet_config
import fleet_desktop
import sync_suggester
from Special._settings import SettingsError
from Special._settings.fleet import (fleet_directory, fleet_home, load_fleet_settings,
                                    save_fleet_config)


class FleetSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home, self.state, self.root = (self.base / name for name in ("profile", "state", "library"))
        self.folder = self.base / "transport"
        for path in (self.home, self.state, self.root, self.folder):
            path.mkdir()
        self.environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.key = "12" * 32
        self.app = fleet_config.new_config("machine-a", "Machine A", [self.root], self.key,
                                           transports={"folder": {"path": str(self.folder), "seconds": 300},
                                                       "repo": {"name": "example/status", "seconds": 1800}})
        self.doc = {"schema_version": 2, "machine": {"id": "machine-a", "label": "Machine A", "fleet_secret": self.key},
                    "defaults": {"security": {"never_publish": ["private@example.invalid"]}},
                    "transports": copy.deepcopy(self.app["transports"]), "components": {
                        "sync": {"scope": {"roots": [str(self.root)]}, "options": {
                            "root_recursion": {str(self.root): False}, "transport_names": ["folder"],
                            "stale_hours": 24, "expired_days": 7, "compress_manifests": False}},
                        "app": {"scope": {"roots": [str(self.root)]}, "options": {
                            **{key: copy.deepcopy(value) for key, value in self.app.items() if key not in
                               ("version", "mode", "machine_id", "label", "fleet_secret", "roots", "transports")},
                            "transport_names": ["folder", "repo"]}}}}
        self.path = self.home / "settings.json"
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.doc, indent=1) + "\n", encoding="utf-8")

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def app_command(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return fleet_app.main(["--settings-home", str(self.home), "--config-dir", str(self.state), *args])

    def test_readers_select_common_and_keep_distinct_transports(self):
        (self.state / "config.json").write_text("broken legacy", encoding="utf-8")
        (self.state / "fleet-app.json").write_text("broken legacy", encoding="utf-8")
        before = self.path.read_bytes()
        cli = cli_config.load_config(self.state)
        app = fleet_app.load_saved(self.state)
        self.assertEqual(cli["state_dir"], str(self.folder))
        self.assertIsNone(cli["state_repo"])
        self.assertEqual(set(app["transports"]), {"folder", "repo"})
        self.assertEqual(app["baskets"], self.app["baskets"])
        self.assertNotIn(self.key, repr(app))
        self.assertNotIn(str(self.home), repr(app.snapshot))
        self.assertEqual(before, self.path.read_bytes())

    def test_legacy_only_round_trip(self):
        self.path.unlink()
        cli = cli_config.default_config("machine-a", self.key)
        cli_config.save_config(self.state, cli)
        self.assertEqual(cli, cli_config.load_config(self.state))
        fleet_app.save_saved(self.state, self.app)
        self.assertEqual(self.app, fleet_app.load_saved(self.state))
        self.assertFalse(self.path.exists())

    def test_common_unenrolled_does_not_read_legacy(self):
        self.doc["components"] = {}
        self.write()
        (self.state / "config.json").write_text("broken", encoding="utf-8")
        (self.state / "fleet-app.json").write_text("broken", encoding="utf-8")
        self.assertIsNone(cli_config.load_config(self.state))
        with self.assertRaisesRegex(ValueError, "no app enrollment"):
            fleet_app.load_saved(self.state)

    def test_invalid_common_never_falls_back(self):
        for text in ("{bad", '{"schema_version":2,"schema_version":2}', '{"schema_version":999}'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    cli_config.load_config(self.state)
                with self.assertRaises(ValueError):
                    fleet_app.load_saved(self.state)

    def test_incomplete_enrollment_is_error(self):
        del self.doc["components"]["app"]["options"]["baskets"]
        self.write()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            fleet_app.load_saved(self.state)

    def test_recursion_must_cover_exact_roots(self):
        self.doc["components"]["sync"]["options"]["root_recursion"] = {}
        self.write()
        with self.assertRaisesRegex(ValueError, "recursion"):
            cli_config.load_config(self.state)

    def test_equivalent_root_spellings_share_recursion_but_duplicate_aliases_fail(self):
        alternate = (self.root / ".." / self.root.name).as_posix()
        self.doc["components"]["sync"]["scope"]["roots"] = [alternate]
        recursion = self.doc["components"]["sync"]["options"]["root_recursion"]
        recursion.clear()
        recursion[alternate] = True
        self.write()
        cli = cli_config.load_config(self.state)
        self.assertEqual(cli["roots"], [{"path": str(self.root), "recursive": True}])
        recursion[str(self.root)] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "recursion"):
            cli_config.load_config(self.state)

    def test_save_preserves_other_owners_and_legacy_bytes(self):
        legacy = self.state / "fleet-app.json"
        legacy.write_bytes(b"retained original")
        before = copy.deepcopy(self.doc)
        app = fleet_app.load_saved(self.state)
        app["fetch_minutes"] = 0
        fleet_app.save_saved(self.state, app)
        saved = self.saved()
        self.assertEqual(saved["components"]["sync"], before["components"]["sync"])
        self.assertEqual(saved["defaults"], before["defaults"])
        self.assertEqual(legacy.read_bytes(), b"retained original")
        self.assertEqual(saved["components"]["app"]["options"]["fetch_minutes"], 0)
        app["share_names"] = False
        fleet_app.save_saved(self.state, app)
        self.assertFalse(self.saved()["components"]["app"]["options"]["share_names"])

    def test_noop_retains_exact_bytes(self):
        before = self.path.read_bytes()
        app = fleet_app.load_saved(self.state)
        fleet_app.save_saved(self.state, app)
        cli_config.save_config(self.state, cli_config.load_config(self.state))
        self.assertEqual(before, self.path.read_bytes())

    def test_stale_mutated_and_busy_saves_fail(self):
        for failure in ("stale", "mutated", "busy"):
            with self.subTest(failure=failure):
                self.write()
                app = fleet_app.load_saved(self.state)
                app["share_names"] = False
                if failure == "stale":
                    self.path.write_bytes(self.path.read_bytes() + b" ")
                elif failure == "mutated":
                    app.snapshot.document["machine"]["label"] = "altered"
                else:
                    (self.home / ".settings.lock").touch()
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    fleet_app.save_saved(self.state, app)
                self.assertEqual(before, self.path.read_bytes())
                (self.home / ".settings.lock").unlink(missing_ok=True)

    def test_plain_copy_cannot_bypass_revision(self):
        app = fleet_app.load_saved(self.state)
        with self.assertRaisesRegex(ValueError, "source snapshot"):
            fleet_app.save_saved(self.state, dict(app))

    def test_deleted_common_cannot_redirect_loaded_save(self):
        app = fleet_app.load_saved(self.state)
        self.path.unlink()
        with self.assertRaises(ValueError):
            fleet_app.save_saved(self.state, app)
        self.assertFalse((self.state / "fleet-app.json").exists())

    def test_shared_identity_change_refused(self):
        app = fleet_app.load_saved(self.state)
        app["label"] = "other machine"
        with self.assertRaisesRegex(ValueError, "shared machine"):
            fleet_app.save_saved(self.state, app)

    def test_shared_transport_change_refused(self):
        app = fleet_app.load_saved(self.state)
        app["transports"]["folder"]["seconds"] = 600
        with self.assertRaisesRegex(ValueError, "another component"):
            fleet_app.save_saved(self.state, app)

    def test_own_transport_change_and_clear_preserve_shared_definition(self):
        app = fleet_app.load_saved(self.state)
        app["transports"]["repo"]["seconds"] = 3600
        fleet_app.save_saved(self.state, app)
        del app["transports"]["folder"]
        fleet_app.save_saved(self.state, app)
        self.assertIn("folder", self.saved()["transports"])
        self.assertEqual(cli_config.load_config(self.state)["state_dir"], str(self.folder))

    def test_exclusion_rejected_before_git_and_run_override(self):
        self.doc["defaults"]["scope"] = {"exclude_paths": [str(self.root / "private")]}
        self.write()
        with patch("sync_suggester.open_transport", side_effect=AssertionError("must not open transport")):
            args = sync_suggester.build_parser().parse_args(["--settings-home", str(self.home), "check"])
            with redirect_stderr(io.StringIO()):
                self.assertEqual(sync_suggester._resolve(args), 2)
        self.doc["defaults"]["scope"] = {"exclude_paths": [str(self.base / "forbidden")]}
        self.write()
        args = sync_suggester.build_parser().parse_args(["--settings-home", str(self.home), "check", "--root", str(self.base)])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(sync_suggester._resolve(args), 2)

    def test_settings_home_and_runtime_directory_are_independent(self):
        self.assertEqual(fleet_directory(self.state, home=self.home), self.state)
        self.assertEqual(fleet_directory(home=self.home), self.home / "sync-suggester")
        with patch.dict(os.environ, {"GITSPECOPS_SYNC_HOME": str(self.state)}):
            self.assertEqual(fleet_directory(home=self.home), self.state)
            self.assertEqual(fleet_home(), self.home)
            self.assertEqual(cli_config.load_config()["machine_id"], "machine-a")

    def test_baskets_and_transports_commands_save_common(self):
        self.assertEqual(self.app_command("baskets", "--scope", "publish", "--mode", "none"), 0)
        self.assertEqual(self.saved()["components"]["app"]["options"]["baskets"]["publish"], {"mode": "none"})
        self.assertEqual(self.app_command("transports", "--clear-repo"), 0)
        self.assertEqual(self.saved()["components"]["app"]["options"]["transport_names"], ["folder"])
        self.assertFalse((self.state / "fleet-app.json").exists())

    def test_cli_init_reuses_shared_identity(self):
        del self.doc["components"]["sync"]
        self.write()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch("config.new_fleet_secret", side_effect=AssertionError):
            code = sync_suggester.main(["--settings-home", str(self.home), "--config-dir", str(self.state),
                                        "init", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(self.saved()["machine"], self.doc["machine"])
        self.assertFalse((self.state / "config.json").exists())

    def test_app_enrollment_uses_existing_identity(self):
        del self.doc["components"]["app"]
        self.write()
        with patch("fleet_app.resolve_machine_identity", side_effect=AssertionError), patch("fleet_app.run_peer", side_effect=AssertionError):
            self.assertEqual(self.app_command("peer", "--root", str(self.root), "--no-tailnet",
                                              "--acknowledge-initial-scan", "--configure-only"), 0)
        self.assertEqual(self.saved()["machine"], self.doc["machine"])

    def test_help_has_no_profile_reads_or_locks(self):
        for module in (fleet_app, sync_suggester):
            with patch.object(module, "load_fleet_settings", side_effect=AssertionError), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    module.main(["--help"])
                self.assertEqual(caught.exception.code, 0)
        self.assertFalse((self.state / "fleet-app.lock").exists())

    def test_preflight_remains_independent_of_invalid_configuration(self):
        self.path.write_text("{bad", encoding="utf-8")
        with patch("fleet_app.load_fleet_settings", side_effect=AssertionError), patch("fleet_app.command_preflight", return_value=0):
            self.assertEqual(self.app_command("preflight"), 0)

    def test_app_run_and_tray_preserve_selected_profile(self):
        with patch("fleet_app.run_peer", return_value=0) as run:
            self.assertEqual(self.app_command("run"), 0)
            self.assertEqual(run.call_args.args[0].snapshot.home, self.home)
            self.assertEqual(run.call_args.args[1], self.state)
        with patch("fleet_tray.run_tray", return_value=0) as tray:
            self.assertEqual(self.app_command("tray"), 0)
            self.assertEqual(tray.call_args.args[0], fleet_app.profile_arguments(self.state, self.home) + ["run"])

    def test_desktop_common_enrollment_does_not_start_setup(self):
        with patch("fleet_desktop.threading.Thread"), patch("fleet_desktop.main", return_value=0) as main:
            self.assertEqual(fleet_desktop.desktop_main([]), 0)
            main.assert_called_once_with(["tray"])

    def test_dashboard_choice_does_not_persist_runtime_transport_identity(self):
        self.doc["transports"]["tailnet"] = {"port": 8765, "allowed_login": None}
        self.doc["components"]["app"]["options"]["transport_names"].append("tailnet")
        self.write()
        app = fleet_app.load_saved(self.state)
        app["transports"]["tailnet"]["allowed_login"] = "discovered-user@example.invalid"
        executable = self.base / "desktop.exe"
        executable.touch()
        choice = {"id": "github-desktop", "executable": str(executable)}
        fleet_config.save_client_choice(self.state, app, choice)
        self.assertIsNone(self.saved()["transports"]["tailnet"]["allowed_login"])
        self.assertEqual(self.saved()["components"]["app"]["options"]["git_client"], choice)
        # Failure preserves the old runtime choice and cannot replace newer settings.
        self.path.write_bytes(self.path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            fleet_config.save_client_choice(self.state, app, None)
        self.assertEqual(app["git_client"], choice)

    def test_incompatible_setup_refuses_before_network(self):
        del self.doc["components"]["sync"]
        self.write()
        with patch("sync_suggester.repo_exists", side_effect=AssertionError), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(sync_suggester.main(["--settings-home", str(self.home), "init", "--machine-id", "other-machine",
                                                  "--state-repo", "example/new-status", "--create-state-repo"]), 2)
        del self.doc["components"]["app"]
        self.write()
        with patch("fleet_app.require_gh", side_effect=AssertionError):
            self.assertEqual(self.app_command("peer", "--root", str(self.root), "--label", "other label",
                                              "--repo", "example/new-status", "--create-repo",
                                              "--acknowledge-initial-scan", "--configure-only"), 2)

    def test_shared_transport_edit_refuses_before_optional_repo_creation(self):
        self.doc["components"]["sync"]["options"]["transport_names"] = ["repo"]
        self.write()
        with patch("fleet_app.require_gh", side_effect=AssertionError):
            self.assertEqual(self.app_command("transports", "--repo", "example/new-status", "--create-repo"), 2)

    def test_invalid_profile_errors_are_exit_codes_not_tracebacks(self):
        with patch.dict(os.environ, {"GITSPECOPS_HOME": "relative-invalid"}), redirect_stderr(io.StringIO()):
            self.assertEqual(sync_suggester.main(["check", "--root", str(self.root)]), 2)

    def test_settings_exclusions_apply_without_component_enrollment(self):
        self.doc["components"].pop("sync")
        self.doc["defaults"]["scope"] = {"exclude_paths": [str(self.root)]}
        self.write()
        args = sync_suggester.build_parser().parse_args(["--settings-home", str(self.home), "check", "--root", str(self.root)])
        with patch("sync_suggester.open_transport", side_effect=AssertionError), redirect_stderr(io.StringIO()):
            self.assertEqual(sync_suggester._resolve(args), 2)

    def test_cli_recursion_save_and_unrelated_settings_preserved(self):
        before_app = copy.deepcopy(self.doc["components"]["app"])
        cli = cli_config.load_config(self.state)
        cli["roots"][0]["recursive"] = True
        cli["stale_hours"] = 48
        cli_config.save_config(self.state, cli)
        self.assertTrue(cli_config.load_config(self.state)["roots"][0]["recursive"])
        self.assertEqual(self.saved()["components"]["app"], before_app)

    def test_missing_transport_interval_is_preserved_when_changing_other_choice(self):
        del self.doc["transports"]["folder"]["seconds"]
        self.write()
        app = fleet_app.load_saved(self.state)
        self.assertEqual(app["transports"]["folder"]["seconds"], 300)
        app["share_names"] = False
        fleet_app.save_saved(self.state, app)
        self.assertNotIn("seconds", self.saved()["transports"]["folder"])

    def test_write_failure_keeps_original_and_releases_owned_lock(self):
        app = fleet_app.load_saved(self.state)
        app["share_names"] = False
        before = self.path.read_bytes()
        with patch("Special._settings.store.atomic_write_bytes", side_effect=OSError):
            with self.assertRaises(ValueError):
                fleet_app.save_saved(self.state, app)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse((self.home / ".settings.lock").exists())

    def test_invalid_common_prevents_desktop_setup_and_app_lock(self):
        self.path.write_text("{bad", encoding="utf-8")
        with patch("fleet_desktop.main", side_effect=AssertionError), redirect_stderr(io.StringIO()):
            self.assertEqual(fleet_desktop.desktop_main([]), 2)
        with patch("fleet_app.app_lock", side_effect=AssertionError):
            self.assertEqual(self.app_command("run"), 2)

    def test_unknown_runtime_fields_cannot_be_silently_discarded(self):
        app = fleet_app.load_saved(self.state)
        app["unknown_future_choice"] = True
        with self.assertRaisesRegex(ValueError, "runtime fields"):
            fleet_app.save_saved(self.state, app)

    def test_link_scope_and_source_destination_refused_without_creating_files(self):
        with patch("Special._settings.fleet.linked", return_value=True):
            with self.assertRaisesRegex(ValueError, "link"):
                cli_config.load_config(self.state)
        with self.assertRaises(ValueError):
            fleet_directory(Path(__file__).resolve().parents[2])

    def test_v1_common_profile_never_silently_upgrades_for_enrollment(self):
        self.doc = {"schema_version": 1, "defaults": {"security": {"never_publish": ["private@example.invalid"]}}}
        self.write()
        before = self.path.read_bytes()
        self.assertIsNone(cli_config.load_config(self.state))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(sync_suggester.main(["--settings-home", str(self.home), "init"]), 2)
        self.assertEqual(self.app_command("peer", "--root", str(self.root), "--acknowledge-initial-scan", "--configure-only"), 2)
        self.assertEqual(before, self.path.read_bytes())

    def test_common_cli_local_check_uses_real_disposable_git_without_writes(self):
        checkout = self.root / "checkout"
        subprocess.run(["git", "init", "-q", str(checkout)], check=True, capture_output=True)
        before = self.path.read_bytes()
        head = (checkout / ".git" / "HEAD").read_bytes()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = sync_suggester.main(["--settings-home", str(self.home), "--config-dir", str(self.state),
                                        "check", "--local-only", "--no-publish", "--no-catalog", "--json"])
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["manifest"]["machine_id"], "machine-a")
        self.assertEqual(len(result["manifest"]["repositories"]), 1)
        self.assertEqual(len(result["local_security"]), 1)
        self.assertNotIn(self.key, stdout.getvalue())
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(head, (checkout / ".git" / "HEAD").read_bytes())
        self.assertFalse((self.state / "catalog.json").exists())

    def test_key_commands_hide_by_default_and_disclose_only_when_selected_without_writes(self):
        before = self.path.read_bytes()
        for command in (sync_suggester.main, fleet_app.main):
            for show in (False, True):
                output = io.StringIO()
                args = ["--settings-home", str(self.home), "--config-dir", str(self.state), "fleet-key"]
                if show:
                    args.append("--show")
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    self.assertEqual(command(args), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["disclosed"], show)
                self.assertEqual(self.key in output.getvalue(), show)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.home / "logs").exists())

    def test_new_cli_setup_does_not_automatically_print_generated_key(self):
        self.doc = {"schema_version": 2}
        self.write()
        output = io.StringIO()
        with patch("config.new_fleet_secret", return_value=self.key), redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = sync_suggester.main(["--settings-home", str(self.home), "--config-dir", str(self.state),
                                        "init", "--machine-id", "machine-a", "--root", str(self.root)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertNotIn(self.key, output.getvalue())
        self.assertEqual(self.saved()["machine"]["fleet_secret"], self.key)

    def test_new_app_setup_does_not_automatically_print_generated_key(self):
        self.doc = {"schema_version": 2}
        self.write()
        output = io.StringIO()
        with patch("fleet_app.new_fleet_secret", return_value=self.key), \
             patch("fleet_app.resolve_machine_identity", return_value=("machine-a", "Machine A")), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = fleet_app.main(["--settings-home", str(self.home), "--config-dir", str(self.state),
                                   "peer", "--root", str(self.root), "--no-tailnet", "--acknowledge-initial-scan", "--configure-only"])
        self.assertEqual(code, 0, output.getvalue())
        self.assertNotIn(self.key, output.getvalue())
        self.assertEqual(self.saved()["machine"]["fleet_secret"], self.key)

    def test_recovery_and_git_client_commands_save_common_options(self):
        location = self.base / "recovery"
        location.mkdir()
        self.assertEqual(self.app_command("recovery", "configure", "--location", str(location),
                                          "--confirm-private-location"), 0)
        options = self.saved()["components"]["app"]["options"]
        self.assertEqual(options["recovery"]["location"], str(location))
        self.assertIs(options["recovery"]["confirmed"], True)
        executable = self.base / "desktop.exe"
        executable.touch()
        self.assertEqual(self.app_command("git-client", "--client", "github-desktop", "--executable", str(executable)), 0)
        self.assertEqual(self.app_command("git-client", "--disable"), 0)
        self.assertIsNone(self.saved()["components"]["app"]["options"]["git_client"])
        self.assertFalse((self.state / "fleet-app.json").exists())


if __name__ == "__main__":
    unittest.main()
