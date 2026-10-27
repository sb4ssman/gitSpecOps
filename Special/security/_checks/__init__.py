"""Explicit registry. Check components return records, never print or mutate."""
from Special.security._checks import _identity, _personal, _secrets

CHECKS = (_secrets.check, _personal.check, _identity.check)


def inspect(text, where, policy, object_id=""):
    return [finding for check in CHECKS for finding in check(text, where, policy, object_id)]
