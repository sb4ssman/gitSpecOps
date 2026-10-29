"""Pure v2 enrollment/component record validation; no auth, filesystem or app imports.

Import from Special._settings.records; document() validates the typed enrollment sections.
"""
from __future__ import annotations

import math
import re
from pathlib import Path


class RecordError(ValueError):
    """Sanitized schema error: never include supplied paths, keys or values."""


def require(ok, message="invalid enrollment settings"):
    if not ok:
        raise RecordError(message)


def obj(value, allowed, required=()):
    require(isinstance(value, dict) and not (set(value) - set(allowed))
            and set(required) <= set(value), "invalid settings record fields")


def text(value):
    require(isinstance(value, str) and bool(value.strip()) and "\0" not in value,
            "invalid settings string")


def path(value):
    text(value)
    require(Path(value).is_absolute(), "enrollment paths must be absolute")


def integer(value, low=0, high=None):
    require(type(value) is int and value >= low and (high is None or value <= high),
            "invalid settings integer")


def boolean(value):
    require(type(value) is bool, "invalid settings boolean")


def strings(value):
    require(isinstance(value, list), "invalid settings list")
    for item in value:
        text(item)


def machine(value):
    obj(value, ("id", "label", "fleet_secret"), ("id", "label", "fleet_secret"))
    text(value["id"])
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value["id"]) is not None, "invalid machine id")
    text(value["label"])
    require(isinstance(value["fleet_secret"], str) and
            re.fullmatch(r"[0-9a-fA-F]{64}", value["fleet_secret"]) is not None, "invalid fleet key")


def transports(value):
    obj(value, ("folder", "repo", "tailnet"))
    for name, entry in value.items():
        if name == "folder":
            obj(entry, ("path", "seconds"), ("path",))
            path(entry["path"])
        elif name == "repo":
            obj(entry, ("name", "seconds"), ("name",))
            require(isinstance(entry["name"], str) and re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}", entry["name"]) is not None,
                "invalid state repository name")
        else:
            obj(entry, ("port", "allowed_login"), ("port",))
            integer(entry["port"], 1024, 65535)
            if entry.get("allowed_login") is not None:
                text(entry["allowed_login"])
        if "seconds" in entry:
            integer(entry["seconds"], 1)


def baskets(value):
    obj(value, ("observe", "publish", "capture"), ("observe", "publish", "capture"))
    for selection in value.values():
        obj(selection, ("mode", "namespaces"), ("mode",))
        mode = selection["mode"]
        require(mode in ("all", "none", "only", "except"), "invalid scope selection")
        if mode in ("only", "except"):
            strings(selection.get("namespaces"))
            require(bool(selection["namespaces"]), "empty namespace selection")
            require(all(item.count("/") == 1 and all(item.split("/")) for item in selection["namespaces"]),
                    "invalid namespace selection")
        else:
            require(set(selection) == {"mode"}, "unexpected namespace selection")


def recovery(value):
    obj(value, ("location", "confirmed", "policies"), ("location", "confirmed", "policies"))
    if value["location"] is not None:
        path(value["location"])
    boolean(value["confirmed"])
    require(value["location"] is None or value["confirmed"], "recovery location is not confirmed")
    require(isinstance(value["policies"], dict), "invalid recovery policies")
    for identity, policy in value["policies"].items():
        require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{32}", identity) is not None,
                "invalid recovery repository id")
        obj(policy, ("obey_gitignore", "secret_protection", "allow_paths"),
            ("obey_gitignore", "secret_protection", "allow_paths"))
        boolean(policy["obey_gitignore"])
        boolean(policy["secret_protection"])
        strings(policy["allow_paths"])
        for item in policy["allow_paths"]:
            require("\\" not in item and not item.startswith("/") and
                    all(part not in ("", ".", "..") and part.lower() != ".git" for part in item.split("/")),
                    "invalid recovery allowance path")


OPTIONS = {
    "sync": {"root_recursion", "transport_names", "stale_hours", "expired_days", "compress_manifests"},
    "app": {"transport_names", "fetch_minutes", "share_names", "baskets", "recovery", "observation_mode",
            "debounce_seconds", "heartbeat", "inventory_notice_acknowledged", "local_port", "git_client"},
    "archive_manage": {"archives"},
}


def options(component, value):
    obj(value, OPTIONS.get(component, ()))
    for key, item in value.items():
        if key == "transport_names":
            strings(item)
            require(len(item) == len(set(item)) and set(item) <= {"folder", "repo", "tailnet"},
                    "invalid selected transports")
            require(component != "sync" or (len(item) <= 1 and "tailnet" not in item),
                    "unsupported CLI transport selection")
        elif key == "root_recursion":
            require(isinstance(item, dict), "invalid root recursion map")
            for root, recursive in item.items():
                path(root)
                boolean(recursive)
        elif key in ("share_names", "compress_manifests", "inventory_notice_acknowledged"):
            boolean(item)
        elif key in ("stale_hours", "expired_days", "heartbeat", "local_port", "fetch_minutes"):
            integer(item, 0 if key == "fetch_minutes" else (1024 if key == "local_port" else 1),
                    65535 if key == "local_port" else (60 if key == "heartbeat" else None))
        elif key == "debounce_seconds":
            require((type(item) is int and item >= 0) or
                    (type(item) is float and math.isfinite(item) and item >= 0), "invalid debounce duration")
        elif key == "observation_mode":
            require(item == "filesystem-events", "unsupported observation mode")
        elif key == "baskets":
            baskets(item)
        elif key == "recovery":
            recovery(item)
        elif key == "git_client" and item is not None:
            obj(item, ("id", "executable"), ("id", "executable"))
            require(item["id"] in ("sourcetree", "github-desktop"), "unsupported desktop Git client")
            path(item["executable"])
        elif key == "archives":
            require(isinstance(item, list), "invalid managed archives")
            for archive in item:
                obj(archive, ("root", "mode", "approved_remote_prefixes"),
                    ("root", "mode", "approved_remote_prefixes"))
                path(archive["root"])
                require(archive["mode"] in ("update", "sync"), "invalid archive update mode")
                strings(archive["approved_remote_prefixes"])
    if "stale_hours" in value and "expired_days" in value:
        require(value["expired_days"] * 24 >= value["stale_hours"], "inconsistent freshness thresholds")
    if "baskets" in value and value["baskets"]["capture"]["mode"] != "none":
        require(value.get("recovery", {}).get("confirmed") is True and
                value["recovery"].get("location") is not None, "capture requires confirmed recovery storage")


def document(value):
    if "machine" in value:
        machine(value["machine"])
    transports(value.get("transports", {}))
    for component, entries in value.get("components", {}).items():
        selected = entries.get("options", {})
        options(component, selected)
        require(set(selected.get("transport_names", ())) <= set(value.get("transports", {})),
                "selected transport has no definition")
        if selected.get("transport_names"):
            require("machine" in value, "transport selection requires a machine identity")
