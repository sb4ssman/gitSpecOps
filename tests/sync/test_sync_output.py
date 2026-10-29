"""Callable check-command output contracts; no Git, network or persistent state."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

import sync_suggester as cli  # noqa: E402
from observer import Observation  # noqa: E402


class CheckOutputTests(unittest.TestCase):
    def invoke(self, *options, enrolled=False):
        transport = Mock() if enrolled else None
        if transport is not None:
            transport.write_own_manifest.return_value = "chosen-state/machine-a.json"
        resolved = cli.Resolution(
            config_dir=Path("unused-config"),
            config={"fleet_secret": "ab" * 32} if enrolled else None,
            specs=[], source="test roots", machine_id="machine-a",
            machine_label="workstation-a", state_dir=None, transport=transport)
        args = cli.build_parser().parse_args(["check", "--local-only", *options])
        observation = Observation([], {}, ["one checkout could not be inspected"])

        def observe(*unused, **kwargs):
            kwargs["progress"](1, 1, Path("invented-repo"))
            return observation

        stdout, stderr = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli, "_resolve", return_value=resolved))
            observer = stack.enter_context(patch.object(cli, "observe_roots", side_effect=observe))
            stack.enter_context(patch.object(cli, "load_catalog", return_value={}))
            stack.enter_context(patch.object(cli, "load_branches", return_value={}))
            save = stack.enter_context(patch.object(cli, "save_catalog"))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            code = args.handler(args)
        self.assertEqual(code, 0)
        self.assertIn("warning: one checkout could not be inspected", stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue(), observer, save, transport

    def test_local_json_is_one_parseable_manifest(self):
        stdout, stderr, observer, save, transport = self.invoke("--json")
        result = json.loads(stdout)
        manifest = result["manifest"]
        self.assertEqual(result["local_security"], [])
        self.assertEqual(manifest["machine_id"], "machine-a")
        self.assertEqual(manifest["repositories"], [])
        self.assertIn("Observed 0 repositor(ies)", stderr)
        self.assertNotIn("Fetching remote refs", stderr)
        self.assertFalse(observer.call_args.kwargs["fetch"])
        save.assert_not_called()
        self.assertIsNone(transport)

    def test_json_stays_parseable_when_fetching_and_publishing(self):
        stdout, stderr, observer, save, transport = self.invoke("--json", "--fetch", enrolled=True)
        result = json.loads(stdout)
        manifest = result["manifest"]
        self.assertNotIn("local_security", manifest)
        self.assertIn("Fetching remote refs", stderr)
        self.assertIn("1/1 observed", stderr)
        self.assertIn("Manifest written: chosen-state/machine-a.json", stderr)
        self.assertTrue(observer.call_args.kwargs["fetch"])
        save.assert_called_once()
        transport.write_own_manifest.assert_called_once_with("machine-a", manifest, compress=False)

    def test_human_status_remains_on_stdout(self):
        stdout, stderr, observer, save, transport = self.invoke("--fetch", enrolled=True)
        self.assertIn("Fetching remote refs", stdout)
        self.assertIn("Observed 0 repositor(ies)", stdout)
        self.assertIn("Manifest written: chosen-state/machine-a.json", stdout)
        self.assertIn("1/1 observed", stderr)
        save.assert_called_once()
        transport.write_own_manifest.assert_called_once()


if __name__ == "__main__":
    unittest.main()
