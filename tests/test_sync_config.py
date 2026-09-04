"""Synthetic, offline tests for Sync Suggester persistent local state (config + catalog).

Every path used here is a disposable temporary directory; no real machine paths, no real
repository names, no network.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "git-sync-suggester"
sys.path.insert(0, str(TOOL_DIR))

from config import (  # noqa: E402
    CONFIG_SCHEMA_VERSION,
    catalog_path,
    config_path,
    default_config,
    default_config_dir,
    default_machine_id,
    display_name_for,
    load_catalog,
    load_config,
    merge_catalog,
    roots_from_archive_registry,
    save_catalog,
    save_config,
    validate_config,
)
from folder_transport import SAFE_MACHINE_ID, atomic_write_bytes  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def rejects(value, message):
    try:
        validate_config(value)
    except ValueError:
        return
    failures.append(f"validate_config accepted {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    # --- config directory selection -------------------------------------------------
    os.environ["GITSPECOPS_SYNC_HOME"] = str(tmp / "override")
    check(default_config_dir() == tmp / "override", "GITSPECOPS_SYNC_HOME did not win")
    del os.environ["GITSPECOPS_SYNC_HOME"]
    check("gitspecops" in str(default_config_dir()).lower(),
          "default config dir is not namespaced under gitspecops")

    # --- identity -------------------------------------------------------------------
    check(bool(SAFE_MACHINE_ID.fullmatch(default_machine_id())),
          "default_machine_id produced an id the transport would reject")

    # --- round trip -----------------------------------------------------------------
    config_dir = tmp / "cfg"
    original = default_config("alpha-machine")
    original["machine_label"] = "ALPHA"
    original["state_dir"] = str(tmp / "state")
    original["roots"] = [{"path": str(tmp / "one"), "recursive": False},
                         {"path": str(tmp / "two"), "recursive": True}]
    save_config(config_dir, original)
    check(load_config(config_dir) == original, "config did not survive a save/load round trip")
    check(load_config(tmp / "never-written") is None, "missing config should read as None")

    config_path(config_dir).write_text("{not json", encoding="utf-8")
    try:
        load_config(config_dir)
        failures.append("corrupt config did not raise")
    except ValueError:
        pass
    save_config(config_dir, original)

    # --- validation -----------------------------------------------------------------
    rejects("nope", "a non-object config")
    rejects({**original, "surprise": 1}, "an unknown top-level field")
    rejects({**original, "schema_version": CONFIG_SCHEMA_VERSION + 1}, "a future schema version")
    rejects({**original, "machine_id": "bad id/slash"}, "a machine_id with unsafe characters")
    rejects({**original, "machine_id": ""}, "an empty machine_id")
    rejects({**original, "machine_label": ""}, "an empty machine_label")
    rejects({**original, "state_dir": ""}, "an empty state_dir")
    rejects({**original, "roots": "one"}, "roots as a string")
    rejects({**original, "roots": [{"path": "/a", "extra": 1}]}, "an unknown root field")
    rejects({**original, "roots": [{"path": ""}]}, "an empty root path")
    rejects({**original, "roots": [{"path": "/a", "recursive": "yes"}]}, "a non-boolean recursive")
    rejects({**original, "roots": [{"path": "/a"}, {"path": "/a"}]}, "a duplicate root")
    rejects({**original, "stale_hours": 0}, "stale_hours below one")
    rejects({**original, "stale_hours": True}, "a boolean stale_hours")
    rejects({**original, "expired_days": 1, "stale_hours": 48},
            "an expiry window shorter than the stale window")
    check(validate_config({**original, "state_dir": None}) is not None,
          "a null state_dir should be allowed (preview-only machine)")

    # --- catalog --------------------------------------------------------------------
    check(load_catalog(config_dir) == {}, "missing catalog should read as empty")
    first = {"a" * 64: {"display_name": "alpha-repo", "path": str(tmp / "one" / "alpha-repo")}}
    save_catalog(config_dir, first)
    check(load_catalog(config_dir) == first, "catalog did not survive a round trip")

    catalog_path(config_dir).write_text("{broken", encoding="utf-8")
    check(load_catalog(config_dir) == {}, "corrupt catalog should degrade to empty, not raise")
    save_catalog(config_dir, first)

    aliased = {**first}
    aliased["a" * 64] = {**aliased["a" * 64], "alias": "my name for it"}
    aliased["b" * 64] = {"display_name": "peer-only"}
    merged = merge_catalog(aliased, {"a" * 64: {"display_name": "alpha-repo",
                                                "path": str(tmp / "moved" / "alpha-repo")}})
    check(merged["a" * 64].get("alias") == "my name for it",
          "re-observation erased a user-supplied alias")
    check(merged["a" * 64]["path"].endswith("moved/alpha-repo"),
          "re-observation did not update the local path")
    check("b" * 64 in merged, "merge dropped an entry that was not observed this run")

    check(display_name_for("a" * 64, merged) == "my name for it", "alias did not win")
    check(display_name_for("b" * 64, merged) == "peer-only", "display_name was not used")
    check(display_name_for("c" * 64, merged) == "repo:cccccccc",
          "unknown repo id did not fall back to a short stable identifier")

    # --- archive registry import ----------------------------------------------------
    fake_repo = tmp / "fake-repo"
    (fake_repo / "git-archive-updater").mkdir(parents=True)
    registry = fake_repo / "git-archive-updater" / "managed_archives.json"
    check(roots_from_archive_registry(fake_repo) == [], "missing registry should import nothing")
    registry.write_text("{broken", encoding="utf-8")
    check(roots_from_archive_registry(fake_repo) == [], "corrupt registry should import nothing")
    registry.write_text(json.dumps({"version": 1, "installations": "nope"}), encoding="utf-8")
    check(roots_from_archive_registry(fake_repo) == [], "non-list installations should import nothing")
    registry.write_text(json.dumps({"version": 1, "installations": [
        {"root": "/archives/one", "mode": "update"},
        {"mode": "sync"},
        {"root": ""},
        {"root": "/archives/two"},
    ]}), encoding="utf-8")
    check(roots_from_archive_registry(fake_repo) == ["/archives/one", "/archives/two"],
          "registry import did not skip records without a usable root")

    # --- atomic write ---------------------------------------------------------------
    target = tmp / "atomic.json"
    atomic_write_bytes(target, b"first")
    atomic_write_bytes(target, b"second")
    check(target.read_bytes() == b"second", "atomic write did not replace the file")
    leftovers = [p.name for p in tmp.iterdir() if p.name.startswith(".atomic.json-")]
    check(not leftovers, f"atomic write left temporary files behind: {leftovers}")

if failures:
    print("SYNC-CONFIG-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-SYNC-CONFIG-TESTS-PASS")
