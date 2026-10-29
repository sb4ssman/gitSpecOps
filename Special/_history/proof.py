"""Pure comparison of a source history model and an observed rewritten history model.

Every selected ref, reachable commit, ordered parent, tree path/mode, blob, identity/date and
tag must match the declared Rules. Callers supply independently read objects and the rewrite
map. This does not execute a rewriter, certify Git object integrity or grant publication.
Raw models stay private; the result contains only counts and finite problem codes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from Basic._objects import Person
from Special._history.rules import Rules, git_path

OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class File:
    object_id: str = field(repr=False)
    mode: str = "100644"


@dataclass(frozen=True)
class Commit:
    tree: str = field(repr=False)
    parents: tuple = field(repr=False)
    author: Person = field(repr=False)
    committer: Person = field(repr=False)
    message: str = field(repr=False)
    signed: bool = False
    extra_headers: tuple = field(default=(), repr=False)


@dataclass(frozen=True)
class Tag:
    target: str = field(repr=False)
    name: str = field(repr=False)
    tagger: Person | None = field(default=None, repr=False)
    message: str = field(default="", repr=False)
    signed: bool = False
    extra_headers: tuple = field(default=(), repr=False)


@dataclass
class History:
    refs: dict = field(default_factory=dict, repr=False)
    commits: dict = field(default_factory=dict, repr=False)
    trees: dict = field(default_factory=dict, repr=False)
    tags: dict = field(default_factory=dict, repr=False)
    head: str = field(default="", repr=False)
    symbolic_refs: dict = field(default_factory=dict, repr=False)

    def validate(self):
        """Refuse incomplete/unsupported input models rather than infer missing history."""
        for group in (self.commits, self.trees, self.tags):
            if not isinstance(group, dict) or any(not isinstance(key, str) or not OID.fullmatch(key) for key in group):
                raise ValueError("invalid history object map")
        if not self.refs or self.head not in self.refs or not self.head.startswith("refs/heads/"):
            raise ValueError("a selected attached branch is required")
        for name, target in self.refs.items():
            if (not isinstance(name, str) or not name.startswith(("refs/heads/", "refs/tags/", "refs/remotes/")) or
                    any(char in name for char in "\0\r\n") or not isinstance(target, str) or not OID.fullmatch(target)):
                raise ValueError("unsupported selected ref")
            if name.startswith(("refs/heads/", "refs/remotes/")) and target not in self.commits:
                raise ValueError("branch does not point to a selected commit")
        if not isinstance(self.symbolic_refs, dict):
            raise ValueError("invalid symbolic refs")
        for name, target in self.symbolic_refs.items():
            if not isinstance(name, str) or not name.startswith("refs/remotes/") or name not in self.refs:
                raise ValueError("unsupported symbolic ref")
            seen = {name}
            while True:
                if target not in self.refs or target in seen or self.refs[target] != self.refs[name]:
                    raise ValueError("incomplete or cyclic symbolic ref")
                seen.add(target)
                if target not in self.symbolic_refs:
                    break
                target = self.symbolic_refs[target]
        for commit in self.commits.values():
            if (not isinstance(commit, Commit) or commit.signed or commit.extra_headers or
                    commit.tree not in self.trees or not isinstance(commit.parents, tuple) or
                    any(parent not in self.commits for parent in commit.parents) or
                    not isinstance(commit.message, str)):
                raise ValueError("unsupported or incomplete commit")
            _person_valid(commit.author)
            _person_valid(commit.committer)
        for tag in self.tags.values():
            if not isinstance(tag, Tag) or tag.signed or tag.extra_headers or not isinstance(tag.name, str) or not isinstance(tag.message, str):
                raise ValueError("unsupported tag")
            if tag.tagger is not None:
                _person_valid(tag.tagger)
        for tree in self.trees.values():
            if not isinstance(tree, dict):
                raise ValueError("invalid tree")
            for path, item in tree.items():
                git_path(path)
                if not isinstance(item, File) or item.mode not in ("100644", "100755", "120000") or not OID.fullmatch(item.object_id):
                    raise ValueError("unsupported tree entry")
        # Explicit stacks avoid a recursion limit on long histories. A cycle/incomplete ref
        # must fail before a proof, even if a caller supplied a forged model.
        reachable, active, seen_tags = set(), set(), set()
        def tag_commit(target):
            chain = set()
            while target in self.tags:
                if target in chain:
                    raise ValueError("tag cycle")
                chain.add(target)
                seen_tags.add(target)
                target = self.tags[target].target
            if target not in self.commits:
                raise ValueError("only commit-target tags are supported")
            return target
        for target in self.refs.values():
            stack = [(tag_commit(target), False)]
            while stack:
                current, finish = stack.pop()
                if finish:
                    active.remove(current)
                    reachable.add(current)
                elif current in active:
                    raise ValueError("commit cycle")
                elif current not in reachable:
                    active.add(current)
                    stack.append((current, True))
                    stack.extend((parent, False) for parent in reversed(self.commits[current].parents))
        if reachable != set(self.commits) or seen_tags != set(self.tags):
            raise ValueError("history model contains unselected objects")


def _person_valid(person):
    if (not isinstance(person, Person) or not isinstance(person.name, str) or not isinstance(person.email, str) or
            type(person.when) is not int or not isinstance(person.offset, str)):
        raise ValueError("invalid identity/date")


@dataclass
class Proof:
    status: str
    commits: int = 0
    refs: int = 0
    trees: int = 0
    files: int = 0
    problems: list = field(default_factory=list)

    def record(self):
        return {"schema_version": 1, "operation": "history-model-proof", "status": self.status,
                "commits": self.commits, "refs": self.refs, "trees": self.trees, "files": self.files,
                "problems": self.problems, "publication_clearance": False}


def compare(before, after, mapping, rules, before_blob, after_blob):
    """Compare all declared transformations, including history away from current tips.

Blob callbacks take an object id and return bytes or raise. They must read independent
source/result stores. Native workflow validation/fsck/rescan remain additional requirements.
"""
    result = Proof("failed")
    def problem(code):
        if code not in result.problems:
            result.problems.append(code)
    try:
        if not isinstance(rules, Rules):
            raise ValueError("validated rules are required")
        before.validate()
        after.validate()
        if not isinstance(mapping, dict) or set(mapping) != set(before.commits) or set(mapping.values()) != set(after.commits):
            problem("commit-map-incomplete")
            return result
        if before.head != after.head or set(before.refs) != set(after.refs):
            problem("ref-set-changed")
        if before.symbolic_refs != after.symbolic_refs:
            problem("symbolic-ref-topology-changed")
        checked_tags = {}
        def same_person(old, new):
            return (old is None and new is None) or (old is not None and new is not None and
                rules.person(old.name, old.email) == (new.name, new.email) and
                (old.when, old.offset) == (new.when, new.offset))
        def ref_matches(old, new):
            while old in before.tags:
                if new not in after.tags or (old in checked_tags and checked_tags[old] != new):
                    return False
                checked_tags[old] = new
                a, b = before.tags[old], after.tags[new]
                if a.name != b.name or not same_person(a.tagger, b.tagger) or rules.text(a.message, "message") != b.message:
                    return False
                old, new = a.target, b.target
            return mapping[old] == new
        for name in sorted(set(before.refs) & set(after.refs)):
            result.refs += 1
            if not ref_matches(before.refs[name], after.refs[name]):
                problem("ref-or-tag-mismatch")
        if set(checked_tags.values()) != set(after.tags):
            problem("tag-set-changed")
        checked_trees = set()
        for old_id, old in before.commits.items():
            new = after.commits[mapping[old_id]]
            result.commits += 1
            if tuple(mapping[parent] for parent in old.parents) != new.parents:
                problem("parent-graph-changed")
            if not same_person(old.author, new.author) or not same_person(old.committer, new.committer):
                problem("identity-or-date-mismatch")
            if rules.text(old.message, "message") != new.message:
                problem("message-mismatch")
            pair = old.tree, new.tree
            if pair in checked_trees:
                continue
            checked_trees.add(pair)
            result.trees += 1
            expected = {}
            for path, item in before.trees[old.tree].items():
                destination = rules.path(path)
                if destination is None:
                    continue
                if destination in expected:
                    problem("rewritten-path-collision")
                    return result
                expected[destination] = item
            # Check directory prefixes without comparing every possible file pair.
            if any(path[:index] in expected for path in expected
                   for index, char in enumerate(path) if char == "/"):
                problem("rewritten-path-collision")
                return result
            actual = after.trees[new.tree]
            if set(expected) != set(actual):
                problem("tree-path-set-mismatch")
            for path in set(expected) & set(actual):
                result.files += 1
                old_file, new_file = expected[path], actual[path]
                if old_file.mode != new_file.mode:
                    problem("file-mode-mismatch")
                original, rewritten = before_blob(old_file.object_id), after_blob(new_file.object_id)
                if not isinstance(original, bytes) or not isinstance(rewritten, bytes):
                    raise OSError("missing object bytes")
                if rules.blob(original) != rewritten:
                    problem("blob-content-mismatch")
        if not result.problems:
            result.status = "matched-model"
    except (OSError, KeyError):
        result.status = "incomplete"
        problem("required-object-unreadable")
    except (ValueError, TypeError, AttributeError):
        result.status = "unsupported"
        problem("invalid-or-unsupported-history-model")
    return result
