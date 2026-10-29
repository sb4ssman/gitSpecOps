"""Optional-engine protocols and privacy on synthetic selected text; no installed scanners.

    python tests/security/test_engines.py

Mocks replace only the external process boundary. Policy resolution, batching, report
serialization and CLI presentation run normally; no live settings, Git actions or network.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Basic._run import CommandFailed, CommandTimeout
from Special._settings import SettingsError, resolve_document, validate_document
from Special.security import _cli, _engines
from Special.security._findings import Finding, Report
from Special.security._me import Policy, load_policy


class Engines(unittest.TestCase):
    def setUp(self):
        self.report = Report("/path/to/repo", "tree")
        self.policy = Policy()

    def batch(self, engines=("gitleaks",)):
        return _engines.EngineBatch(self.report, self.policy, engines,
                                   executables={name: sys.executable for name in engines})

    def test_none_never_discovers_or_starts_a_process(self):
        with patch.object(_engines.shutil, "which", side_effect=AssertionError("unexpected discovery")), \
             patch.object(_engines, "_execute", side_effect=AssertionError("unexpected process")):
            batch = self.batch(())
            batch.add("selected ordinary text", "readme.txt")
            batch.finish()
        self.assertEqual(self.report.engines, {})
        self.assertEqual(self.report.record()["external_secret_scanner"], "not-run")

    def test_selection_rejects_unknown_duplicate_and_scalar_without_echoing_values(self):
        for value in (("gitleaks", "gitleaks"), ("private-fixture",), "gitleaks", (None,), None, {"gitleaks": True}):
            with self.subTest(value=value), self.assertRaises(SettingsError) as raised:
                _engines.selected_engines(value)
            self.assertNotIn("private-fixture", str(raised.exception))

    def test_each_documented_engine_protocol_normalizes_findings(self):
        samples = {"gitleaks": b'[{"Secret":"synthetic-marker","RuleID":"sample-rule"}]',
                   "betterleaks": b'[{"Secret":"synthetic-marker","RuleID":"sample-rule"}]',
                   "trufflehog": b'{"Raw":"synthetic-marker","DetectorName":"Sample"}\n'}
        for engine, payload in samples.items():
            with self.subTest(engine=engine):
                self.assertEqual(_engines._records(engine, payload)[0][0], "synthetic-marker")

    def test_unknown_output_does_not_become_clean(self):
        for payload in (b"not JSON", b"{}", b'[{}]', b'[true]', b'[{"Secret":"x","RuleID":"bad\\nrule"}]'):
            with self.subTest(payload=payload), self.assertRaises((ValueError, UnicodeError)):
                _engines._records("gitleaks", payload)

    def test_empty_engine_results_are_supported(self):
        self.assertEqual(_engines._records("gitleaks", b"null"), [])
        self.assertEqual(_engines._records("betterleaks", b"[]"), [])
        self.assertEqual(_engines._records("trufflehog", b""), [])

    def test_combined_engines_map_selected_fragments_and_deduplicate(self):
        batch = self.batch(("gitleaks", "betterleaks", "trufflehog"))
        batch.add("ordinary\nsynthetic-marker", "a.txt", "object-a")
        batch.add("synthetic-marker", "b.txt", "object-b")
        with patch.object(_engines, "_execute", return_value=[("synthetic-marker", "sample-rule")] * 2):
            batch.finish()
        self.assertEqual(len(self.report.findings), 6)
        self.assertEqual({hit.line for hit in self.report.findings}, {1, 2})
        self.assertEqual({hit.object_id for hit in self.report.findings}, {"object-a", "object-b"})
        self.assertEqual(self.report.record()["external_secret_scanner"], "checked-selected-engines")
        self.assertNotIn("synthetic-marker", json.dumps(self.report.record()))
        self.assertFalse(batch.seen)

    def test_safe_value_applies_to_external_results_too(self):
        self.policy.safe = ["synthetic-marker"]
        batch = self.batch()
        batch.add("synthetic-marker", "a.txt")
        with patch.object(_engines, "_execute", return_value=[("synthetic-marker", "sample-rule")]):
            batch.finish()
        self.assertFalse(self.report.findings)
        self.assertFalse(self.report.gaps)

    def test_selected_missing_engine_is_an_explicit_gap(self):
        batch = _engines.EngineBatch(self.report, self.policy, ("gitleaks",))
        batch.add("ordinary", "a.txt")
        with patch.object(_engines.shutil, "which", return_value=None), \
             patch.object(_engines, "_execute", side_effect=AssertionError("unexpected process")):
            batch.finish()
        self.assertEqual(self.report.exit_code, 2)
        self.assertEqual(self.report.engines, {"gitleaks": "incomplete"})

    def test_failure_timeout_and_raw_process_errors_do_not_leak(self):
        for error in (CommandFailed("synthetic-private stderr"), CommandTimeout("synthetic-private"),
                      ValueError("synthetic-private output")):
            with self.subTest(error=type(error).__name__):
                self.report = Report("/path/to/repo", "tree")
                batch = self.batch()
                batch.add("ordinary", "a.txt")
                with patch.object(_engines, "_execute", side_effect=error) as execute:
                    batch.flush()
                    batch.add("more", "b.txt")
                    batch.finish()
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(self.report.exit_code, 2)
                self.assertNotIn("synthetic-private", json.dumps(self.report.record()))

    def test_unmapped_transformed_result_is_incomplete_not_discarded(self):
        batch = self.batch()
        batch.add("ordinary", "a.txt")
        with patch.object(_engines, "_execute", return_value=[("unmapped-marker", "sample-rule")]):
            batch.finish()
        self.assertEqual(self.report.exit_code, 2)
        self.assertFalse(self.report.findings)

    def test_batch_bound_preserves_all_admitted_fragments(self):
        batch = self.batch()
        with patch.object(_engines, "BATCH_FRAGMENTS", 2), \
             patch.object(_engines, "_execute", return_value=[]) as execute:
            for number in range(5):
                batch.add(f"content-{number}", f"file-{number}")
            batch.finish()
        self.assertEqual(execute.call_count, 3)
        feed = b"".join(call.args[2] for call in execute.call_args_list)
        for number in range(5):
            self.assertIn(f"content-{number}".encode(), feed)

    def test_process_uses_stdin_empty_cwd_and_explicit_no_validation(self):
        seen = {}

        @contextmanager
        def process(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
            yield type("Process", (), {"stdout": io.BytesIO(b"[]")})()

        with patch.object(_engines, "stream", process):
            self.assertEqual(_engines._execute("betterleaks", sys.executable, b"selected secret text"), [])
        self.assertNotIn("selected secret text", " ".join(seen["argv"]))
        self.assertEqual(seen["feed"], (b"selected secret text",))
        self.assertIn("--validation=false", seen["argv"])
        self.assertEqual(seen["env"]["BETTERLEAKS_ANALYZE"], "false")
        self.assertFalse(Path(seen["cwd"]).exists())
        self.assertIn("--no-verification", _engines.command("trufflehog", "trufflehog"))
        self.assertIn("--no-update", _engines.command("trufflehog", "trufflehog"))

    def test_excess_engine_output_is_stopped_and_rejected(self):
        stopped = []

        @contextmanager
        def process(*args, **kwargs):
            yield type("Process", (), {"stdout": io.BytesIO(b"[] "),
                                       "stop": lambda self: stopped.append(True)})()

        with patch.object(_engines, "MAX_OUTPUT_BYTES", 2), patch.object(_engines, "stream", process):
            with self.assertRaises(ValueError):
                _engines._execute("gitleaks", sys.executable, b"text")
        self.assertEqual(stopped, [True])

    def test_empty_material_still_checks_selected_engine(self):
        with patch.object(_engines, "_execute", return_value=[]) as execute:
            self.batch().finish()
        execute.assert_called_once()
        self.assertEqual(self.report.engines["gitleaks"], "checked")


class PolicyAndPresentation(unittest.TestCase):
    def test_master_and_machine_blocks_accumulate_without_allow_override(self):
        doc = {"schema_version": 2, "defaults": {"security": {"never_publish": ["master-marker"],
               "local_never_publish": ["machine-marker"], "engines": ["gitleaks", "trufflehog"]}}}
        with tempfile.TemporaryDirectory() as home:
            resolved = resolve_document(doc, "security", home=home)
            with patch("Special.security._me.run", return_value=type("R", (), {"returncode": 1, "stdout": ""})()):
                policy = load_policy(Path(home), settings=resolved)
            self.assertEqual(policy.engines, ("gitleaks", "trufflehog"))
            self.assertEqual(policy.identities["never-publish"], ["master-marker", "machine-marker"])
            self.assertNotIn("master-marker", json.dumps(resolved.summary()))
            with self.assertRaises(SettingsError):
                resolve_document(doc, "security", home=home,
                                 overrides={"security": {"local_safe_values": ["MASTER-MARKER"]}})
            self.assertFalse(list(Path(home).iterdir()))

    def test_invalid_saved_engine_names_are_sanitized_errors(self):
        for values in (["private-marker"], ["gitleaks", "gitleaks"], [False]):
            with self.subTest(values=values), self.assertRaises(SettingsError) as raised:
                validate_document({"schema_version": 2, "defaults": {"security": {"engines": values}}})
            self.assertNotIn("private-marker", str(raised.exception))

    def test_actionable_records_hide_values_and_do_not_hash_them(self):
        report = Report("/path/to/repo", "tree", findings=[
            Finding("never-publish", "leak", "synthetic-marker", "synthetic-marker.txt", "object-a", 4)])
        record = report.record()
        finding = record["findings"][0]
        self.assertEqual(finding["finding_id"], "finding-000001")
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(finding["line"], 4)
        self.assertTrue(finding["recommendation"])
        self.assertNotIn("synthetic-marker", json.dumps(record))
        self.assertNotIn("synthetic-marker", repr(report.findings[0]))
        self.assertIn("synthetic-marker", json.dumps(report.record(redacted=False)))

    def test_artifact_presentation_and_explicit_engine_override(self):
        report = Report("/path/to/repo", "tree", private_values=("private-marker",))
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home, \
             patch.object(_cli, "load_policy", return_value=Policy(engines=("gitleaks",))), \
             patch.object(_cli, "scan", return_value=report) as scanner, \
             patch.object(_cli, "write_report") as writer, redirect_stdout(output):
            code = _cli.main("tree", [home, "--engine", "none", "--json", "--out", str(Path(home) / "private-marker.json")])
        self.assertEqual(code, 0)
        self.assertEqual(scanner.call_args.kwargs["engines"], [])
        writer.assert_called_once()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["artifacts"]), 1)
        self.assertEqual(result["artifacts"][0]["disclosure"], "full private values")
        self.assertNotIn("private-marker", output.getvalue())
        self.assertIn("Produced security report", report.summary())


if __name__ == "__main__":
    unittest.main()
