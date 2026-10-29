"""Pure history-rule regressions. No Git execution or history-tool calls.

Pins rule-file bugs, literal replacements, contributor scope, exact removals and bounds;
native disposable rewrite execution remains a separately guarded integration proof.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special._history import rules as subject
from Special._history.rules import IdentityRule, Rule, Rules


class HistoryRulesTests(unittest.TestCase):
    def test_private_json_is_data_not_a_line_or_comment_format(self):
        rules = Rules([Rule("# not a header", "kept literal"), Rule("old==>value", r"C:\Users\<you>")])
        restored = Rules.from_record(json.loads(json.dumps(rules.record())))
        self.assertEqual(restored.text("# not a header; old==>value", "blob"), r"kept literal; C:\Users\<you>")

    def test_backslashes_and_replacement_tokens_are_literal(self):
        replacement = r"C:\Users\<you>\1\g<name>"
        self.assertEqual(Rules([Rule("private-marker", replacement)]).blob(b"private-marker"), replacement.encode())

    def test_value_metacharacters_are_not_regex(self):
        self.assertEqual(Rules([Rule("a.[x]", "example")]).text("a.[x] axxx", "blob"), "example axxx")

    def test_matching_is_bounded_and_case_configured(self):
        rules = Rules([Rule("private", "public")])
        self.assertEqual(rules.text("PRIVATE privatex xprivate private_name", "blob"), "public privatex xprivate public_name")
        self.assertEqual(Rules([Rule("PRIVATE", "public", ignore_case=False)]).text("PRIVATE private", "blob"), "public private")

    def test_unicode_values_use_same_python_semantics(self):
        self.assertEqual(Rules([Rule("privaté", "example")]).blob("PRIVATÉ".encode()), b"example")

    def test_one_pass_and_longest_at_same_position(self):
        rules = Rules([Rule("private", "public"), Rule("private-name", "private"), Rule("public", "retained")])
        self.assertEqual(rules.text("private-name private public", "blob"), "private public retained")

    def test_targets_are_explicit(self):
        rules = Rules([Rule("private", "public", targets=("message",))])
        self.assertEqual(rules.blob(b"private"), b"private")
        self.assertEqual(rules.path("private.txt"), "private.txt")
        self.assertEqual(rules.text("private", "message"), "public")

    def test_file_and_directory_removals_do_not_expand_globs(self):
        rules = Rules(remove_paths=["retired/", "old.txt", "star*.txt"])
        for path in ("retired/deep/a.txt", "old.txt", "star*.txt"):
            self.assertIsNone(rules.path(path))
        for path in ("star-other.txt", "retired", "old.txt/kept"):
            self.assertEqual(rules.path(path), path)

    def test_remove_before_rename(self):
        self.assertIsNone(Rules([Rule("retired", "current")], remove_paths=["retired/"]).path("retired/file.txt"))

    def test_unsafe_paths_are_refused(self):
        for name in ("", "/absolute", "../escape", "a//b", ".git/config", "a/.GiT/config", "a\\b", "drive:path"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Rules(remove_paths=[name])
        with self.assertRaises(ValueError):
            Rules([Rule("private", "../escape")]).path("private")

    def test_binary_is_preserved_or_refused_never_text_edited(self):
        rules = Rules([Rule("private", "public")])
        self.assertEqual(rules.blob(b"other\0data"), b"other\0data")
        for data in (b"private\0data", b"private\xff"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                rules.blob(data)

    def test_exact_identity_mapping_preserves_other_contributors(self):
        rules = Rules(identities=[IdentityRule("Old Name", "old@example.test", "Public Name", "public@example.test")])
        self.assertEqual(rules.person("Old Name", "old@example.test"), ("Public Name", "public@example.test"))
        self.assertEqual(rules.person("Other", "old@example.test"), ("Other", "old@example.test"))
        self.assertEqual(rules.person("Old Name", "other@example.test"), ("Old Name", "other@example.test"))

    def test_repr_never_discloses_values(self):
        rule = Rule("private-marker", "private-result")
        identity = IdentityRule("private-name", "private@example.test", "public-name", "public@example.test")
        self.assertNotIn("private", repr(rule) + repr(identity) + repr(Rules([rule], identities=[identity])))

    def test_ambiguous_duplicate_rules_are_refused(self):
        with self.assertRaises(ValueError):
            Rules([Rule("private", "one"), Rule("PRIVATE", "two")])
        identity = IdentityRule("Old", "old@example.test", "New", "new@example.test")
        with self.assertRaises(ValueError):
            Rules(identities=[identity, identity])

    def test_invalid_schema_and_choices_are_refused(self):
        record = Rules([Rule("private", "public")]).record()
        for bad in ({**record, "schema_version": True}, {**record, "unexpected": True}):
            with self.assertRaises(ValueError):
                Rules.from_record(bad)
        for args in (("", "public"), ("same", "same"), ("private", "public", "yes")):
            with self.assertRaises(ValueError):
                Rule(*args)

    def test_output_and_match_budgets(self):
        rules = Rules([Rule("x", "expanded", bounded=False)])
        with patch.object(subject, "MAX_BYTES", 10), self.assertRaises(ValueError):
            rules.text("xx", "blob")
        with patch.object(subject, "MAX_MATCHES", 2), self.assertRaises(ValueError):
            rules.text("xxx", "blob")


if __name__ == "__main__":
    unittest.main()
