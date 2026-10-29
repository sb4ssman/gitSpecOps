"""Private versioned exact-source plans. Preparation reads; saving is explicit/exclusive.

The random public plan id does not hash a sensitive value. The private content digest detects
accidental alteration; it is not a signature against a hostile owner of the profile/storage.
No rewrite choice is inferred from scanner output, and no history operation runs here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from Basic._history_read import refs
from Special._history.native import snapshot
from Special._history.rules import Rules
from Special.security._private_files import read_private_json, write_private_json


def _digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True,
                                      separators=(",", ":")).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Plan:
    plan_id: str
    source: str = field(repr=False)
    refs: dict = field(repr=False)
    head: str = field(repr=False)
    choices: dict = field(repr=False)
    symbolic_refs: dict = field(repr=False)
    include_remote_refs: bool
    context: dict = field(repr=False)
    content_digest: str = field(repr=False)

    def record(self):
        return {"schema_version": 2, "plan_id": self.plan_id, "source": self.source,
                "refs": self.refs, "head": self.head, "choices": self.choices,
                "symbolic_refs": self.symbolic_refs, "include_remote_refs": self.include_remote_refs,
                "context": self.context,
                "content_digest": self.content_digest}

    def validate(self):
        record = self.record()
        record.pop("content_digest")
        if (not isinstance(self.plan_id, str) or not self.plan_id.startswith("history-") or
                len(self.plan_id) != 40 or not isinstance(self.source, str) or
                str(Path(self.source).resolve()) != self.source or type(self.include_remote_refs) is not bool or
                not isinstance(self.context, dict) or not isinstance(self.symbolic_refs, dict) or
                self.content_digest != _digest(record)):
            raise ValueError("invalid or altered history plan")
        Rules.from_record(self.choices)

    def current(self):
        self.validate()
        if refs(self.source) != (self.refs, self.head, self.symbolic_refs):
            raise ValueError("source refs changed since planning")


def prepare(source, rules, *, include_remote_refs=False, context=None):
    """Validate all retained transformations and bind the exact complete source ref state."""
    if not isinstance(rules, Rules):
        raise ValueError("validated history rules are required")
    source = str(Path(source).resolve())
    model, reader = snapshot(source, include_remote_refs=include_remote_refs)
    for tree in model.trees.values():
        paths = set()
        for name, item in tree.items():
            path = rules.path(name)
            if path is None:
                continue
            if path in paths:
                raise ValueError("rewritten path collision")
            paths.add(path)
            rules.blob(reader.blob(item.object_id))
        if any(path[:index] in paths for path in paths for index, char in enumerate(path) if char == "/"):
            raise ValueError("rewritten file/directory collision")
    for commit in model.commits.values():
        rules.text(commit.message, "message")
        for person in (commit.author, commit.committer):
            rules.person(person.name, person.email)
    for tag in model.tags.values():
        rules.text(tag.message, "message")
    record = {"schema_version": 2, "plan_id": "history-" + uuid4().hex, "source": source,
              "refs": model.refs, "head": model.head, "choices": rules.record(),
              "symbolic_refs": model.symbolic_refs, "include_remote_refs": include_remote_refs,
              "context": {} if context is None else context}
    return Plan(**{key: value for key, value in record.items() if key != "schema_version"}, content_digest=_digest(record))


def save(plan, destination):
    plan.validate()
    return write_private_json(destination, plan.record())


def load(source):
    record = read_private_json(source)
    keys = {"schema_version", "plan_id", "source", "refs", "head", "choices", "content_digest",
            "symbolic_refs", "include_remote_refs", "context"}
    if not isinstance(record, dict) or set(record) != keys or type(record["schema_version"]) is not int or record["schema_version"] != 2:
        raise ValueError("unsupported history plan")
    plan = Plan(**{key: record[key] for key in keys - {"schema_version"}})
    plan.validate()
    return plan
