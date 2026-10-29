"""Canonical literal rewrite choices; no Git execution or IO.

One Python transform will serve both the rewrite callbacks and verification. Private JSON is
the interchange format: no comment lines, delimiter parsing, user regex or executable input.
Replacements apply once, longest first at the same position; replacement text is literal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import io
import re

MAX_BYTES = 32 * 1024 * 1024
MAX_MATCHES = 1000000
TARGETS = frozenset({"blob", "path", "message"})


def git_path(path, *, directory=False):
    """Portable literal Git path. A trailing slash explicitly selects a directory subtree."""
    if (not isinstance(path, str) or not path or len(path.encode("utf-8")) > 65536 or
            any(char in path for char in "\\\0\r\n:")):
        raise ValueError("history paths must be literal repository-relative Git paths")
    value = path[:-1] if directory and path.endswith("/") else path
    if any(part in ("", ".", "..") or part.casefold() == ".git" for part in value.split("/")):
        raise ValueError("history paths must not escape or name Git metadata")
    return value


@dataclass(frozen=True)
class Rule:
    """Literal value with explicit case/boundary matching and target channels."""
    old: str = field(repr=False)
    new: str = field(repr=False)
    ignore_case: bool = True
    bounded: bool = True
    targets: tuple = ("blob", "path", "message")

    def __post_init__(self):
        if (not isinstance(self.old, str) or not self.old or not isinstance(self.new, str) or
                "\0" in self.old or "\0" in self.new or self.old == self.new or
                type(self.ignore_case) is not bool or type(self.bounded) is not bool or
                not isinstance(self.targets, tuple) or not self.targets or
                any(not isinstance(target, str) or target not in TARGETS for target in self.targets) or
                len(set(self.targets)) != len(self.targets)):
            raise ValueError("invalid literal rewrite rule")
        if len(self.old.encode("utf-8")) > 65536 or len(self.new.encode("utf-8")) > 65536:
            raise ValueError("rewrite value exceeds its limit")

    @property
    def expression(self):
        body = re.escape(self.old)
        if self.bounded:
            body = r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])"
        return "(?i:" + body + ")" if self.ignore_case else "(?:" + body + ")"

    def record(self):
        """Private data, never a public summary."""
        return {"old": self.old, "new": self.new, "ignore_case": self.ignore_case,
                "bounded": self.bounded, "targets": list(self.targets)}


@dataclass(frozen=True)
class IdentityRule:
    """Exact old name/email pair; no ownership inference or contributor-wide rewriting."""
    old_name: str = field(repr=False)
    old_email: str = field(repr=False)
    new_name: str = field(repr=False)
    new_email: str = field(repr=False)

    def __post_init__(self):
        if any(not isinstance(value, str) or not value or len(value.encode("utf-8")) > 65536 or
               any(char in value for char in "\0\r\n<>") for value in
               (self.old_name, self.old_email, self.new_name, self.new_email)):
            raise ValueError("identity rules require exact single-line names and emails")
        if (self.old_name, self.old_email) == (self.new_name, self.new_email):
            raise ValueError("identity rule has no effect")

    def record(self):
        return {name: getattr(self, name) for name in ("old_name", "old_email", "new_name", "new_email")}


class Rules:
    """One-pass transforms; explicit removals only, with no generated-file purge defaults."""
    def __init__(self, replacements=(), remove_paths=(), identities=()):
        self.replacements, self.remove_paths, self.identities = tuple(replacements), tuple(remove_paths), tuple(identities)
        if (len(self.replacements) > 256 or len(self.remove_paths) > 10000 or len(self.identities) > 10000 or
                any(not isinstance(rule, Rule) for rule in self.replacements) or
                any(not isinstance(rule, IdentityRule) for rule in self.identities)):
            raise ValueError("invalid or oversized rewrite choices")
        for path in self.remove_paths:
            git_path(path, directory=path.endswith("/") if isinstance(path, str) else False)
        if len(set(self.remove_paths)) != len(self.remove_paths):
            raise ValueError("duplicate path removal")
        pairs = [(rule.old_name, rule.old_email) for rule in self.identities]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate old identity")
        for index, rule in enumerate(self.replacements):
            for other in self.replacements[index + 1:]:
                if (set(rule.targets) & set(other.targets) and
                        (rule.old == other.old or ((rule.ignore_case or other.ignore_case) and rule.old.casefold() == other.old.casefold()))):
                    raise ValueError("ambiguous duplicate value rules")
        self._patterns = {}
        for target in TARGETS:
            selected = sorted((rule for rule in self.replacements if target in rule.targets), key=lambda item: -len(item.old))
            pattern = re.compile("|".join(f"(?P<r{index}>{rule.expression})" for index, rule in enumerate(selected))) if selected else None
            self._patterns[target] = pattern, selected

    def __repr__(self):
        return f"Rules(replacements={len(self.replacements)}, remove_paths={len(self.remove_paths)}, identities={len(self.identities)})"

    def text(self, value, target):
        """Literal substitution, bounded output/work; no regex replacement templates."""
        if target not in TARGETS or not isinstance(value, str) or len(value.encode("utf-8")) > MAX_BYTES:
            raise ValueError("invalid or oversized rewrite input")
        pattern, selected = self._patterns[target]
        if pattern is None:
            return value
        output, end, size = io.StringIO(), 0, 0
        def emit(chunk):
            nonlocal size
            size += len(chunk.encode("utf-8"))
            if size > MAX_BYTES:
                raise ValueError("rewritten data exceeds its limit")
            output.write(chunk)
        for count, match in enumerate(pattern.finditer(value), 1):
            if count > MAX_MATCHES:
                raise ValueError("rewrite match budget exceeded")
            emit(value[end:match.start()])
            emit(selected[int(match.lastgroup[1:])].new)
            end = match.end()
        emit(value[end:])
        return output.getvalue()

    def blob(self, data):
        """Rewrite only UTF-8 text. Matching binary material requires explicit path removal."""
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise ValueError("blob exceeds rewrite limits")
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            text = None
        if text is None or "\0" in text:
            pattern, _ = self._patterns["blob"]
            if pattern is not None and pattern.search(data.decode("utf-8", errors="replace")):
                raise ValueError("matching binary content requires explicit path removal")
            return data
        return self.text(text, "blob").encode("utf-8")

    def removed(self, path):
        return any(path.startswith(rule) if rule.endswith("/") else path == rule for rule in self.remove_paths)

    def path(self, path):
        git_path(path)
        return None if self.removed(path) else git_path(self.text(path, "path"))

    def person(self, name, email):
        for rule in self.identities:
            if (name, email) == (rule.old_name, rule.old_email):
                return rule.new_name, rule.new_email
        return name, email

    def record(self):
        return {"schema_version": 1, "replacements": [rule.record() for rule in self.replacements],
                "remove_paths": list(self.remove_paths), "identities": [rule.record() for rule in self.identities]}

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or set(record) != {"schema_version", "replacements", "remove_paths", "identities"} or type(record["schema_version"]) is not int or record["schema_version"] != 1:
            raise ValueError("unsupported rewrite choices")
        if any(not isinstance(record[name], list) for name in ("replacements", "remove_paths", "identities")):
            raise ValueError("rewrite choices require lists")
        replacements, identities = [], []
        for row in record["replacements"]:
            if not isinstance(row, dict) or set(row) != {"old", "new", "ignore_case", "bounded", "targets"} or not isinstance(row["targets"], list):
                raise ValueError("invalid replacement record")
            replacements.append(Rule(row["old"], row["new"], row["ignore_case"], row["bounded"], tuple(row["targets"])))
        for row in record["identities"]:
            if not isinstance(row, dict) or set(row) != {"old_name", "old_email", "new_name", "new_email"}:
                raise ValueError("invalid identity record")
            identities.append(IdentityRule(**row))
        return cls(replacements, record["remove_paths"], identities)
