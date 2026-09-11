"""The dashboard must work with no host and no Tailscale, from published manifests alone.

This is the property the whole design rests on: every machine owns one file, and a dashboard is
just "read every file I can see". A machine that is offline, asleep, or switched off still has
its last manifest sitting in the transport, and must keep appearing — with honest freshness —
rather than vanishing.

Offline and synthetic: a temporary folder transport stands in for the synced folder.
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

from folder_transport import FolderTransport  # noqa: E402
from local_view import display_from_transport, reports_from_manifests  # noqa: E402
from manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "33" * 32
FLEET = fleet_id_for(SECRET)
OTHER_FLEET = fleet_id_for("44" * 32)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def manifest_for(machine, fleet=FLEET, dirty=0, observed=None, repo_id="e" * 32):
    return build_manifest(fleet, machine, machine, [{
        "repo_id": repo_id, "branch_id": "f" * 16, "has_upstream": True,
        "upstream_observed_at": None, "ahead": 0, "behind": 0,
        "staged": 0, "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
    }], observed_at=observed)


def test_offline_machines_still_appear():
    """The core claim: no live connection, and an old manifest is still a visible machine."""
    now = datetime.now(timezone.utc)
    long_ago = (now - timedelta(days=3)).isoformat()
    with tempfile.TemporaryDirectory() as temp:
        transport = FolderTransport(temp)
        transport.write_own_manifest("awake", manifest_for("awake", observed=now.isoformat()))
        transport.write_own_manifest("asleep", manifest_for("asleep", dirty=4, observed=long_ago))
        document = display_from_transport(transport, {"fleet_id": FLEET}, {}, now=now)

    labels = {m["label"]: m["freshness"] for m in document["machines"]}
    check(set(labels) == {"awake", "asleep"}, f"both machines must appear: {labels}")
    check(labels["asleep"] != "current", "a three-day-old report must not read as current")
    check(document["summary"]["machines"] == 2, "summary must count every known machine")
    check(document["contract"]["name"] == "gitspecops.fleet.display",
          "the local dashboard must emit the same contract every skin consumes")


def test_unfinished_work_on_an_offline_machine_is_not_an_all_clear():
    """Silence is never good news: stale *unfinished* work keeps warning."""
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(days=2)).isoformat()
    with tempfile.TemporaryDirectory() as temp:
        transport = FolderTransport(temp)
        transport.write_own_manifest("gone", manifest_for("gone", dirty=7, observed=stale))
        document = display_from_transport(transport, {"fleet_id": FLEET}, {}, now=now)
    check(document["summary"]["attention"] >= 1,
          "uncommitted work on an offline machine must still demand attention")


def test_foreign_fleet_manifests_are_reported_not_merged():
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as temp:
        transport = FolderTransport(temp)
        transport.write_own_manifest("mine", manifest_for("mine", observed=now.isoformat()))
        transport.write_own_manifest("stranger",
                                     manifest_for("stranger", fleet=OTHER_FLEET,
                                                  observed=now.isoformat()))
        document = display_from_transport(transport, {"fleet_id": FLEET}, {}, now=now)
    labels = [m["label"] for m in document["machines"]]
    check(labels == ["mine"], f"a different fleet must not be merged in: {labels}")
    text = " ".join(item for issue in document["issues"] for item in issue["items"])
    check("different fleet" in text, f"the mismatch must be surfaced, not silent: {text}")


def test_unknown_peer_repositories_keep_their_digest():
    """A repo only a peer has cannot be named locally; inventing a name would be worse."""
    reports = reports_from_manifests([manifest_for("peer")], catalog={})
    identity = list(reports[0]["names"].values())[0]
    check(identity["owner"] == "unidentified",
          f"an unresolvable repo id must say so: {identity}")
    check("e" * 8 in identity["name"], f"the digest prefix must remain visible: {identity}")


def test_catalog_names_are_used_when_known():
    catalog = {"e" * 32: {"host": "github.com", "owner": "example", "name": "work"}}
    reports = reports_from_manifests([manifest_for("mine")], catalog=catalog)
    identity = list(reports[0]["names"].values())[0]
    check((identity["owner"], identity["name"]) == ("example", "work"),
          f"a locally known repository must render readably: {identity}")


def test_empty_transport_is_a_valid_empty_fleet():
    with tempfile.TemporaryDirectory() as temp:
        document = display_from_transport(FolderTransport(temp), {"fleet_id": FLEET}, {})
    check(document["summary"]["machines"] == 0, "an empty fleet is zero machines, not an error")
    check(document["rows"] == [], "no manifests means no rows")


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        print("LOCAL-DASHBOARD-TESTS FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"ALL-LOCAL-DASHBOARD-TESTS-PASS ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
