"""Offline native history readers/plans; opt-in scan/rewrite/rescan on scratch repos only.

Default: python -B -m unittest discover -s tests/special -p test_history_native.py
Native rewrite: set GITSPECOPS_RUN_HISTORY_REWRITE=1 for the same command after guard approval.
The opt-in test invokes installed git filter-repo, keeps fresh-clone checks and never forces
or publishes. Ordinary discovery does not execute that dependency. No user repo is a fixture.
"""
from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Basic._history_read import Reader, integrity
from Basic._run import CommandFailed
from Special._history import callbacks
from Special._history.native import snapshot
from Special._history.operation import command, execute
from Special._history.plan import load, prepare, save
from Special._history.rules import IdentityRule, Rule, Rules
from Special.security._material import scan
from Special.security._me import Policy


class Scratch(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="history-native-proof-")
        self.addCleanup(temp.cleanup)
        self.root, self.repo = Path(temp.name), Path(temp.name) / "original"
        self.environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_AUTHOR_DATE": "2001-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00+0000",
            "GITSPECOPS_HOME": str(self.root / "profile")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Old Owner")
        self.git("config", "user.email", "old@example.test")
        self.git("config", "core.autocrlf", "false")
        self.write("readme.txt", "private-marker\n# header-fixture\nold==>delimiter\n")
        self.write("same.txt", "unchanged\n")
        self.write("private-marker.txt", "unchanged\n")
        self.save("initial private-marker\n\n    indented\nlast line\n")
        self.first = self.git("rev-parse", "HEAD")
        self.rules = Rules([Rule("private-marker", "public-marker"),
                            Rule("# header-fixture", "retained header"),
                            Rule("old==>delimiter", r"example\literal\1")],
                           remove_paths=["retired/", "former/", "build-old/"],
                           identities=[IdentityRule("Old Owner", "old@example.test", "Public Owner",
                                                   "100+public-owner@users.noreply.github.com")])

    def git(self, *args, cwd=None, data=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *args], input=data,
                                capture_output=True, timeout=30, check=True)
        return result.stdout.decode("utf-8").strip()

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)

    def save(self, message, *, author=None):
        self.git("add", "-A")
        args = ["-c", "commit.gpgsign=false", "commit", "--allow-empty", "--cleanup=verbatim", "-qm", message]
        if author:
            args += ["--author", author]
        self.git(*args)


class NativeReadPlanTests(Scratch):
    def test_raw_bytes_messages_dates_modes_and_duplicate_paths(self):
        self.git("update-index", "--chmod=+x", "same.txt")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "mode")
        model, reader = snapshot(self.repo)
        initial = model.commits[self.first]
        self.assertEqual(initial.message, "initial private-marker\n\n    indented\nlast line\n")
        self.assertEqual(initial.author.when, 978307200)
        tree = model.trees[model.commits[model.refs[model.head]].tree]
        self.assertEqual(tree["same.txt"].object_id, tree["private-marker.txt"].object_id)
        self.assertEqual(tree["same.txt"].mode, "100755")
        self.assertEqual(reader.blob(tree["same.txt"].object_id), b"unchanged\n")
        self.assertNotIn("private-marker", repr(model) + repr(reader))
        integrity(self.repo)

    def test_private_plan_roundtrip_and_alteration_rejected(self):
        plan = prepare(self.repo, self.rules)
        path = save(plan, self.root / "plan.json")
        self.assertEqual(load(path), plan)
        self.assertNotIn("old@example.test", repr(plan))
        with self.assertRaises(FileExistsError):
            save(plan, path)
        record = json.loads(path.read_text())
        record["choices"]["remove_paths"].append("readme.txt")
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "altered"):
            load(path)

    def test_source_movement_refused_before_creating_output_or_running_dependency(self):
        plan = prepare(self.repo, self.rules)
        self.write("new.txt", "new")
        self.save("source moved")
        with patch("Special._history.operation.run", side_effect=AssertionError("must not execute")):
            with self.assertRaisesRegex(ValueError, "changed since planning"):
                execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id)
        self.assertFalse((self.root / "output").exists())

    def test_ambient_repository_redirect_is_refused_before_any_output_or_rewrite(self):
        plan = prepare(self.repo, self.rules)
        with patch.dict(os.environ, {"GIT_DIR": str(self.root / "different.git")}), \
             patch("Special._history.operation.run", side_effect=AssertionError("must not execute")):
            with self.assertRaisesRegex(ValueError, "environments"):
                execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id)
        self.assertFalse((self.root / "output").exists())

    def test_counted_directory_trust_survives_but_other_injected_settings_refuse(self):
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
                                     "GIT_CONFIG_VALUE_0": str(self.repo)}):
            self.assertIsNotNone(prepare(self.repo, self.rules))
            self.assertEqual(os.environ["GIT_CONFIG_VALUE_0"], str(self.repo))
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                                     "GIT_CONFIG_VALUE_0": str(self.root / "hooks")}):
            with self.assertRaisesRegex(ValueError, "counted"):
                prepare(self.repo, self.rules)

    def test_confirmation_and_exact_plan_are_both_required(self):
        plan = prepare(self.repo, self.rules)
        for word, plan_id in (("yes", plan.plan_id), ("REWRITE", "other-plan")):
            with self.subTest(word=word), self.assertRaises(ValueError):
                execute(plan, self.root / "output", confirmation=word, approved_plan=plan_id)
        self.assertFalse((self.root / "output").exists())

    def test_interrupted_clone_presents_owned_workspace_and_partial_mirror(self):
        plan = prepare(self.repo, self.rules)
        created = []
        def interrupted_clone(source, target, **kwargs):
            target.mkdir()
            raise KeyboardInterrupt()
        with patch("Special._history.operation.clone", side_effect=interrupted_clone), self.assertRaises(KeyboardInterrupt):
            execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id, artifacts=created)
        self.assertIn(self.root / "output", created)
        self.assertIn(self.root / "output/mirror.git", created)
        self.assertIn(self.root / "output/plan.json", created)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.first)

    def test_matching_binary_requires_explicit_removal_and_collisions_refuse(self):
        self.write("binary.dat", b"private-marker\0")
        self.save("binary")
        with self.assertRaisesRegex(ValueError, "binary"):
            prepare(self.repo, self.rules)
        rules = Rules(self.rules.replacements, [*self.rules.remove_paths, "binary.dat"], self.rules.identities)
        self.assertIsNotNone(prepare(self.repo, rules))
        self.write("public-marker.txt", "other")
        self.save("collision")
        with self.assertRaisesRegex(ValueError, "collision"):
            prepare(self.repo, rules)

    def test_unknown_headers_and_noncommit_refs_are_refused(self):
        self.git("tag", "tree-only", "HEAD^{tree}")
        with self.assertRaises(ValueError):
            snapshot(self.repo)
        self.git("tag", "-d", "tree-only")
        raw = self.git("cat-file", "commit", "HEAD").encode()
        raw = raw.replace(b"\n\n", b"\nencoding unsupported\n\n", 1)
        object_id = self.git("hash-object", "-t", "commit", "-w", "--stdin", data=raw)
        self.git("update-ref", "refs/heads/main", object_id)
        with self.assertRaisesRegex(ValueError, "header"):
            snapshot(self.repo)

    def test_shallow_promisor_and_alternate_store_are_refused(self):
        self.git("config", "remote.example.promisor", "true")
        with self.assertRaisesRegex(ValueError, "promisor"):
            snapshot(self.repo)
        self.git("config", "--unset", "remote.example.promisor")
        (self.repo / ".git/objects/info/alternates").write_text(str(self.root / "missing"))
        with self.assertRaisesRegex(ValueError, "alternate"):
            snapshot(self.repo)

    def test_raw_object_reader_refuses_corrupt_truncated_and_oversized_streams(self):
        @contextmanager
        def fake(data):
            yield SimpleNamespace(stdout=io.BytesIO(data))
        object_id = "a" * 40
        for raw in (f"{object_id} blob 4\nwrong\n".encode(),
                    f"{object_id} blob 4\nabc".encode(),
                    f"{object_id} blob 999999999\n".encode()):
            with patch("Basic._history_read.stream", return_value=fake(raw)), self.assertRaises(ValueError):
                Reader(self.repo).object(object_id)
        with self.assertRaises(ValueError):
            Reader(self.repo, object_limit=0).object(self.first)

    def test_engine_arguments_preserve_graph_and_do_not_disable_fresh_clone_checks(self):
        args = command()
        self.assertEqual(args[:2], ["git", "filter-repo"])
        self.assertNotIn("--force", args)
        self.assertNotIn("--yes", args)
        self.assertEqual(args[args.index("--prune-empty") + 1], "never")
        self.assertEqual(args[args.index("--prune-degenerate") + 1], "never")
        self.assertIn("--preserve-commit-hashes", args)

    def test_callbacks_transform_deletions_once_and_drop_removed_binary_before_reading(self):
        rules = Rules([Rule("private", "public"), Rule("public", "retained")], remove_paths=["retired/"])
        changes = [SimpleNamespace(type=b"D", filename=b"private.txt"),
                   SimpleNamespace(type=b"D", filename=b"retired/file.dat"),
                   SimpleNamespace(type=b"M", filename=b"public.txt")]
        record = SimpleNamespace(author_name=b"Contributor", author_email=b"helper@example.test",
                                 committer_name=b"Contributor", committer_email=b"helper@example.test",
                                 file_changes=changes)
        with patch.object(callbacks, "_rules", return_value=rules):
            callbacks.commit(record)
            self.assertEqual([item.filename for item in record.file_changes], [b"public.txt", b"public.txt"])
            value = SimpleNamespace(get_contents_by_identifier=lambda unused: self.fail("removed object was read"))
            self.assertEqual(callbacks.file_info(b"retired/file.dat", b"100644", b"object", value),
                             (None, b"100644", b"object"))

    def test_signed_tag_and_detached_head_are_refused(self):
        for format_name in ("PGP", "SSH"):
            raw = (f"object {self.first}\ntype commit\ntag signed\n"
                   "tagger Fixture <100+fixture@users.noreply.github.com> 978307200 +0000\n\n"
                   f"message\n-----BEGIN {format_name} SIGNATURE-----\nfixture\n").encode()
            object_id = self.git("hash-object", "-t", "tag", "-w", "--stdin", data=raw)
            self.git("update-ref", "refs/tags/signed", object_id)
            with self.assertRaisesRegex(ValueError, "signature"):
                snapshot(self.repo)
        self.git("update-ref", "-d", "refs/tags/signed")
        self.git("checkout", "--detach", "-q")
        with self.assertRaises(CommandFailed):
            snapshot(self.repo)


@unittest.skipUnless(os.environ.get("GITSPECOPS_RUN_HISTORY_REWRITE") == "1", "explicit native rewrite trial not selected")
class NativeRewriteProof(Scratch):
    def test_remote_only_history_and_symbolic_alias_preserve_names_without_fetching(self):
        self.git("checkout", "-qb", "upstream-only")
        self.write("remote.txt", "private-marker in remote-only history")
        self.save("remote-only commit")
        remote_tip = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        self.git("update-ref", "refs/remotes/origin/main", remote_tip)
        self.git("update-ref", "refs/remotes/backup/feature", self.first)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("branch", "-D", "upstream-only")
        with self.assertRaisesRegex(ValueError, "explicit inclusion"):
            prepare(self.repo, self.rules)
        before, unused = snapshot(self.repo, include_remote_refs=True)
        plan = prepare(self.repo, self.rules, include_remote_refs=True)
        outcome = execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id)
        after, unused = snapshot(outcome.mirror, include_remote_refs=True)
        self.assertEqual(set(after.refs), set(before.refs))
        self.assertEqual(after.symbolic_refs, before.symbolic_refs)
        self.assertNotEqual(after.refs["refs/heads/main"], after.refs["refs/remotes/origin/main"])
        self.assertEqual(self.git("remote", cwd=outcome.mirror), "")
        original_blob = self.git("rev-parse", "HEAD:readme.txt")
        found = subprocess.run(["git", "-C", str(outcome.mirror), "cat-file", "-e", original_blob],
                               capture_output=True, timeout=30)
        self.assertNotEqual(found.returncode, 0, "old object survived private all-ref cleanup")
        self.assertEqual(snapshot(self.repo, include_remote_refs=True)[0], before)
        self.assertFalse(scan(outcome.mirror, Policy(identities={"never-publish": ["private-marker", "old@example.test"]}),
                              material="history", engines=()).actionable)

    def test_scan_rewrite_rescan_preserves_retained_history_and_source(self):
        self.write("retired/binary.dat", b"obsolete-fixture\0")
        tiff = (b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", 1) +
                struct.pack("<HHII", 0x8825, 4, 1, 26) + struct.pack("<I", 0) +
                struct.pack("<H", 1) + struct.pack("<HHI4s", 1, 2, 2, b"N\0\0\0") + struct.pack("<I", 0))
        self.write("retired/location.tiff", tiff)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("retired-alias.txt", "obsolete-fixture private-marker")
        self.write("retired/renamed.dat", memory.getvalue())
        self.write("build-old/setup.py", "obsolete-fixture\n")
        self.save("historical material")
        (self.repo / "retired").rename(self.repo / "former")
        self.save("retired path renamed")
        self.git("checkout", "-qb", "side")
        self.write("side.txt", "retained contributor work")
        with patch.dict(os.environ, {"GIT_AUTHOR_DATE": "2001-01-01T05:30:00+0530"}):
            self.save("side", author="Contributor <200+helper@users.noreply.github.com>")
        self.git("checkout", "-q", "main")
        self.write("main.txt", "retained main work")
        self.save("main")
        self.git("merge", "--no-ff", "--no-commit", "side")
        self.save("merge private-marker")
        self.git("-c", "tag.gpgsign=false", "tag", "-a", "-m", "private-marker", "release")
        self.git("tag", "start", self.first)
        (self.repo / "private-marker.txt").unlink()
        self.save("delete renamed path; retained hash " + self.first[:12])
        # Saved untracked/unstaged data must remain untouched by the mirror operation.
        self.write("untracked.txt", "local work")
        self.write("same.txt", "unstaged local work")
        status = self.git("status", "--porcelain=v1")
        index = (self.repo / ".git/index").read_bytes()
        source, unused = snapshot(self.repo)
        self.assertEqual((len(source.commits), len(source.refs)), (7, 4))
        policy = Policy(identities={"never-publish": ["private-marker", "old@example.test", "retired-alias", "obsolete-fixture"]})
        before = scan(self.repo, policy, material="history", engines=())
        self.assertTrue(any(item.check == "image GPS position" for item in before.findings))
        self.assertTrue(any("!" in item.where for item in before.findings))
        self.assertTrue(any(item.where == "author" for item in before.findings))
        self.assertTrue(before.actionable)
        self.assertTrue(before.gaps, "the explicit binary fixture must retain its coverage warning before removal")
        plan = prepare(self.repo, self.rules)
        outcome = execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id)
        after = scan(outcome.mirror, policy, material="history", engines=())
        self.assertFalse(after.gaps, after.record())
        self.assertFalse(after.actionable, after.record())
        self.assertEqual(after.check_status, "passed")
        self.assertEqual(outcome.proof.commits, len(source.commits))
        # Purged file objects should be absent from the independent result store, not just
        # hidden by replacement refs or dropped from the current tip.
        removed_ids = {item.object_id for tree in source.trees.values() for name, item in tree.items()
                       if self.rules.removed(name)}
        self.assertTrue(removed_ids)
        for object_id in removed_ids:
            found = subprocess.run(["git", "-C", str(outcome.mirror), "cat-file", "-e", object_id],
                                   capture_output=True, timeout=30)
            self.assertNotEqual(found.returncode, 0, "purged object remains in result store")
        self.assertEqual(snapshot(self.repo)[0], source)
        self.assertEqual(self.git("status", "--porcelain=v1"), status)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual((self.repo / "same.txt").read_bytes(), b"unstaged local work")
        self.assertEqual((self.repo / "untracked.txt").read_bytes(), b"local work")
        self.assertFalse(outcome.record()["publication_clearance"])
        self.assertNotIn("private-marker", json.dumps(outcome.record()))
        self.assertTrue(all(path.is_file() for path in outcome.artifacts))

    def test_native_symlink_mode_and_one_pass_rename_with_later_deletion(self):
        # core.symlinks=false models the Windows checkout representation without requiring
        # filesystem symlink privileges. The Git object/mode itself is still a real symlink.
        self.git("config", "core.symlinks", "false")
        self.write("link", "private-marker")
        self.git("add", "link")
        blob = self.git("hash-object", "-w", "--stdin", data=b"private-marker")
        self.git("update-index", "--cacheinfo", f"120000,{blob},link")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "add link")
        (self.repo / "private-marker.txt").unlink()
        self.git("add", "-u")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "delete old name")
        rules = Rules([Rule("private-marker", "public-marker"), Rule("public-marker", "retained-marker")],
                      identities=self.rules.identities)
        plan = prepare(self.repo, rules)
        outcome = execute(plan, self.root / "output", confirmation="REWRITE", approved_plan=plan.plan_id)
        model, reader = snapshot(outcome.mirror)
        tree = model.trees[model.commits[model.refs[model.head]].tree]
        self.assertNotIn("public-marker.txt", tree)
        self.assertNotIn("retained-marker.txt", tree)
        self.assertEqual(tree["link"].mode, "120000")
        self.assertEqual(reader.blob(tree["link"].object_id), b"public-marker")


if __name__ == "__main__":
    unittest.main()
