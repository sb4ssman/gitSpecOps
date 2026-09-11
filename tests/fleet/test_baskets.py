"""Baskets select per scope, never imply one another, and never narrow silently."""
import copy
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
import baskets
from fleet_config import CONFIG_VERSION, migrate, new_config, validate
from fleet_observer import IncrementalObserver
from local_view import display_from_manifests
from manifest import build_manifest, fleet_id_for


def refused(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("expected refusal")


def test_selection():
    assert baskets.selects(baskets.ALL, "github.com/anyone")
    assert not baskets.selects(baskets.NONE, "github.com/anyone")
    only = baskets.parse_selection("only", ["GitHub.com/Work"])
    assert baskets.selects(only, "github.com/work")          # host and owner are case-folded
    assert not baskets.selects(only, "github.com/personal")
    other = baskets.parse_selection("except", ["github.com/personal"])
    assert baskets.selects(other, "github.com/work")
    assert not baskets.selects(other, "github.com/personal")
    refused(lambda: baskets.parse_selection("only", []))
    refused(lambda: baskets.parse_selection("only", ["not-a-namespace"]))
    refused(lambda: baskets.validate_selection({"mode": "all", "namespaces": ["a/b"]}))
    refused(lambda: baskets.validate_selection({"mode": "everything"}))
    selected, excluded = baskets.split(only, {"r1": "github.com/work", "r2": "github.com/other"})
    assert selected == {"r1"} and excluded == {"r2"}, "both halves must be reported"


def test_scopes_are_independent():
    scopes = copy.deepcopy(baskets.DEFAULT_SCOPES)
    assert scopes["capture"]["mode"] == "none", "capture must never default on"
    # Widening observation must not widen publication or capture.
    scopes["observe"] = baskets.parse_selection("all", None)
    assert baskets.validate_scopes(scopes)["capture"]["mode"] == "none"
    refused(lambda: baskets.validate_scopes({**scopes, "capture": baskets.parse_selection("all", None)}))
    refused(lambda: baskets.validate_scopes({**scopes,
                                             "capture": baskets.parse_selection("only", ["a/b"])}))
    refused(lambda: baskets.validate_scopes({"observe": baskets.ALL, "publish": baskets.ALL}))


def test_config_migration():
    with tempfile.TemporaryDirectory() as temp:
        legacy = {"version": 3, "mode": "peer", "machine_id": "m", "label": "L",
                  "fleet_secret": "22" * 32, "roots": [temp], "heartbeat": 30,
                  "observation_mode": "filesystem-events", "debounce_seconds": 0.75,
                  "inventory_notice_acknowledged": True, "local_port": 8760, "transports": {}}
        migrated = migrate(dict(legacy))
        assert migrated["version"] == CONFIG_VERSION
        # v3 behavior is reproduced exactly: everything observed, everything published.
        assert migrated["baskets"]["observe"] == {"mode": "all"}
        assert migrated["baskets"]["publish"] == {"mode": "all"}
        assert migrated["baskets"]["capture"] == {"mode": "none"}
        validate(migrated)
        refused(lambda: validate({**migrated, "baskets": {"observe": {"mode": "all"},
                                                          "publish": {"mode": "all"},
                                                          "capture": {"mode": "all"}}}))
        fresh = new_config("m", "L", [temp], "22" * 32)
        assert fresh["baskets"] == baskets.DEFAULT_SCOPES
        validate(fresh)


class FakeObserver(IncrementalObserver):
    """Exercise the basket seams without touching Git or the filesystem."""
    def __init__(self, scopes, entries):
        super().__init__({"fleet_secret": "22" * 32, "machine_id": "m", "label": "L",
                          "roots": [], "baskets": scopes})
        for index, (owner, repo_id) in enumerate(entries):
            path = Path(f"/synthetic/{index}")
            self._repos[path] = {"repo_id": repo_id, "branch_id": "c" * 16,
                                 "has_upstream": True, "upstream_observed_at": None,
                                 "ahead": 1, "behind": 0, "staged": 0, "unstaged": 1,
                                 "untracked": 0, "stashes": 0, "operation": None}
            self._catalog[path] = {"host": "github.com", "owner": owner, "name": f"r{index}",
                                   "path": str(path)}


def test_publish_basket_withholds():
    scopes = {**copy.deepcopy(baskets.DEFAULT_SCOPES),
              "publish": baskets.parse_selection("only", ["github.com/work"])}
    observer = FakeObserver(scopes, [("work", "a" * 32), ("personal", "b" * 32)])
    local = observer.report()
    shared, withheld = observer.shared_report(local)
    assert withheld == {"b" * 32}
    published = [repo["repo_id"] for repo in shared["manifest"]["repositories"]]
    assert published == ["a" * 32], "a withheld repository must not reach any transport"
    assert "b" * 32 not in shared["names"], "withheld names must not reach peers either"
    # The local view keeps everything: withholding hides work from peers, not from its owner.
    assert len(local["manifest"]["repositories"]) == 2

    everything = FakeObserver(copy.deepcopy(baskets.DEFAULT_SCOPES), [("work", "a" * 32)])
    same, none_held = everything.shared_report(everything.report())
    assert not none_held and len(same["manifest"]["repositories"]) == 1


def test_dashboard_states_what_is_withheld():
    fleet = fleet_id_for("22" * 32)
    records = [{"repo_id": rid, "branch_id": "c" * 16, "has_upstream": True,
                "upstream_observed_at": None, "ahead": 1, "behind": 0, "staged": 0,
                "unstaged": 1, "untracked": 0, "stashes": 0, "operation": None}
               for rid in ("a" * 32, "b" * 32)]
    manifest = build_manifest(fleet, "machine-a", "A", records)
    names = {"a" * 32: {"host": "github.com", "owner": "work", "name": "r0"},
             "b" * 32: {"host": "github.com", "owner": "personal", "name": "r1"}}
    view = display_from_manifests([manifest], fleet_id=fleet, names=names, settings={
        "local_repo_ids": ["a" * 32, "b" * 32], "withheld_repo_ids": ["b" * 32],
        "unobserved_count": 3, "baskets": copy.deepcopy(baskets.DEFAULT_SCOPES)})
    rows = {row["id"]: row for row in view["rows"]}
    assert rows["a" * 32]["publication"]["published"] is True
    assert rows["b" * 32]["publication"]["published"] is False
    assert rows["b" * 32]["publication"]["reason"], "a withheld row must say so"
    notices = {notice["id"] for notice in view["notices"]}
    assert {"withheld", "unobserved"} <= notices, "narrowing is never silent"
    assert view["baskets"]["withheld"] == 1 and view["baskets"]["unobserved"] == 3
    assert view["capabilities"]["baskets"]["available"] is True
    # No namespace list leaks into a row; only the local settings block carries them.
    quiet = display_from_manifests([manifest], fleet_id=fleet, names=names, settings={})
    assert quiet["baskets"]["configured"] is False
    assert all(row["publication"]["published"] for row in quiet["rows"])
    assert quiet["capabilities"]["baskets"]["available"] is False


def _make_repo(path, owner):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin",
                    f"https://github.com/{owner}/{path.name}.git"],
                   check=True, capture_output=True)
    (path / "note.txt").write_text("uncommitted\n")


def test_withheld_work_never_reaches_a_transport():
    """The property unit tests cannot reach: a real peer run, writing a real manifest.

    This caught a defect the seam tests could not. The dashboard read this machine's *own*
    manifest back out of the transport, where a publish basket had already narrowed it, and that
    narrower echo won over live local state -- so withheld repositories vanished from the one
    screen that must always show them.
    """
    import fleet_peer

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        library, folder, config_dir = root / "lib", root / "folder", root / "cfg"
        folder.mkdir()
        config_dir.mkdir()
        _make_repo(library / "work-thing", "work-org")
        _make_repo(library / "other-thing", "other-owner")
        config = new_config("machine-a", "A", [library], "22" * 32,
                            transports={"folder": {"path": str(folder), "seconds": 1}})
        config["baskets"]["publish"] = baskets.parse_selection("only", ["github.com/work-org"])

        captured = {}
        fleet_peer.run_peer(config, config_dir, threading.Event(), once=True,
                            on_ready=lambda info: captured.update(info), log=lambda *_: None)

        written = [item for item in folder.rglob("*") if item.is_file()]
        assert len(written) == 1, written
        raw = written[0].read_bytes()
        manifest = json.loads(gzip.decompress(raw) if written[0].suffix == ".gz" else raw)
        assert len(manifest["repositories"]) == 1, "withheld work must not be written anywhere"

        document = captured["dashboard"]()
        withheld = [row["name"] for row in document["rows"] if not row["publication"]["published"]]
        assert len(document["rows"]) == 2, "both repositories must stay visible to their owner"
        assert withheld == ["other-owner/other-thing"], withheld
        assert "withheld" in {notice["id"] for notice in document["notices"]}


def main():
    test_selection()
    test_scopes_are_independent()
    test_config_migration()
    test_publish_basket_withholds()
    test_dashboard_states_what_is_withheld()
    test_withheld_work_never_reaches_a_transport()
    print("ALL-BASKET-TESTS-PASS")


if __name__ == "__main__":
    main()
