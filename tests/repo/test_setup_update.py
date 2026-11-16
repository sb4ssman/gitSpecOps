"""Setup's express update: fast-forward only, refuse rather than guess, change no setting."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_build"))
import setup_update  # noqa: E402

IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


def run(cwd, *args):
    subprocess.run(["git", *IDENTITY, *args], cwd=cwd, check=True, capture_output=True)


def commit(cwd, name, text):
    (Path(cwd) / name).write_text(text, encoding="utf-8")
    run(cwd, "add", name)
    run(cwd, "commit", "-q", "-m", f"change {name}")


class UpdateTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.origin, self.here, self.other = temp / "origin.git", temp / "here", temp / "other"
        run(temp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        run(temp, "clone", "-q", str(self.origin), str(self.here))
        run(self.here, "switch", "-q", "-c", "main")
        commit(self.here, "a.txt", "one")
        run(self.here, "push", "-q", "-u", "origin", "main")
        run(temp, "clone", "-q", str(self.origin), str(self.other))
        stack.enter_context(patch.object(setup_update, "ROOT", self.here))
        self.refresh = stack.enter_context(patch.object(setup_update.subprocess, "call", return_value=0))
        self.output = io.StringIO()
        stack.enter_context(redirect_stdout(self.output))

    def head(self, cwd):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()

    def newer_upstream(self):
        commit(self.other, "b.txt", "two")
        run(self.other, "push", "-q", "origin", "main")

    def test_up_to_date_changes_nothing(self):
        self.assertEqual(setup_update.update(answer="u"), 0)
        self.assertIn("Up to date", self.output.getvalue())
        self.refresh.assert_not_called()

    def test_new_changes_are_shown_then_fast_forwarded_and_refreshed_by_the_new_code(self):
        self.newer_upstream()
        self.assertEqual(setup_update.update(answer="u"), 0)
        self.assertEqual(self.head(self.here), self.head(self.other))
        self.assertIn("change b.txt", self.output.getvalue())
        self.assertEqual(self.refresh.call_args.args[0][-1], "refresh")

    def test_cancel_changes_nothing(self):
        self.newer_upstream()
        before = self.head(self.here)
        self.assertEqual(setup_update.update(answer="0"), 0)
        self.assertEqual(self.head(self.here), before)

    def test_uncommitted_changes_here_stop_it(self):
        self.newer_upstream()
        (self.here / "a.txt").write_text("edited", encoding="utf-8")
        self.assertEqual(setup_update.update(answer="u"), 1)
        self.assertIn("changes of its own", self.output.getvalue())

    def test_commits_only_here_stop_it(self):
        self.newer_upstream()
        commit(self.here, "c.txt", "mine")
        self.assertEqual(setup_update.update(answer="u"), 1)
        self.assertIn("not a simple step forward", " ".join(self.output.getvalue().split()))

    def test_a_branch_with_no_upstream_stops_it(self):
        run(self.here, "switch", "-q", "-c", "local-only")
        self.assertEqual(setup_update.update(answer="u"), 1)
        self.assertIn("follows no branch", " ".join(self.output.getvalue().split()))


if __name__ == "__main__":
    unittest.main()
