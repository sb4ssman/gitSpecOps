"""Explicit registry. Check components return records, never print or mutate."""
from Special.security._checks import _identity, _personal, _secrets
from dataclasses import replace
import hashlib

CHECKS = (_secrets.check, _personal.check, _identity.check)


def inspect(text, where, policy, object_id=""):
    findings = [finding for check in CHECKS for finding in check(text, where, policy, object_id)]
    if not findings:
        return []
    content_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return [replace(finding, content_id=content_id) for finding in findings]
