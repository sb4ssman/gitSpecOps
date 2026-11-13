"""Read and change the security policy's value lists from the local web view.

Why:          the values that must never be published (a name, an address, a username) and the
              values allowed despite looking risky belong to the person, and they should be able
              to see and change them where they look at findings, not only in a settings file.
Reads:        the common settings profile's `defaults.security` lists.
May change:   `never_publish`, `never_publish_words` and `safe_values` in that profile, through
              the shared settings writer (stale-file checks, conflict checks, atomic write).
              Nothing else.
Results:      the lists, and the lists after a change.
Layer:        Special: this machine, once.
Status:       working

Tightening (adding a never-publish value, removing an allowance) needs no extra step. Loosening
(removing a never-publish value, adding an allowance, or making a value whole-word only) needs
the typed word LOOSEN. Matching is
case-insensitive, as the scanner's is. Each audit reads the profile afresh, so a change applies
to the next audit without restarting anything.
"""
from __future__ import annotations

from Special._settings import SettingsError
from Special._settings.security import load_security_settings, save_security_settings

LISTS = ("never_publish", "never_publish_words", "safe_values")
#: Lists whose entries block: removing from them weakens protection.
BLOCKING = ("never_publish", "never_publish_words")
LOOSEN_WORD = "LOOSEN"
MAX_VALUE = 200
MAX_CHANGE = 50


def _load(home):
    try:
        return load_security_settings(home)
    except SettingsError as exc:
        raise ValueError(f"the settings profile could not be read: {exc}") from None


def _move_to_words(home, name, values, confirm) -> dict:
    """Never-publish values become whole-word values, in one save. Narrower matching weakens
    protection (a value inside another word is no longer caught), so it needs LOOSEN."""
    if name != "never_publish" or not values:
        raise ValueError("move_to_words takes values from never_publish")
    if confirm != LOOSEN_WORD:
        raise ValueError(f"whole-word matching catches less: type {LOOSEN_WORD} to allow it")
    snapshot = _load(home)
    owned = snapshot.owned_policy()
    current = {v.casefold(): v for v in owned["never_publish"]}
    if any(v.casefold() not in current for v in values):
        raise ValueError("a value to move is not in the list (it may have changed); reload")
    moving = {v.casefold() for v in values}
    words = list(owned["never_publish_words"])
    known = {v.casefold() for v in words}
    words += [current[key] for key in dict.fromkeys(v.casefold() for v in values) if key not in known]
    try:
        save_security_settings(snapshot, {"never_publish": [v for v in owned["never_publish"] if v.casefold() not in moving],
                                          "never_publish_words": words})
    except SettingsError as exc:
        raise ValueError(f"not saved: {exc}") from None
    return policy_view(home)


def policy_view(home) -> dict:
    snapshot = _load(home)
    owned = snapshot.owned_policy()
    return {"lists": {name: list(owned[name]) for name in LISTS},
            "machine_only_counts": {"never_publish": len(owned["local_never_publish"]),
                                    "safe_values": len(owned["local_safe_values"])}}


def _values(payload, key) -> list[str]:
    values = payload.get(key, [])
    if (not isinstance(values, list) or len(values) > MAX_CHANGE
            or any(not isinstance(v, str) or not v.strip() or len(v) > MAX_VALUE for v in values)):
        raise ValueError(f"{key} must be a list of up to {MAX_CHANGE} values of 1 to {MAX_VALUE} characters")
    return [v.strip() for v in values]


def policy_change(home, payload) -> dict:
    if not isinstance(payload, dict) or not set(payload) <= {"list", "add", "remove", "confirm", "move_to_words"}:
        raise ValueError("send list, and add, remove or move_to_words")
    name = payload.get("list")
    if name not in LISTS:
        raise ValueError("list must be never_publish, never_publish_words or safe_values")
    if "move_to_words" in payload:
        return _move_to_words(home, name, _values(payload, "move_to_words"), payload.get("confirm"))
    add, remove = _values(payload, "add"), _values(payload, "remove")
    if not add and not remove:
        raise ValueError("nothing to change")
    loosens = bool(remove) if name in BLOCKING else bool(add)
    if loosens and payload.get("confirm") != LOOSEN_WORD:
        raise ValueError(f"this weakens what is protected: type {LOOSEN_WORD} to allow it")
    snapshot = _load(home)
    current = snapshot.owned_policy()[name]
    dropping = {v.casefold() for v in remove}
    missing = [v for v in remove if v.casefold() not in {c.casefold() for c in current}]
    if missing:
        raise ValueError("a value to remove is not in the list (it may have changed); reload")
    kept = [v for v in current if v.casefold() not in dropping]
    known = {v.casefold() for v in kept}
    for value in add:
        if value.casefold() not in known:
            kept.append(value)
            known.add(value.casefold())
    try:
        save_security_settings(snapshot, {name: kept})
    except SettingsError as exc:
        raise ValueError(f"not saved: {exc}") from None
    return policy_view(home)
