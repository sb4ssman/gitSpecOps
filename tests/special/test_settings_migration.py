"""Settings migration/writes in invented temporary homes; no actual enrollment or Git."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._settings import SettingsError, resolve_settings, validate_document  # noqa: E402
from Special._settings_migration import preview_migration  # noqa: E402
from Special._settings_store import revision, write_settings  # noqa: E402


class SettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="settings-migration-"))).resolve()
        self.home = self.root / "user-data"
        stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def put(self, name, record):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")
        return path

    def cli(self):
        return {"schema_version": 1, "machine_id": "machine-a", "machine_label": "workstation-a",
                "fleet_secret": "ab" * 32, "roots": [{"path": str(self.root / "code"), "recursive": False}],
                "state_dir": None, "state_repo": "example/state", "stale_hours": 24,
                "expired_days": 7, "compress_manifests": False}

    def app(self):
        return {"version": 5, "mode": "peer", "machine_id": "machine-a", "label": "workstation-a",
                "fleet_secret": "ab" * 32, "roots": [str(self.root / "other-code")],
                "transports": {"repo": {"name": "example/state", "seconds": 1800},
                               "folder": {"path": str(self.root / "status"), "seconds": 300},
                               "tailnet": {"port": 8765, "allowed_login": "example-user"}},
                "fetch_minutes": 0, "share_names": False,
                "baskets": {"observe": {"mode": "all"}, "publish": {"mode": "only", "namespaces": ["example.test/team"]},
                            "capture": {"mode": "none"}},
                "recovery": {"location": None, "confirmed": False, "policies": {}},
                "observation_mode": "filesystem-events", "debounce_seconds": 0.75, "heartbeat": 30,
                "inventory_notice_acknowledged": True, "local_port": 8760,
                "git_client": {"id": "sourcetree", "executable": str(self.root / "client.exe")}}

    def test_v2_preserves_shared_identity_and_distinct_component_behavior(self):
        cli_path = self.put("sync-suggester/config.json", self.cli())
        app_path = self.put("sync-suggester/fleet-app.json", self.app())
        before = (cli_path.read_bytes(), app_path.read_bytes())
        preview = preview_migration(self.home)
        self.assertTrue(preview.ready, preview.summary())
        self.assertEqual(preview.document["machine"]["id"], "machine-a")
        self.assertEqual(preview.document["components"]["sync"]["options"]["transport_names"], ["repo"])
        self.assertEqual(preview.document["components"]["app"]["options"]["transport_names"], ["repo", "folder", "tailnet"])
        self.assertFalse(preview.document["components"]["app"]["options"]["share_names"])
        self.assertEqual(preview.document["components"]["app"]["options"]["fetch_minutes"], 0)
        self.assertEqual(preview.document["components"]["app"]["options"]["baskets"], self.app()["baskets"])
        self.assertEqual(preview.document["components"]["app"]["options"]["git_client"], self.app()["git_client"])
        self.assertEqual(preview.document["components"]["sync"]["options"]["root_recursion"],
                         {str(self.root / "code"): False})
        self.assertEqual((cli_path.read_bytes(), app_path.read_bytes()), before)
        self.assertFalse((self.home / "settings.json").exists())
        preview.verify()

    def test_private_summary_never_returns_identity_key_paths_or_policy_values(self):
        self.put("sync-suggester/config.json", self.cli())
        self.put("security/never_publish.txt", "# comment\nprotected-marker\n")
        self.put("security/safe.txt", "allowed-marker\n")
        preview = preview_migration(self.home)
        self.assertTrue(preview.ready)
        self.assertEqual(preview.document["defaults"]["security"]["never_publish"], ["protected-marker"])
        rendered = json.dumps(preview.summary()) + repr(preview)
        for value in (str(self.root), "workstation-a", "ab" * 32, "protected-marker", "allowed-marker"):
            self.assertNotIn(value, rendered)

    def test_disagreeing_identity_or_transport_is_a_blocking_named_conflict(self):
        self.put("sync-suggester/config.json", self.cli())
        record = self.app()
        record.update(machine_id="machine-b", fleet_secret="cd" * 32)
        record["transports"]["repo"]["name"] = "example/other-state"
        self.put("sync-suggester/fleet-app.json", record)
        preview = preview_migration(self.home)
        self.assertFalse(preview.ready)
        self.assertIn("machine.id", preview.conflicts)
        self.assertIn("machine.fleet_secret", preview.conflicts)
        self.assertIn("transports.repo.name", preview.conflicts)
        with self.assertRaises(SettingsError):
            preview.verify()

    def test_registry_preferences_are_extracted_without_destroying_receipts(self):
        registry = {"version": 1, "installations": [{"root": str(self.root / "archive"), "mode": "sync",
                    "approved_remote_prefixes": ["https://example.test/"], "launcher": "retained-launcher",
                    "installed_at": "2026-01-02T00:00:00", "last_status": "retained-status"}]}
        source = self.put("gitspecops_managed_archives.json", registry)
        before = source.read_bytes()
        preview = preview_migration(self.home)
        self.assertTrue(preview.ready)
        self.assertTrue(preview.retains_archive_receipts)
        archive = preview.document["components"]["archive_manage"]["options"]["archives"][0]
        self.assertEqual(set(archive), {"root", "mode", "approved_remote_prefixes"})
        self.assertEqual(source.read_bytes(), before)

    def test_invalid_unknown_and_older_source_records_block_instead_of_dropping_fields(self):
        for change in ({"unexpected": "private-marker"}, {"version": 4}, {"heartbeat": True}):
            with self.subTest(change=change):
                record = self.app()
                record.update(change)
                self.put("sync-suggester/fleet-app.json", record)
                preview = preview_migration(self.home)
                self.assertFalse(preview.ready)
                self.assertNotIn("private-marker", json.dumps(preview.summary()))

    def test_relative_enrollment_paths_require_review(self):
        record = self.cli()
        record["roots"][0]["path"] = "relative-root"
        self.put("sync-suggester/config.json", record)
        self.assertFalse(preview_migration(self.home).ready)

    def test_existing_target_blocks_migration_and_is_untouched(self):
        self.put("security/never_publish.txt", "protected-marker")
        target = self.put("settings.json", {"schema_version": 1})
        before = target.read_bytes()
        preview = preview_migration(self.home)
        self.assertIn("target.already-configured", preview.conflicts)
        self.assertFalse(preview.ready)
        self.assertEqual(target.read_bytes(), before)

    def test_changed_or_new_sources_invalidate_a_preview(self):
        source = self.put("security/never_publish.txt", "first-marker")
        preview = preview_migration(self.home)
        source.write_text("second-marker")
        with self.assertRaises(SettingsError):
            preview.verify()
        fresh = preview_migration(self.home)
        self.put("security/safe.txt", "new-marker")
        with self.assertRaises(SettingsError):
            fresh.verify()

    def test_modified_candidate_is_no_longer_the_reviewed_preview(self):
        self.put("sync-suggester/config.json", self.cli())
        preview = preview_migration(self.home)
        preview.document["machine"]["label"] = "modified-label"
        with self.assertRaises(SettingsError):
            preview.verify()

    def test_explicit_custom_sync_directory_preserves_legacy_location_choice(self):
        custom = self.root / "custom-sync"
        custom.mkdir()
        (custom / "config.json").write_text(json.dumps(self.cli()))
        os.environ["GITSPECOPS_SYNC_HOME"] = str(custom)
        self.assertFalse(preview_migration(self.home).ready)
        self.assertTrue(preview_migration(self.home, sync_directory=custom).ready)

    def test_conflicting_safe_values_block_migration(self):
        self.put("security/never_publish.txt", "protected-marker")
        self.put("security/safe.txt", "PROTECTED-MARKER")
        self.assertFalse(preview_migration(self.home).ready)

    def test_no_sources_is_not_a_ready_migration(self):
        self.assertFalse(preview_migration(self.home).ready)
        self.assertFalse(self.home.exists())

    def test_writer_creates_validated_settings_and_resolver_reads_v2(self):
        self.put("sync-suggester/config.json", self.cli())
        preview = preview_migration(self.home)
        saved_revision = write_settings(preview.document, home=self.home, check_sources=preview.verify)
        self.assertEqual(revision(self.home / "settings.json"), saved_revision)
        result = resolve_settings("sync", home=self.home)
        self.assertEqual(result.schema_version, 2)
        self.assertEqual(result.values["machine"]["id"], "machine-a")
        self.assertEqual(result.values["scope"]["roots"], [self.root / "code"])
        self.assertEqual(result.values["options"]["transport_names"], ["repo"])
        self.assertNotIn("ab" * 32, json.dumps(result.summary()))
        self.assertFalse((self.home / ".settings.lock").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.home / "settings.json").stat().st_mode), 0o600)

    def test_writer_rejects_invalid_data_before_creating_directories(self):
        with self.assertRaises(SettingsError):
            write_settings({"schema_version": 2, "machine": {"id": "bad"}}, home=self.home)
        self.assertFalse(self.home.exists())
        with self.assertRaises(SettingsError):
            write_settings({"schema_version": 2}, home="")

    def test_writer_requires_exact_revision_before_replacement(self):
        document = {"schema_version": 2}
        old_revision = write_settings(document, home=self.home)
        target = self.home / "settings.json"
        before = target.read_bytes()
        with self.assertRaises(SettingsError):
            write_settings(document, home=self.home)
        self.assertEqual(target.read_bytes(), before)
        changed = {"schema_version": 2, "defaults": {"output": {"format": "json"}}}
        new_revision = write_settings(changed, home=self.home, expected_revision=old_revision)
        self.assertNotEqual(old_revision, new_revision)
        with self.assertRaises(SettingsError):
            write_settings(document, home=self.home, expected_revision=old_revision)
        self.assertEqual(json.loads(target.read_text()), changed)

    def test_busy_writer_does_not_remove_another_writers_lock(self):
        self.home.mkdir()
        lock = self.home / ".settings.lock"
        lock.write_text("other writer")
        with self.assertRaises(SettingsError):
            write_settings({"schema_version": 2}, home=self.home)
        self.assertEqual(lock.read_text(), "other writer")
        self.assertFalse((self.home / "settings.json").exists())

    def test_failed_atomic_replace_preserves_original_and_removes_temporary_files(self):
        old_revision = write_settings({"schema_version": 2}, home=self.home)
        target = self.home / "settings.json"
        before = target.read_bytes()
        with patch("Basic._files.os.replace", side_effect=OSError("private-marker")):
            with self.assertRaises(SettingsError) as stopped:
                write_settings({"schema_version": 2, "defaults": {}}, home=self.home,
                               expected_revision=old_revision)
        self.assertNotIn("private-marker", str(stopped.exception))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.home.iterdir()), [target])

    def test_stale_source_check_prevents_initial_settings_write(self):
        source = self.put("security/never_publish.txt", "first-marker")
        preview = preview_migration(self.home)
        source.write_text("second-marker")
        with self.assertRaises(SettingsError):
            write_settings(preview.document, home=self.home, check_sources=preview.verify)
        self.assertFalse((self.home / "settings.json").exists())
        self.assertFalse((self.home / ".settings.lock").exists())

    def test_lock_cleanup_failure_reports_that_settings_were_saved(self):
        with patch.object(Path, "unlink", side_effect=PermissionError("private-marker")):
            with self.assertRaises(SettingsError) as stopped:
                write_settings({"schema_version": 2}, home=self.home)
        self.assertIn("were saved", str(stopped.exception))
        self.assertNotIn("private-marker", str(stopped.exception))
        self.assertTrue((self.home / "settings.json").exists())
        self.assertTrue((self.home / ".settings.lock").exists())

    def test_v1_remains_readable_and_v2_rejects_undefined_or_unsafe_records(self):
        self.assertEqual(validate_document({"schema_version": 1})["schema_version"], 1)
        bad = [
            {"schema_version": 1, "machine": {}},
            {"schema_version": 2, "components": {"app": {"options": {"surprise": True}}}},
            {"schema_version": 2, "components": {"sync": {"options": {"transport_names": ["repo"]}}}},
            {"schema_version": 2, "machine": {"id": "..", "label": "example", "fleet_secret": "ab" * 32}},
        ]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(SettingsError):
                validate_document(document)


if __name__ == "__main__":
    unittest.main()
