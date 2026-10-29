"""Archive/policy settings switch and recovery using invented disposable profiles only.

Run directly with Python. No real settings, Git operations, launchers, schedules or network.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

import setup_gitspecops as command
from Special._settings import SettingsError, resolve_settings
from Special._settings import existing as subject
from Special._archive.registry import load_registry


class ExistingSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "profile-private-marker"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        old = os.environ.pop("GITSPECOPS_SYNC_HOME", None)
        if old is not None:
            self.addCleanup(os.environ.__setitem__, "GITSPECOPS_SYNC_HOME", old)
        self.registry = self.home / "gitspecops_managed_archives.json"
        self.policy = self.home / "security" / "never_publish.txt"
        self.policy.parent.mkdir()
        self.policy.write_bytes(b"# original comment\r\nprivate@example.invalid\r\n")
        records = []
        for number in range(3):
            root = self.base / ("archive-" + str(number))
            root.mkdir()
            records.append({"root": str(root), "mode": "update", "approved_remote_prefixes": ["https://example.invalid/"],
                            "launcher": str(root / "update_archive.bat"), "installed_at": "original-time",
                            "retained_extra": {"unknown_operational_field": number}})
        self.raw = {"version": 1, "installations": records}
        self.registry.write_bytes(json.dumps(self.raw, indent=1).encode() + b"\r\n")
        self.launcher = Path(records[1]["launcher"])
        self.launcher.write_text("echo --approved-remote-prefix synthetic\n", encoding="utf-8")
        self.original_registry = self.registry.read_bytes()
        self.original_policy = self.policy.read_bytes()

    def plan(self):
        return subject.prepare_existing(self.home)

    def save(self, plan):
        return subject.save_existing(plan, plan.review_id, writers_stopped=True, launchers_reviewed=True)

    def invoke(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = command.main([*arguments, "--settings-home", str(self.home), "--json"])
        return code, out.getvalue(), err.getvalue()

    def interrupted(self):
        plan = self.plan()
        with patch.object(subject, "write_settings", side_effect=SettingsError("injected failure")):
            with self.assertRaises(SettingsError):
                self.save(plan)
        return plan

    def test_plan_reads_only_and_masks_values(self):
        plan = self.plan()
        record = plan.summary()
        self.assertEqual(record["archives"], 3)
        self.assertEqual(record["protected_values"], 1)
        self.assertFalse(record["changes_launchers"])
        self.assertTrue(any(item.get("copied_remote_allowance") for item in record["launcher_plan"]))
        for private in (str(self.home), "private@example.invalid", "https://example.invalid/"):
            self.assertNotIn(private, json.dumps(record))
            self.assertNotIn(private, repr(plan))
        self.assertFalse((self.home / subject.BUNDLE_ROOT).exists())
        self.assertEqual(self.registry.read_bytes(), self.original_registry)
        self.assertEqual(self.policy.read_bytes(), self.original_policy)

    def test_explicit_save_preserves_bytes_choices_and_receipts(self):
        plan = self.plan()
        launcher_before = self.launcher.read_bytes()
        self.assertEqual(self.save(plan)["status"], "saved")
        self.assertEqual((plan.bundle / "originals" / self.registry.name).read_bytes(), self.original_registry)
        self.assertEqual((plan.bundle / "originals/security/never_publish.txt").read_bytes(), self.original_policy)
        saved_registry = json.loads(self.registry.read_bytes())
        self.assertEqual(saved_registry, {**self.raw, "version": 2})
        self.assertEqual(self.policy.read_bytes(), self.original_policy)
        self.assertEqual(self.launcher.read_bytes(), launcher_before)
        loaded = load_registry(home=self.home)
        self.assertEqual(len(loaded["installations"]), 3)
        self.assertEqual(loaded["installations"][0]["installed_at"], "original-time")
        self.assertEqual(resolve_settings("security", home=self.home).values["security"]["never_publish"], ["private@example.invalid"])
        self.assertNotIn("machine", plan.document)
        self.assertNotIn("transports", plan.document)

    def test_no_approval_or_attestations_means_no_writes(self):
        plan = self.plan()
        for kwargs in ({"approve": "wrong", "writers_stopped": True, "launchers_reviewed": True},
                       {"approve": plan.review_id, "launchers_reviewed": True},
                       {"approve": plan.review_id, "writers_stopped": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SettingsError):
                subject.save_existing(plan, **kwargs)
        self.assertFalse(plan.bundle.exists())
        self.assertEqual(self.registry.read_bytes(), self.original_registry)

    def test_stale_source_absent_input_target_and_artifact_are_rejected(self):
        cases = (self.policy, self.home / "security/safe.txt", self.home / "settings.json", self.launcher)
        for path in cases:
            with self.subTest(path=path.name):
                before = path.read_bytes() if path.exists() else None
                plan = self.plan()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"changed")
                with self.assertRaises(SettingsError):
                    self.save(plan)
                self.assertFalse(plan.bundle.exists())
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)

    def test_mutated_plan_rejected(self):
        plan = self.plan()
        plan.document["defaults"]["security"]["never_publish"] = []
        with self.assertRaises(SettingsError):
            self.save(plan)
        self.assertFalse(plan.bundle.exists())

    def test_busy_switch_and_registry_locks_are_not_removed(self):
        for name in (".settings-switch.lock", ".archive-registry.lock", ".settings.lock"):
            with self.subTest(name=name):
                path = self.home / name
                path.write_bytes(b"owned by another writer")
                plan = self.plan()
                with self.assertRaises(SettingsError):
                    self.save(plan)
                self.assertEqual(path.read_bytes(), b"owned by another writer")
                self.assertEqual(self.registry.read_bytes(), self.original_registry)
                path.unlink()
                self.assertFalse(plan.bundle.exists())

    def test_originals_failure_does_not_mark_receipts(self):
        plan = self.plan()
        with patch.object(subject, "_exclusive", side_effect=OSError), self.assertRaises(SettingsError):
            self.save(plan)
        self.assertEqual(self.registry.read_bytes(), self.original_registry)
        self.assertFalse((self.home / "settings.json").exists())
        with self.assertRaises(SettingsError):
            subject.inspect_existing(self.home, plan.review_id)

    def test_originals_flush_failure_does_not_touch_live_files(self):
        plan = self.plan()
        with patch.object(subject.os, "fsync", side_effect=OSError), self.assertRaises(SettingsError):
            self.save(plan)
        self.assertEqual(self.registry.read_bytes(), self.original_registry)
        self.assertEqual(self.policy.read_bytes(), self.original_policy)
        self.assertFalse((self.home / "settings.json").exists())

    def test_receipt_write_failure_is_resumable_from_preserved_bundle(self):
        plan = self.plan()
        with patch.object(subject, "atomic_write_bytes", side_effect=OSError), self.assertRaises(SettingsError):
            self.save(plan)
        self.assertEqual(self.registry.read_bytes(), self.original_registry)
        status = subject.inspect_existing(self.home, plan.review_id)
        self.assertTrue(status["can_resume"])
        self.assertFalse(status["receipt_only"])
        subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
        self.assertEqual(subject.inspect_existing(self.home, plan.review_id)["status"], "saved")

    def test_interruption_refuses_old_authority_then_explicit_resume_works(self):
        plan = self.interrupted()
        with self.assertRaises(SettingsError):
            load_registry(home=self.home)
        status = subject.inspect_existing(self.home, plan.review_id)
        self.assertTrue(status["can_resume"])
        self.assertTrue(status["receipt_only"])
        with self.assertRaises(SettingsError):
            subject.resume_existing(self.home, plan.review_id)
        subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
        before = (self.home / "settings.json").read_bytes()
        result = subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(before, (self.home / "settings.json").read_bytes())

    def test_status_is_read_only(self):
        plan = self.interrupted()
        before = {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}
        subject.inspect_existing(self.home, plan.review_id)
        self.assertEqual(before, {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()})

    def test_resume_refuses_newer_settings(self):
        plan = self.interrupted()
        target = self.home / "settings.json"
        target.write_text('{"schema_version":2}', encoding="utf-8")
        before = target.read_bytes()
        self.assertFalse(subject.inspect_existing(self.home, plan.review_id)["can_resume"])
        with self.assertRaises(SettingsError):
            subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
        self.assertEqual(before, target.read_bytes())

    def test_resume_refuses_changed_policy_receipts_and_launchers(self):
        plan = self.interrupted()
        for path in (self.policy, self.registry, self.launcher):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(before + b" ")
                self.assertFalse(subject.inspect_existing(self.home, plan.review_id)["can_resume"])
                with self.assertRaises(SettingsError):
                    subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
                path.write_bytes(before)

    def test_tampered_original_candidate_and_manifest_cannot_resume(self):
        plan = self.interrupted()
        for path in (plan.bundle / "originals" / self.registry.name, plan.bundle / "candidate.json", plan.bundle / "manifest.json"):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(b"{}")
                with self.assertRaises(SettingsError):
                    subject.resume_existing(self.home, plan.review_id, writers_stopped=True, launchers_reviewed=True)
                path.write_bytes(before)

    def test_existing_bundle_is_not_overwritten(self):
        plan = self.plan()
        plan.bundle.mkdir(parents=True)
        marker = plan.bundle / "preserved-marker"
        marker.write_bytes(b"keep")
        with self.assertRaises(SettingsError):
            self.save(plan)
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertEqual(self.registry.read_bytes(), self.original_registry)

    def test_policy_only_profile_needs_no_archive_or_fleet(self):
        self.registry.unlink()
        plan = self.plan()
        self.save(plan)
        self.assertFalse(self.registry.exists())
        self.assertEqual(subject.inspect_existing(self.home, plan.review_id)["status"], "saved")

    def test_allowed_values_are_preserved(self):
        path = self.policy.with_name("safe.txt")
        path.write_bytes(b"# generic\ngit@github.com\n")
        plan = self.plan()
        self.save(plan)
        self.assertEqual(resolve_settings("security", home=self.home).values["security"]["safe_values"], ["git@github.com"])
        self.assertEqual(path.read_bytes(), b"# generic\ngit@github.com\n")

    def test_fleet_profiles_and_overrides_are_explicitly_unsupported(self):
        path = self.home / "sync-suggester/config.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(SettingsError, "fleet settings|Fleet settings"):
            self.plan()
        path.unlink()
        with patch.dict(os.environ, {"GITSPECOPS_SYNC_HOME": str(self.base / "other")}):
            with self.assertRaises(SettingsError):
                self.plan()

    def test_invalid_duplicate_and_existing_target_refused(self):
        self.registry.write_bytes(b'{"version":1,"version":1,"installations":[]}')
        with self.assertRaises(SettingsError):
            self.plan()
        self.registry.write_bytes(self.original_registry)
        (self.home / "settings.json").write_text('{"schema_version":2}', encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.plan()

    def test_duplicate_archive_roots_are_not_silently_collapsed(self):
        self.raw["installations"].append(dict(self.raw["installations"][0]))
        self.registry.write_text(json.dumps(self.raw), encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.plan()

    def test_outside_root_launcher_and_source_destination_refused(self):
        self.raw["installations"][0]["launcher"] = str(self.base / "outside.bat")
        self.registry.write_text(json.dumps(self.raw), encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.plan()
        with self.assertRaises(ValueError):
            subject.prepare_existing(Path(__file__).resolve().parents[2])

    def test_completed_switch_does_not_fall_back_when_settings_are_deleted(self):
        plan = self.plan()
        self.save(plan)
        (self.home / "settings.json").unlink()
        with self.assertRaises(SettingsError):
            load_registry(home=self.home)
        with self.assertRaises(SettingsError):
            resolve_settings("security", home=self.home)

    def test_cli_plan_save_status_resume_and_private_paths(self):
        code, output, _ = self.invoke("settings-existing-plan")
        self.assertEqual(code, 0)
        record = json.loads(output)
        self.assertNotIn(str(self.home), output)
        review_id = record["review_id"]
        code, _, _ = self.invoke("settings-existing-save", "--approve", review_id,
                                  "--legacy-writers-stopped", "--launcher-plan-reviewed")
        self.assertEqual(code, 0)
        code, output, _ = self.invoke("settings-existing-status", "--switch-id", review_id)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "saved")
        code, output, _ = self.invoke("settings-existing-resume", "--switch-id", review_id,
                                       "--legacy-writers-stopped", "--launcher-plan-reviewed")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "unchanged")

    def test_cli_rejects_irrelevant_flags_before_profile_read(self):
        cases = (("settings-existing-plan", "--root", str(self.base)),
                 ("settings-existing-plan", "--legacy-writers-stopped"),
                 ("settings-existing-status", "--launcher-plan-reviewed"),
                 ("bootstrap", "--switch-id", "bad"))
        with patch.object(subject, "prepare_existing", side_effect=AssertionError), redirect_stderr(io.StringIO()):
            for args in cases:
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    command.main(list(args))

    def test_help_does_not_read_profiles(self):
        with patch.object(subject, "prepare_existing", side_effect=AssertionError), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                command.main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_guided_cancellation_and_eof_do_not_write(self):
        for answers in (["no"], ["STOPPED", "no"], ["STOPPED", "REVIEWED", "no"], [EOFError()]):
            with self.subTest(answers=answers), patch.object(command.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                 patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()):
                self.assertEqual(command.main(["settings-existing", "--settings-home", str(self.home)]), 0)
            self.assertFalse((self.home / subject.BUNDLE_ROOT).exists())
            self.assertEqual(self.registry.read_bytes(), self.original_registry)

    def test_guided_save_requires_all_three_typed_answers(self):
        with patch.object(command.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
             patch("builtins.input", side_effect=["STOPPED", "REVIEWED", "SAVE"]), redirect_stdout(io.StringIO()):
            self.assertEqual(command.main(["settings-existing", "--settings-home", str(self.home)]), 0)
        self.assertTrue((self.home / "settings.json").exists())

    def test_unattended_guidance_and_path_errors_are_structured(self):
        with patch.object(command.sys, "stdin", SimpleNamespace(isatty=lambda: False)), redirect_stderr(io.StringIO()):
            self.assertEqual(command.main(["settings-existing", "--settings-home", str(self.home)]), 2)
        with redirect_stdout(io.StringIO()) as output:
            code = command.main(["settings-existing-plan", "--settings-home", str(Path(__file__).resolve().parents[2]), "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")
        self.assertNotIn(str(self.base), output.getvalue())

    def test_explicit_path_review_does_not_reveal_policy_values(self):
        code, output, _ = self.invoke("settings-existing-plan", "--show-paths")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["paths"]["settings"], str(self.home / "settings.json"))
        self.assertNotIn("private@example.invalid", output)
        self.assertNotIn("https://example.invalid/", output)

    def test_writer_callback_rechecks_after_receipt_mark(self):
        plan = self.plan()
        from Special._settings.store import write_settings as real_write

        def changed_before_writer(*args, **kwargs):
            self.policy.write_bytes(self.original_policy + b"changed\n")
            return real_write(*args, **kwargs)

        with patch.object(subject, "write_settings", side_effect=changed_before_writer), self.assertRaises(SettingsError):
            self.save(plan)
        self.assertFalse((self.home / "settings.json").exists())
        self.assertFalse(subject.inspect_existing(self.home, plan.review_id)["can_resume"])

    def test_save_then_exception_can_be_inspected_without_overwriting(self):
        plan = self.plan()
        from Special._settings.store import write_settings as real_write

        def saved_then_failed(*args, **kwargs):
            real_write(*args, **kwargs)
            raise OSError("failure after replacement")

        with patch.object(subject, "write_settings", side_effect=saved_then_failed), self.assertRaises(SettingsError):
            self.save(plan)
        before = (self.home / "settings.json").read_bytes()
        self.assertEqual(subject.inspect_existing(self.home, plan.review_id)["status"], "saved")
        self.assertEqual(subject.resume_existing(self.home, plan.review_id, writers_stopped=True,
                                                launchers_reviewed=True)["status"], "unchanged")
        self.assertEqual(before, (self.home / "settings.json").read_bytes())

    def test_bad_receipt_metadata_is_refused_before_writes(self):
        self.raw["installations"][0]["extra"] = float("nan")
        self.registry.write_text(json.dumps(self.raw), encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.plan()
        self.assertFalse((self.home / subject.BUNDLE_ROOT).exists())

    def test_bad_recovery_id_cannot_escape_profile(self):
        for review_id in ("../elsewhere", "", "a" * 31, "G" * 32):
            with self.subTest(review_id=review_id), self.assertRaises(SettingsError):
                subject.inspect_existing(self.home, review_id)


if __name__ == "__main__":
    unittest.main()
