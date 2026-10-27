"""Settings resolution in disposable folders; no real user settings or Git operations."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special import _settings as subject  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="settings-test-")))
        self.home = self.root / "selected-home"
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        stack.enter_context(patch.object(subject, "config_home", return_value=self.home))

    def save(self, **entries):
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.home / subject.SETTINGS_NAME
        path.write_text(json.dumps({"schema_version": 1, **entries}), encoding="utf-8")
        return path

    def test_first_use_returns_defaults_without_creating_the_home(self):
        result = subject.resolve_settings("archive_update")
        self.assertFalse(self.home.exists())
        self.assertFalse(result.configured)
        self.assertEqual(result.home_source, "platform-default")
        self.assertEqual(result.values["output"]["mode"], "stdout")
        self.assertEqual(result.values["logging"]["directory"], self.home / "logs")
        self.assertEqual(result.values["scope"]["roots"], [])

    def test_effective_values_and_sources_follow_precedence(self):
        path = self.save(defaults={"output": {"format": "json", "mode": "both"}},
                         components={"archive_update": {"output": {"mode": "file"}}})
        before = path.read_bytes()
        result = subject.resolve_settings("archive_update", overrides={"output": {"mode": "stdout"}})
        self.assertEqual(result.values["output"]["mode"], "stdout")
        self.assertEqual(result.values["output"]["format"], "json")
        self.assertEqual(result.sources["output.mode"], ["explicit"])
        self.assertEqual(result.sources["output.format"], ["settings"])
        component = subject.resolve_settings("archive_update")
        self.assertEqual(component.sources["output.mode"], ["component:archive_update"])
        self.assertEqual(subject.resolve_settings("security").values["output"]["mode"], "both")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.home.iterdir()), [path])

    def test_explicit_home_wins_over_environment(self):
        os.environ["GITSPECOPS_HOME"] = str(self.root / "environment-home")
        result = subject.resolve_settings(home=self.home)
        self.assertEqual(result.home, self.home)
        self.assertEqual(result.home_source, "explicit")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_environment_home_is_honored(self):
        environment_home = self.root / "environment-home"
        os.environ["GITSPECOPS_HOME"] = str(environment_home)
        with patch.object(subject, "config_home", return_value=environment_home):
            result = subject.resolve_settings()
        self.assertEqual(result.home, environment_home)
        self.assertEqual(result.home_source, "environment")
        self.assertFalse(environment_home.exists())

    def test_legacy_sync_home_is_not_silently_ignored_or_applied_to_other_components(self):
        os.environ["GITSPECOPS_SYNC_HOME"] = str(self.root / "old-sync-home")
        with self.assertRaises(subject.SettingsError):
            subject.resolve_settings("sync")
        self.assertEqual(subject.resolve_settings("sync", home=self.home).home, self.home)
        self.assertEqual(subject.resolve_settings("archive_update").home, self.home)
        self.assertFalse(self.home.exists())

    def test_invalid_environment_is_an_error_without_default_fallback(self):
        for value in ("", "relative-home"):
            with self.subTest(value=value), patch.dict(os.environ, {"GITSPECOPS_HOME": value}):
                with self.assertRaises(subject.SettingsError):
                    subject.resolve_settings()
        self.assertFalse(self.home.exists())

    def test_invalid_explicit_paths_are_sanitized_errors(self):
        for value in ("", "bad\0path", 42):
            with self.subTest(value=value), self.assertRaises(subject.SettingsError):
                subject.resolve_settings(home=value)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_relative_paths_are_anchored_to_the_selected_home(self):
        self.save(defaults={"scope": {"roots": ["repositories"], "exclude_paths": ["private"]},
                            "logging": {"directory": "events"},
                            "output": {"directory": "reports"}})
        result = subject.resolve_settings()
        self.assertEqual(result.values["scope"]["roots"], [self.home / "repositories"])
        self.assertEqual(result.values["scope"]["exclude_paths"], [self.home / "private"])
        self.assertEqual(result.values["logging"]["directory"], self.home / "events")
        self.assertEqual(result.values["output"]["directory"], self.home / "reports")
        self.assertFalse((self.home / "events").exists())

    def test_component_and_explicit_values_cannot_remove_exclusions(self):
        self.save(defaults={"scope": {"exclude_paths": ["private"]},
                            "security": {"never_publish": ["protected-marker"]}},
                  components={"archive_update": {"scope": {"exclude_paths": ["other"]},
                                                  "security": {"never_publish": []}}})
        result = subject.resolve_settings("archive_update", overrides={"scope": {"exclude_paths": []},
                                                                      "security": {"never_publish": []}})
        self.assertEqual(result.values["scope"]["exclude_paths"], [self.home / "private", self.home / "other"])
        self.assertEqual(result.values["security"]["never_publish"], ["protected-marker"])

    def test_conflicting_safe_and_blocked_values_are_errors(self):
        self.save(defaults={"security": {"never_publish": ["protected-marker"]}})
        with self.assertRaises(subject.SettingsError) as error:
            subject.resolve_settings(overrides={"security": {"safe_values": ["PROTECTED-MARKER"]}})
        self.assertNotIn("protected-marker", str(error.exception))

    def test_invalid_unselected_component_is_not_silently_ignored(self):
        self.save(components={"security": {"logging": {"enabled": "yes"}}})
        with self.assertRaises(subject.SettingsError):
            subject.resolve_settings("archive_update")

    def test_strict_schema_refuses_unknown_fields_and_wrong_types(self):
        bad_records = [
            {}, {"schema_version": True}, {"schema_version": 99},
            {"schema_version": 1, "mystery": {}},
            {"schema_version": 1, "components": {"mystery": {}}},
            {"schema_version": 1, "defaults": {"mystery": {}}},
            {"schema_version": 1, "defaults": {"output": {"token": "private-marker"}}},
            {"schema_version": 1, "defaults": {"logging": {"enabled": 1}}},
            {"schema_version": 1, "defaults": {"logging": {"max_bytes": True}}},
            {"schema_version": 1, "defaults": {"logging": {"backup_count": -1}}},
            {"schema_version": 1, "defaults": {"scope": {"roots": "not-a-list"}}},
            {"schema_version": 1, "defaults": {"security": {"never_publish": [""]}}},
            {"schema_version": 1, "defaults": {"output": {"format": "yaml"}}},
        ]
        for record in bad_records:
            with self.subTest(record=record), self.assertRaises(subject.SettingsError):
                subject.validate_document(record)

    def test_invalid_json_or_duplicate_keys_are_errors_without_overwrite(self):
        path = self.save()
        for text in ("private-marker is not JSON", '{"schema_version":1,"schema_version":1}'):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(subject.SettingsError) as error:
                subject.resolve_settings()
            self.assertNotIn("private-marker", str(error.exception))
            self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_read_error_is_not_an_empty_configuration(self):
        self.save()
        with patch.object(Path, "read_text", side_effect=PermissionError("private-marker")):
            with self.assertRaises(subject.SettingsError) as error:
                subject.resolve_settings()
        self.assertNotIn("private-marker", str(error.exception))

    def test_legacy_settings_require_migration_instead_of_fresh_defaults(self):
        legacy = self.home / "sync-suggester" / "fleet-app.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("private-marker", encoding="utf-8")
        with self.assertRaises(subject.SettingsError) as error:
            subject.resolve_settings()
        self.assertIn("migration", str(error.exception))
        self.assertNotIn("private-marker", str(error.exception))
        self.assertEqual(legacy.read_text(), "private-marker")
        self.assertFalse((self.home / subject.SETTINGS_NAME).exists())

    def test_summary_and_repr_do_not_disclose_paths_or_policy_values(self):
        self.save(defaults={"scope": {"roots": ["private-marker"]},
                            "security": {"never_publish": ["hidden-marker"], "safe_values": ["safe-marker"]}})
        result = subject.resolve_settings("security")
        rendered = json.dumps(result.summary()) + repr(result)
        for private in ("private-marker", "hidden-marker", "safe-marker", str(self.home)):
            self.assertNotIn(private, rendered)
        self.assertEqual(result.summary()["security"]["never_publish"], 1)

    def test_resolutions_do_not_mutate_defaults_or_each_other(self):
        before = copy.deepcopy(subject.DEFAULTS)
        first = subject.resolve_settings()
        first.values["scope"]["roots"].append("private-marker")
        first.summary()["sources"]["output.mode"].append("changed")
        second = subject.resolve_settings()
        self.assertEqual(subject.DEFAULTS, before)
        self.assertEqual(second.values["scope"]["roots"], [])
        self.assertEqual(second.sources["output.mode"], ["default"])


if __name__ == "__main__":
    unittest.main()
