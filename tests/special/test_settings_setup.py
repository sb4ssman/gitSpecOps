"""Reviewed updater settings setup using invented profiles; no actual machine configuration."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()

import setup_gitspecops as command
from Special._settings import SettingsError, resolve_settings
from Special._settings import setup as subject
from Special._settings import store
from Special._settings import setup_cli
from Special import update_archive


class SetupSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="settings-setup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home, self.archive = self.root / "profile", self.root / "private-marker"
        self.archive.mkdir()
        self.env = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        # No inherited alternate legacy source in these invented profiles.
        self.old_sync = os.environ.pop("GITSPECOPS_SYNC_HOME", None)
        if self.old_sync is not None:
            self.addCleanup(os.environ.__setitem__, "GITSPECOPS_SYNC_HOME", self.old_sync)

    def save(self, document):
        self.home.mkdir(exist_ok=True)
        path = self.home / "settings.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def invoke(self, *args, answers=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             patch.object(command.sys, "stdin", SimpleNamespace(isatty=lambda: answers is not None)):
            if answers is None:
                code = command.main(list(args))
            else:
                with patch("builtins.input", side_effect=answers):
                    code = command.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_preview_creates_nothing_and_summaries_hide_values(self):
        plan = subject.prepare_setup(self.home, {"scope": {"roots": [str(self.archive)]}})
        self.assertTrue(plan.ready)
        self.assertFalse(self.home.exists())
        for value in (str(self.home), str(self.archive), "private-marker"):
            self.assertNotIn(value, (json.dumps(plan.summary()) + repr(plan)).replace("\\\\", "\\"))
        self.assertIn(str(self.archive), plan.paths()["roots"])

    def test_exact_approval_creates_profile_without_runtime_directories(self):
        plan = subject.prepare_setup(self.home, {"scope": {"roots": [str(self.archive)]},
            "output": {"format": "json"}, "logging": {"enabled": False}})
        with self.assertRaises(SettingsError):
            subject.save_setup(plan, "wrong-id")
        self.assertFalse(self.home.exists())
        subject.save_setup(plan, plan.review_id)
        self.assertEqual(list(self.home.iterdir()), [self.home / "settings.json"])
        resolved = resolve_settings("archive_update", home=self.home)
        self.assertEqual(resolved.values["scope"]["roots"], [self.archive])

    def test_existing_unrelated_settings_and_private_policy_are_preserved(self):
        original = {"schema_version": 2, "machine": {"id": "machine-a", "label": "fixture",
            "fleet_secret": "ab" * 32}, "transports": {"repo": {"name": "example/private-state"}},
            "defaults": {"security": {"never_publish": ["private-marker"]}},
            "components": {"sync": {"scope": {"roots": [str(self.root / "elsewhere")]}}}}
        self.save(original)
        plan = subject.prepare_setup(self.home, {"logging": {"enabled": False}})
        for value in ("private-marker", "ab" * 32, "example/private-state"):
            self.assertNotIn(value, json.dumps(plan.summary()) + json.dumps(plan.paths()))
        subject.save_setup(plan, plan.review_id)
        saved = json.loads((self.home / "settings.json").read_text())
        for key in ("machine", "transports", "defaults"):
            self.assertEqual(saved[key], original[key])
        self.assertEqual(saved["components"]["sync"], original["components"]["sync"])

    def test_target_and_new_legacy_source_changes_invalidate_review(self):
        for change in ("target", "legacy"):
            with self.subTest(change=change):
                home = self.root / change
                plan = subject.prepare_setup(home)
                home.mkdir()
                changed = home / "settings.json" if change == "target" else home / "gitspecops_managed_archives.json"
                changed.write_text("external change")
                with self.assertRaises(SettingsError):
                    subject.save_setup(plan, plan.review_id)
                self.assertEqual(changed.read_text(), "external change")
                if change == "legacy":
                    self.assertFalse((home / "settings.json").exists())

    def test_modified_candidate_cannot_be_saved(self):
        plan = subject.prepare_setup(self.home)
        plan.document["components"]["archive_update"]["logging"] = {"enabled": False}
        with self.assertRaises(SettingsError):
            subject.save_setup(plan, plan.review_id)
        self.assertFalse(self.home.exists())

    def test_last_input_check_runs_under_the_existing_writer(self):
        plan = subject.prepare_setup(self.home)
        def changed_before_lock(document, **kwargs):
            self.home.mkdir()
            (self.home / "gitspecops_managed_archives.json").write_text("changed")
            return store.write_settings(document, **kwargs)
        with patch.object(subject, "write_settings", side_effect=changed_before_lock), self.assertRaises(SettingsError):
            subject.save_setup(plan, plan.review_id)
        self.assertFalse((self.home / "settings.json").exists())
        self.assertFalse((self.home / ".settings.lock").exists())

    def test_noop_edit_preserves_exact_original_bytes(self):
        path = self.save({"schema_version": 2, "components": {"archive_update": {"logging": {"enabled": False}}}})
        before = path.read_bytes()
        plan = subject.prepare_setup(self.home)
        with patch.object(subject, "write_settings", side_effect=AssertionError("unnecessary write")):
            subject.save_setup(plan, plan.review_id)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_mapping_can_be_ready_while_activation_is_refused(self):
        policy = self.home / "security" / "never_publish.txt"
        policy.parent.mkdir(parents=True)
        policy.write_text("private-marker\n")
        plan = subject.prepare_setup(self.home)
        self.assertFalse(plan.ready)
        self.assertTrue(plan.summary()["migration"]["mapping_ready"])
        self.assertFalse(plan.summary()["migration"]["activation_ready"])
        with self.assertRaises(SettingsError):
            subject.save_setup(plan, plan.review_id)
        self.assertFalse((self.home / "settings.json").exists())
        self.assertEqual(policy.read_text(), "private-marker\n")

    def test_unreadable_or_invalid_configuration_never_becomes_fresh_defaults(self):
        path = self.save({"schema_version": 2})
        path.write_text('{"schema_version":2,"schema_version":2}')
        with self.assertRaises(SettingsError):
            subject.prepare_setup(self.home)
        self.assertEqual(path.read_text(), '{"schema_version":2,"schema_version":2}')

    def test_exclusion_addition_and_explicit_clear_keep_common_exclusions(self):
        common, first, second = (str(self.root / name) for name in ("common", "first", "second"))
        self.save({"schema_version": 2, "defaults": {"scope": {"exclude_paths": [common]}},
                   "components": {"archive_update": {"scope": {"exclude_paths": [first]}}}})
        plan = subject.prepare_setup(self.home, {"scope": {"exclude_paths": [second]}})
        subject.save_setup(plan, plan.review_id)
        self.assertEqual(resolve_settings("archive_update").values["scope"]["exclude_paths"],
                         [Path(common), Path(first), Path(second)])
        plan = subject.prepare_setup(self.home, clear_exclusions=True)
        subject.save_setup(plan, plan.review_id)
        self.assertEqual(resolve_settings("archive_update").values["scope"]["exclude_paths"], [Path(common)])

    def test_setup_cannot_change_security_enrollment_or_other_components(self):
        for value in ({"security": {"never_publish": []}}, {"machine": {}}, {"options": {}}):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                subject.prepare_setup(self.home, value)
        self.assertFalse(self.home.exists())

    def test_preview_save_cli_roundtrip_then_updater_uses_saved_preferences(self):
        flags = ["--settings-home", str(self.home), "--root", str(self.archive), "--format", "json", "--no-log", "--json"]
        code, out, err = self.invoke("settings-preview", *flags)
        self.assertEqual(code, 0, err)
        token = json.loads(out)["review_id"]
        self.assertFalse(self.home.exists())
        code, out, err = self.invoke("settings-save", *flags, "--approve", token)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["status"], "saved")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = update_archive.main(["--settings-home", str(self.home), "--scan-only"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["roots"][0]["scan"]["root"], str(self.archive))
        self.assertFalse((self.home / "logs").exists())

    def test_cli_approval_does_not_apply_to_changed_preferences(self):
        flags = ["--settings-home", str(self.home), "--no-log", "--json"]
        _, out, _ = self.invoke("settings-preview", *flags)
        token = json.loads(out)["review_id"]
        code, out, _ = self.invoke("settings-save", *flags, "--root", str(self.archive), "--approve", token)
        self.assertEqual(code, 2)
        self.assertFalse(self.home.exists())

    def test_guided_save_and_cancel_require_explicit_confirmation(self):
        for confirmation in ("cancel", "SAVE"):
            home = self.root / confirmation
            answers = [str(self.archive), "", "n", "stdout", "json", "n", confirmation]
            code, out, err = self.invoke("settings", "--settings-home", str(home), answers=answers)
            self.assertEqual(code, 0, err)
            self.assertEqual((home / "settings.json").exists(), confirmation == "SAVE")
            self.assertNotIn(str(self.archive), out)

    def test_eof_and_unattended_guidance_create_nothing(self):
        code, _, _ = self.invoke("settings", "--settings-home", str(self.home), answers=[EOFError()])
        self.assertEqual(code, 0)
        self.assertFalse(self.home.exists())
        self.assertEqual(self.invoke("settings", "--settings-home", str(self.home))[0], 2)
        self.assertFalse(self.home.exists())

    def test_migration_preview_never_activates_or_echoes_policy_values(self):
        policy = self.home / "security" / "never_publish.txt"
        policy.parent.mkdir(parents=True)
        policy.write_text("private-marker\n")
        code, out, _ = self.invoke("settings-migration-preview", "--settings-home", str(self.home), "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["activation_ready"])
        self.assertNotIn("private-marker", out)
        self.assertFalse((self.home / "settings.json").exists())

    def test_settings_flags_cannot_be_silently_ignored_by_other_actions(self):
        for args in (("bootstrap", "--root", str(self.archive)), ("settings-preview", "--approve", "wrong"),
                     ("settings-migration-preview", "--root", str(self.archive))):
            with self.subTest(args=args), self.assertRaises(SystemExit) as stopped:
                self.invoke(*args)
            self.assertEqual(stopped.exception.code, 2)
        self.assertFalse(self.home.exists())

    def test_help_and_missing_approval_never_prepare_or_write_a_profile(self):
        with patch.object(setup_cli, "prepare_setup", side_effect=AssertionError("profile read")):
            with self.assertRaises(SystemExit) as stopped:
                self.invoke("--help")
            self.assertEqual(stopped.exception.code, 0)
            self.assertEqual(self.invoke("settings-save", "--json")[0], 2)
        self.assertFalse(self.home.exists())

    def test_private_paths_require_explicit_local_review_channel(self):
        flags = ["settings-preview", "--settings-home", str(self.home), "--root", str(self.archive), "--json"]
        code, out, err = self.invoke(*flags)
        self.assertEqual(code, 0, err)
        self.assertNotIn("paths", json.loads(out))
        code, out, err = self.invoke(*flags, "--show-paths")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["paths"]["roots"], [str(self.archive)])
        self.assertFalse(self.home.exists())

    def test_path_review_still_conceals_a_key_even_when_embedded_in_a_path(self):
        key = "ab" * 32
        self.save({"schema_version": 2, "machine": {"id": "machine-a", "label": "fixture", "fleet_secret": key},
                   "components": {"archive_update": {"scope": {"roots": [str(self.root / key)]}}}})
        view = subject.prepare_setup(self.home).paths()
        self.assertNotIn(key, json.dumps(view))

    def test_json_requires_explicit_action_before_any_interactive_menu(self):
        with self.assertRaises(SystemExit) as stopped:
            self.invoke("--json", answers=[])
        self.assertEqual(stopped.exception.code, 2)
        self.assertFalse(self.home.exists())

    def test_native_setup_wrapper_preserves_caller_relative_paths(self):
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if shell is None:
                self.skipTest("PowerShell is unavailable")
            invocation = [shell, "-NoProfile", "-File", str(ROOT / "run_setup.ps1")]
        else:
            shell = shutil.which("sh")
            if shell is None:
                self.skipTest("POSIX shell is unavailable")
            invocation = [shell, str(ROOT / "run_setup.sh")]
        environment = {**os.environ, "UV_OFFLINE": "1", "UV_PYTHON": sys.executable,
                       "UV_CACHE_DIR": str(self.root / "uv-cache")}
        completed = subprocess.run([*invocation, "settings-preview", "--settings-home", str(self.home),
                                   "--root", ".", "--no-log", "--json", "--show-paths"],
                                  cwd=self.archive, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["paths"]["roots"], [str(self.archive)])
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
