"""Build private exact-history models from raw Git objects through Basic's readers.

Supports attached HEAD, local branches, commit-target tags and portable UTF-8 paths/messages.
Remote-tracking refs and their symbolic aliases require include_remote_refs=True explicitly.
Unknown headers/signatures, submodules and non-commit tags are refused, never normalized away.
Every object read is content-address verified. No writes or native rewriting occur here.
"""
from __future__ import annotations

import re

from Basic._history_read import Reader, complete, refs
from Basic._objects import Person
from Special._history.proof import Commit, File, History, Tag
from Special._history.rules import git_path


def _record(data, allowed, required, repeated=()):
    header, separator, message = data.partition(b"\n\n")
    if not separator:
        raise ValueError("incomplete raw record")
    values = {}
    for line in header.split(b"\n"):
        key, space, value = line.partition(b" ")
        if not space or key not in allowed or (key in values and key not in repeated):
            raise ValueError("unsupported or duplicate raw header")
        values.setdefault(key, []).append(value.decode("utf-8"))
    if any(key not in values for key in required):
        raise ValueError("required raw header missing")
    return values, message.decode("utf-8")


def _person(raw):
    identity, separator, date = raw.rpartition("> ")
    name, opening, email = identity.rpartition(" <")
    when, space, offset = date.partition(" ")
    if (not separator or not opening or not space or not when.lstrip("-").isdigit() or
            len(offset) != 5 or offset[0] not in "+-" or not offset[1:].isdigit()):
        raise ValueError("unsupported raw identity/date")
    return Person(name, email, int(when), offset)


def snapshot(repo, *, include_remote_refs=False):
    """Return (validated model, private reader); refuse movement during the read."""
    complete(repo)
    if type(include_remote_refs) is not bool:
        raise ValueError("remote-ref scope must be explicit")
    selected, head, symbolic = refs(repo)
    prefixes = ("refs/heads/", "refs/tags/", "refs/remotes/") if include_remote_refs else ("refs/heads/", "refs/tags/")
    if any(not name.startswith(prefixes) for name in selected):
        raise ValueError("unsupported refs; remote-tracking refs require explicit inclusion")
    model, reader = History(refs=selected, head=head, symbolic_refs=symbolic), Reader(repo)
    pending, seen = list(selected.values()), set()
    while pending:
        object_id = pending.pop()
        if object_id in seen:
            continue
        seen.add(object_id)
        kind, data = reader.object(object_id)
        if kind == "commit":
            fields, message = _record(data, {b"tree", b"parent", b"author", b"committer"},
                                      (b"tree", b"author", b"committer"), (b"parent",))
            record = Commit(fields[b"tree"][0], tuple(fields.get(b"parent", ())),
                            _person(fields[b"author"][0]), _person(fields[b"committer"][0]), message)
            model.commits[object_id] = record
            pending.extend(record.parents)
        elif kind == "tag":
            fields, message = _record(data, {b"object", b"type", b"tag", b"tagger"},
                                      (b"object", b"type", b"tag"))
            if fields[b"type"][0] not in ("tag", "commit") or re.search(
                    r"-----BEGIN (?:(?:PGP|SSH) SIGNATURE|SIGNED MESSAGE)-----", message):
                raise ValueError("unsupported tag target or signature")
            target = fields[b"object"][0]
            if reader.object(target)[0] != fields[b"type"][0]:
                raise ValueError("tag target type mismatch")
            model.tags[object_id] = Tag(target, fields[b"tag"][0],
                                       _person(fields[b"tagger"][0]) if b"tagger" in fields else None, message)
            pending.append(target)
        else:
            raise ValueError("a selected ref targets unsupported material")
    for commit in model.commits.values():
        if commit.tree in model.trees:
            continue
        flattened, stack = {}, [(commit.tree, "", 0)]
        while stack:
            tree_id, prefix, depth = stack.pop()
            if depth > 128:
                raise ValueError("history path depth exceeded")
            kind, data = reader.object(tree_id)
            if kind != "tree":
                raise ValueError("expected a tree object")
            width, cursor, names = len(bytes.fromhex(tree_id)), 0, set()
            while cursor < len(data):
                end = data.find(b"\0", cursor)
                if end < 0 or end + 1 + width > len(data):
                    raise ValueError("incomplete tree object")
                entry = data[cursor:end].split(b" ", 1)
                if len(entry) != 2:
                    raise ValueError("invalid tree entry")
                mode, name = entry[0].decode("ascii"), entry[1].decode("utf-8")
                if "/" in name or name in names:
                    raise ValueError("invalid or duplicate tree component")
                names.add(name)
                path = git_path(prefix + name)
                target = data[end + 1:end + 1 + width].hex()
                cursor = end + 1 + width
                if mode == "40000":
                    stack.append((target, path + "/", depth + 1))
                elif mode in ("100644", "100755", "120000"):
                    reader.blob(target)
                    flattened[path] = File(target, mode)
                else:
                    raise ValueError("unsupported tree mode")
        model.trees[commit.tree] = flattened
    model.validate()
    if refs(repo) != (selected, head, symbolic):
        raise ValueError("history refs moved during reading")
    return model, reader
