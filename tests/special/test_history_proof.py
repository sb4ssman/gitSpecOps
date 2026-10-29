"""Pure model proof tests. No native rewrite, Git command, source repo or dependency execution."""
from dataclasses import replace
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Basic._objects import Person
from Special._history.proof import Commit, File, History, Tag, compare
from Special._history.rules import IdentityRule, Rule, Rules


def oid(name):
    return hashlib.sha1(name.encode()).hexdigest()


class HistoryProofTests(unittest.TestCase):
    def setUp(self):
        owner = Person("Old Owner", "old@example.test", 100, "+0000")
        public = Person("Public Owner", "public@example.test", 100, "+0000")
        collaborator = Person("Contributor", "contributor@example.test", 100, "+0000")
        self.rules = Rules([Rule("private-marker", "public-marker")], remove_paths=["retired/"],
                           identities=[IdentityRule(owner.name, owner.email, public.name, public.email)])
        self.old_blobs = {oid("oldblob"): b"private-marker", oid("keep"): b"unchanged", oid("binary"): b"private-marker\0"}
        self.new_blobs = {oid("newblob"): b"public-marker", oid("keep"): b"unchanged"}
        old_tree = {"private-marker.txt": File(oid("oldblob")), "kept.txt": File(oid("keep"), "100755"),
                    "retired/archive.zip": File(oid("binary"))}
        new_tree = {"public-marker.txt": File(oid("newblob")), "kept.txt": File(oid("keep"), "100755")}
        old_a = Commit(oid("oldtree"), (), owner, owner, "private-marker")
        old_b = Commit(oid("oldtree"), (oid("old-a"),), collaborator, owner, "second")
        new_a = Commit(oid("newtree"), (), public, public, "public-marker")
        new_b = Commit(oid("newtree"), (oid("new-a"),), collaborator, public, "second")
        self.before = History({"refs/heads/main": oid("old-b"), "refs/tags/release": oid("old-tag")},
                              {oid("old-a"): old_a, oid("old-b"): old_b}, {oid("oldtree"): old_tree},
                              {oid("old-tag"): Tag(oid("old-b"), "release", owner, "private-marker")}, "refs/heads/main")
        self.after = History({"refs/heads/main": oid("new-b"), "refs/tags/release": oid("new-tag")},
                             {oid("new-a"): new_a, oid("new-b"): new_b}, {oid("newtree"): new_tree},
                             {oid("new-tag"): Tag(oid("new-b"), "release", public, "public-marker")}, "refs/heads/main")
        self.mapping = {oid("old-a"): oid("new-a"), oid("old-b"): oid("new-b")}

    def proof(self):
        return compare(self.before, self.after, self.mapping, self.rules, self.old_blobs.__getitem__, self.new_blobs.__getitem__)

    def test_expected_model_including_removed_binary_and_annotated_tag_matches(self):
        result = self.proof()
        self.assertEqual(result.status, "matched-model", result.record())
        self.assertEqual((result.commits, result.refs, result.trees, result.files), (2, 2, 1, 2))
        self.assertFalse(result.record()["publication_clearance"])

    def test_no_mutation_and_no_private_values_in_result_or_repr(self):
        before, after = deepcopy(self.before), deepcopy(self.after)
        mapping, old_blobs, new_blobs = dict(self.mapping), dict(self.old_blobs), dict(self.new_blobs)
        result = self.proof()
        self.assertEqual((self.before, self.after), (before, after))
        self.assertEqual((self.mapping, self.old_blobs, self.new_blobs), (mapping, old_blobs, new_blobs))
        self.assertNotIn("private-marker", repr(result.record()) + repr(self.before) + repr(self.after))

    def test_shared_ancestors_branches_and_ordered_merge_parents(self):
        old_branch, new_branch = oid("old-side"), oid("new-side")
        old_merge, new_merge = oid("old-merge"), oid("new-merge")
        self.before.commits[old_branch] = replace(self.before.commits[oid("old-b")], message="side")
        self.after.commits[new_branch] = replace(self.after.commits[oid("new-b")], message="side")
        self.before.commits[old_merge] = replace(self.before.commits[oid("old-b")], parents=(oid("old-b"), old_branch), message="merge")
        self.after.commits[new_merge] = replace(self.after.commits[oid("new-b")], parents=(oid("new-b"), new_branch), message="merge")
        self.before.refs.update({"refs/heads/main": old_merge, "refs/heads/side": old_branch})
        self.after.refs.update({"refs/heads/main": new_merge, "refs/heads/side": new_branch})
        self.mapping.update({old_branch: new_branch, old_merge: new_merge})
        self.assertEqual(self.proof().status, "matched-model")
        self.after.commits[new_merge] = replace(self.after.commits[new_merge], parents=(new_branch, oid("new-b")))
        self.assertIn("parent-graph-changed", self.proof().problems)

    def test_lightweight_and_nested_annotated_tags(self):
        self.before.refs["refs/tags/light"] = oid("old-a")
        self.after.refs["refs/tags/light"] = oid("new-a")
        self.before.tags[oid("old-outer")] = Tag(oid("old-tag"), "outer", message="private-marker")
        self.after.tags[oid("new-outer")] = Tag(oid("new-tag"), "outer", message="public-marker")
        self.before.refs["refs/tags/outer"] = oid("old-outer")
        self.after.refs["refs/tags/outer"] = oid("new-outer")
        self.assertEqual(self.proof().status, "matched-model")
        self.after.refs["refs/tags/light"] = oid("new-b")
        self.assertIn("ref-or-tag-mismatch", self.proof().problems)

    def test_symbolic_target_identity_is_checked_even_when_both_tips_match(self):
        for name in ("refs/remotes/origin/main", "refs/remotes/backup/main", "refs/remotes/origin/HEAD"):
            self.before.refs[name] = oid("old-a")
            self.after.refs[name] = oid("new-a")
        self.before.symbolic_refs["refs/remotes/origin/HEAD"] = "refs/remotes/origin/main"
        self.after.symbolic_refs["refs/remotes/origin/HEAD"] = "refs/remotes/origin/main"
        self.assertEqual(self.proof().status, "matched-model")
        self.after.symbolic_refs["refs/remotes/origin/HEAD"] = "refs/remotes/backup/main"
        self.assertIn("symbolic-ref-topology-changed", self.proof().problems)

    def test_symlink_object_bytes_are_compared_without_following_a_target(self):
        self.before.trees[oid("oldtree")]["link"] = File(oid("oldblob"), "120000")
        self.after.trees[oid("newtree")]["link"] = File(oid("newblob"), "120000")
        self.assertEqual(self.proof().status, "matched-model")
        self.after.trees[oid("newtree")]["link"] = File(oid("keep"), "120000")
        self.assertIn("blob-content-mismatch", self.proof().problems)

    def test_unselected_commit_objects_are_not_implicitly_certified(self):
        self.after.commits[oid("unselected")] = self.after.commits[oid("new-a")]
        self.mapping[oid("old-a")] = oid("unselected")
        self.assertEqual(self.proof().status, "unsupported")

    def test_file_directory_collision_is_refused(self):
        self.before.trees[oid("oldtree")]["public-marker.txt/child"] = File(oid("keep"))
        self.before.trees[oid("oldtree")]["public-marker.txt-other"] = File(oid("keep"))
        self.assertIn("rewritten-path-collision", self.proof().problems)

    def test_deep_history_does_not_depend_on_python_recursion_limit(self):
        old_parent, new_parent = oid("old-b"), oid("new-b")
        for index in range(1500):
            old_id, new_id = oid(f"old-depth-{index}"), oid(f"new-depth-{index}")
            self.before.commits[old_id] = replace(self.before.commits[oid("old-b")], parents=(old_parent,), message=str(index))
            self.after.commits[new_id] = replace(self.after.commits[oid("new-b")], parents=(new_parent,), message=str(index))
            self.mapping[old_id] = new_id
            old_parent, new_parent = old_id, new_id
        self.before.refs["refs/heads/main"] = old_parent
        self.after.refs["refs/heads/main"] = new_parent
        self.assertEqual(self.proof().status, "matched-model")

    def test_mismatched_old_version_fails_even_when_current_tree_can_match(self):
        self.after.commits[oid("new-a")] = replace(self.after.commits[oid("new-a")], tree=oid("bad-tree"))
        self.after.trees[oid("bad-tree")] = dict(self.after.trees[oid("newtree")])
        self.after.trees[oid("bad-tree")]["public-marker.txt"] = File(oid("badblob"))
        self.new_blobs[oid("badblob")] = b"unexpected edit in old history"
        self.assertIn("blob-content-mismatch", self.proof().problems)

    def test_extra_or_missing_refs_and_incomplete_map_fail(self):
        self.after.refs["refs/heads/extra"] = oid("new-b")
        self.assertIn("ref-set-changed", self.proof().problems)
        del self.mapping[oid("old-a")]
        self.assertIn("commit-map-incomplete", self.proof().problems)

    def test_dates_and_other_contributors_are_preserved(self):
        record = self.after.commits[oid("new-b")]
        self.after.commits[oid("new-b")] = replace(record, author=replace(record.author, email="other@example.test"))
        self.assertIn("identity-or-date-mismatch", self.proof().problems)
        self.after.commits[oid("new-b")] = replace(record, author=replace(record.author, when=101))
        self.assertIn("identity-or-date-mismatch", self.proof().problems)

    def test_parent_graph_and_messages_are_checked(self):
        record = self.after.commits[oid("new-b")]
        self.after.commits[oid("new-b")] = replace(record, message="unapproved")
        self.assertIn("message-mismatch", self.proof().problems)
        self.after.commits[oid("new-b")] = replace(record, parents=())
        self.assertNotEqual(self.proof().status, "matched-model")

    def test_file_modes_and_unapproved_path_changes_fail(self):
        tree = self.after.trees[oid("newtree")]
        tree["kept.txt"] = replace(tree["kept.txt"], mode="100644")
        self.assertIn("file-mode-mismatch", self.proof().problems)
        tree["extra.txt"] = File(oid("keep"))
        self.assertIn("tree-path-set-mismatch", self.proof().problems)

    def test_path_collisions_are_not_overwritten(self):
        self.before.trees[oid("oldtree")]["public-marker.txt"] = File(oid("keep"))
        self.assertIn("rewritten-path-collision", self.proof().problems)

    def test_tag_metadata_and_target_are_checked(self):
        old = self.after.tags[oid("new-tag")]
        self.after.tags[oid("new-tag")] = replace(old, message="unapproved")
        self.assertIn("ref-or-tag-mismatch", self.proof().problems)

    def test_missing_bytes_are_incomplete_not_a_clean_result(self):
        self.new_blobs.clear()
        self.assertEqual(self.proof().status, "incomplete")

    def test_signed_unknown_header_gitlink_and_cycles_are_unsupported(self):
        record = self.after.commits[oid("new-b")]
        for changed in (replace(record, signed=True), replace(record, extra_headers=(("encoding", "unknown"),)),
                        replace(record, parents=(oid("new-b"),))):
            self.after.commits[oid("new-b")] = changed
            self.assertEqual(self.proof().status, "unsupported")
        self.after.commits[oid("new-b")] = record
        self.after.trees[oid("newtree")]["kept.txt"] = File(oid("keep"), "160000")
        self.assertEqual(self.proof().status, "unsupported")


if __name__ == "__main__":
    unittest.main()
