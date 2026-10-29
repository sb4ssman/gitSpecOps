"""Fixed filter-repo adapters using the same literal transform as proof; no user code.

Loaded only by an explicitly invoked rewriter child. The private plan path comes from its
environment, not executable rule text. File-info handles additions/modifications; deletions
are transformed once in the commit callback because file-info does not receive them.
"""
from functools import lru_cache
import os

from Special._history.plan import load
from Special._history.rules import MAX_BYTES, Rules


@lru_cache(maxsize=1)
def _rules():
    return Rules.from_record(load(os.environ["GITSPECOPS_HISTORY_PLAN"]).choices)


def file_info(filename, mode, blob_id, value):
    rules = _rules()
    destination = rules.path(filename.decode("utf-8"))
    if destination is None:
        return None, mode, blob_id
    if mode not in (b"100644", b"100755", b"120000"):
        raise ValueError("unsupported file mode")
    if blob_id not in value.data:
        if value.get_size_by_identifier(blob_id) > MAX_BYTES:
            raise ValueError("blob exceeds rewrite limits")
        original = value.get_contents_by_identifier(blob_id)
        rewritten = rules.blob(original)
        value.data[blob_id] = blob_id if rewritten == original else value.insert_file_with_contents(rewritten)
    return destination.encode("utf-8"), mode, value.data[blob_id]


def message(data):
    return _rules().text(data.decode("utf-8"), "message").encode("utf-8")


def _person(record, prefix):
    name, email = getattr(record, prefix + "_name"), getattr(record, prefix + "_email")
    if name is None or email is None:
        return
    new_name, new_email = _rules().person(name.decode("utf-8"), email.decode("utf-8"))
    setattr(record, prefix + "_name", new_name.encode("utf-8"))
    setattr(record, prefix + "_email", new_email.encode("utf-8"))


def commit(record):
    _person(record, "author")
    _person(record, "committer")
    changes = []
    for change in record.file_changes:
        if change.type == b"D":
            destination = _rules().path(change.filename.decode("utf-8"))
            if destination is None:
                continue
            change.filename = destination.encode("utf-8")
        elif change.type != b"M":
            raise ValueError("unsupported history file change")
        changes.append(change)
    record.file_changes = changes


def tag(record):
    _person(record, "tagger")
