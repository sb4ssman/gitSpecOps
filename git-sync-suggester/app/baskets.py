"""Baskets: which repositories this machine participates in, per scope.

Until now `roots` was the only selector, so a machine either took part in everything under its
library or nothing at all. That is wrong for the actual use: a laptop may want to *watch* every
namespace it has checked out, but only *publish* work namespaces to a shared state repo.

Three scopes, deliberately separate, because they leak different amounts:

    observe   this machine inspects the repository at all (local only)
    publish   its status is written into manifests other machines read
    capture   its uncommitted content is snapshotted (NOT IMPLEMENTED)

They are separate keys and never imply one another. Widening `observe` must never widen
`publish`, and nothing may ever widen `capture` implicitly -- see `validate_scopes`.

The selector unit is a **namespace** (`host/owner`), which is what the dashboard already groups
by and what "which orgs does this machine sync" actually means. Matching happens locally, from
the catalog, because a manifest carries salted digests and no names: a peer therefore cannot
apply, infer, or even see another machine's baskets. That is a feature, not a limitation.

Narrowing is never silent. Callers get the excluded count back and must surface it; a repository
this machine chose not to publish is invisible to every peer, and an invisible repository must
never read as an all-clear.
"""
from __future__ import annotations

MODES = ("all", "none", "only", "except")
SCOPES = ("observe", "publish", "capture")

ALL = {"mode": "all"}
NONE = {"mode": "none"}

# Capture never defaults on, and there is no capture implementation to turn on yet.
DEFAULT_SCOPES = {"observe": dict(ALL), "publish": dict(ALL), "capture": dict(NONE)}


def namespace_of(identity: dict) -> str:
    """`host/owner` from a catalog entry. Lowercased: Git hosts are case-insensitive here."""
    return f"{identity.get('host', '')}/{identity.get('owner', '')}".lower()


def validate_selection(selection, scope: str = "") -> dict:
    where = f"{scope} " if scope else ""
    if not isinstance(selection, dict) or selection.get("mode") not in MODES:
        raise ValueError(f"{where}basket needs a mode of {', '.join(MODES)}")
    listed = selection.get("namespaces")
    if selection["mode"] in ("only", "except"):
        if not isinstance(listed, list) or not listed:
            raise ValueError(f"{where}basket '{selection['mode']}' needs at least one namespace")
        for item in listed:
            if not isinstance(item, str) or item.count("/") != 1 or not all(item.split("/")):
                raise ValueError(f"a namespace must look like host/owner, not {item!r}")
        if set(selection) != {"mode", "namespaces"}:
            raise ValueError(f"{where}basket has unexpected keys")
    elif set(selection) != {"mode"}:
        raise ValueError(f"a '{selection['mode']}' basket takes no namespaces")
    return selection


def validate_scopes(scopes) -> dict:
    if not isinstance(scopes, dict) or set(scopes) != set(SCOPES):
        raise ValueError(f"baskets must define exactly: {', '.join(SCOPES)}")
    for scope in SCOPES:
        validate_selection(scopes[scope], scope)
    if scopes["capture"]["mode"] != "none":
        # A toggle that claims to protect uncommitted work while protecting nothing is worse
        # than no toggle. Capture stays refusable until the medium tier actually captures.
        raise ValueError("content capture is not implemented; the capture basket must be 'none'")
    return scopes


def selects(selection: dict, namespace: str) -> bool:
    mode = selection["mode"]
    if mode == "all":
        return True
    if mode == "none":
        return False
    listed = {item.lower() for item in selection["namespaces"]}
    return (namespace.lower() in listed) if mode == "only" else (namespace.lower() not in listed)


def split(selection: dict, namespaces: dict) -> tuple[set, set]:
    """`(selected, excluded)` repo ids for `{repo_id: namespace}`. Both halves are reported."""
    selected = {key for key, space in namespaces.items() if selects(selection, space)}
    return selected, set(namespaces) - selected


def describe_selection(selection: dict) -> str:
    mode = selection["mode"]
    if mode in ("all", "none"):
        return "every namespace" if mode == "all" else "nothing"
    listed = ", ".join(sorted(selection["namespaces"]))
    return f"only {listed}" if mode == "only" else f"everything except {listed}"


def describe(scopes: dict) -> str:
    lines = [f"  {scope:<8} {describe_selection(scopes[scope])}" for scope in SCOPES]
    lines.append("  (capture is not implemented; it stays 'none')")
    return "\n".join(lines)


def parse_selection(mode: str, namespaces) -> dict:
    """Build a selection from CLI input. Refuses a mode/namespace mismatch rather than guessing."""
    listed = [item.strip().lower() for item in (namespaces or []) if item.strip()]
    selection = {"mode": mode} if mode in ("all", "none") else {"mode": mode, "namespaces": listed}
    return validate_selection(selection)
