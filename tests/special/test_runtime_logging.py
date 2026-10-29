"""Counts-only operational logging, rotation and cooperating processes in temporary homes."""
from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special._runtime import logger
from Special._runtime.files import RuntimeIOError
from Special._settings import resolve_settings


def writer(home, count):
    settings = resolve_settings("archive_update", home=home)
    output = logger.configure_logging(settings, "archive_update")
    try:
        for index in range(count):
            output.event("fixture_event", repositories=index)
    finally:
        output.close()


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="operation-logging-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"

    def settings(self, **preferences):
        return resolve_settings("archive_update", home=self.home, overrides={"logging": preferences})

    def test_disabled_logging_creates_nothing(self):
        output = logger.configure_logging(self.settings(enabled=False), "archive_update")
        output.event("fixture_event", repositories=3)
        output.close()
        self.assertFalse(self.home.exists())

    def test_rotation_is_bounded_and_zero_backups_retains_only_current_log(self):
        for backups in (0, 2):
            directory = self.home / str(backups)
            output = logger.configure_logging(self.settings(directory=str(directory), max_bytes=240,
                                                             backup_count=backups), "archive_update")
            for index in range(12):
                output.event("fixture_event", repositories=index)
            output.close()
            files = sorted(directory.glob("archive_update.log*"))
            self.assertLessEqual(len(files), backups + 1)
            records = [json.loads(line) for file in files for line in file.read_text().splitlines()]
            self.assertTrue(records)
            self.assertEqual(json.loads((directory / "archive_update.log").read_text().splitlines()[-1])["repositories"], 11)

    def test_busy_lock_is_retained_and_never_redirects(self):
        directory = self.home / "logs"
        directory.mkdir(parents=True)
        lock = directory / "archive_update.log.lock"
        lock.write_text("existing lock")
        with patch.object(logger, "LOCK_WAIT_SECONDS", 0), self.assertRaises(RuntimeIOError) as stopped:
            logger.configure_logging(self.settings(), "archive_update")
        self.assertEqual(stopped.exception.code, "logging_busy")
        self.assertEqual(lock.read_text(), "existing lock")
        self.assertFalse((directory / "archive_update.log").exists())

    def test_error_events_survive_warning_level_without_raw_diagnostics(self):
        output = logger.configure_logging(self.settings(level="WARNING"), "archive_update")
        output.event("archive_finished", repositories=2)
        output.event("execution_finished", exit_code=1)
        output.close()
        records = [json.loads(line) for line in (self.home / "logs" / "archive_update.log").read_text().splitlines()]
        self.assertEqual([record["event"] for record in records], ["execution_finished"])

    def test_runtime_write_failures_are_errors_and_raw_fields_are_refused(self):
        output = logger.configure_logging(self.settings(), "archive_update")
        with self.assertRaises(ValueError):
            output.event("fixture_event", path="private-marker")
        with patch.object(output.handler, "_open", side_effect=PermissionError("private-marker")), \
             self.assertRaises(RuntimeIOError) as stopped:
            output.event("fixture_event", repositories=1)
        self.assertNotIn("private-marker", str(stopped.exception))
        output.close()
        self.assertFalse((self.home / "logs" / "archive_update.log.lock").exists())

    def test_concurrent_processes_preserve_all_complete_records(self):
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2,
            "defaults": {"logging": {"max_bytes": 1000, "backup_count": 12}}}), encoding="utf-8")
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=writer, args=(str(self.home), 20)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
        files = list((self.home / "logs").glob("archive_update.log*"))
        self.assertGreater(len(files), 1, "the concurrent run must exercise rotation")
        records = [json.loads(line) for file in files for line in file.read_text().splitlines()]
        self.assertEqual(len(records), 40)
        self.assertEqual(len({record["run_id"] for record in records}), 2)
        self.assertFalse((self.home / "logs" / "archive_update.log.lock").exists())


if __name__ == "__main__":
    unittest.main()
