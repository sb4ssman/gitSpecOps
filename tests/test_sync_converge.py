"""Synthetic, offline tests for fleet convergence.

The provider is a stub, so nothing here touches the network. The property that matters most:
a repository is named by hashing *candidates* under the fleet secret and matching, so the
name never has to travel in a manifest — and a repository the provider cannot see stays an
opaque identifier instead of leaking or guessing.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "git-sync-suggester"))
sys.path.insert(0, str(ROOT))

from aggregate import machine_views  # noqa: E402
from convergence import (  # noqa: E402
    catalog_updates,
    missing_from,
    namespaces_from_catalog,
    render_report,
    resolve_missing,
    roots_by_owner,
)
from manifest import (branch_id, build_manifest, fleet_id_for,  # noqa: E402
                      repository_id)
from shared.remote_identity import RepoRef  # noqa: E402

failures = []
SECRET = "ab" * 32
FLEET_ID = fleet_id_for(SECRET)
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-03T11:55:00Z"

NAMES = ["alpha-tool", "beta-service", "gamma-notes", "hidden-thing"]
IDS = {name: repository_id("example.test", "sample-team", name, SECRET) for name in NAMES}


def check(condition, message):
    if not condition:
        failures.append(message)


def repo(name):
    return {"repo_id": IDS[name], "branch_id": branch_id("main", SECRET),
            "has_upstream": True,
            "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0,
            "unstaged": 0, "untracked": 0, "stashes": 0, "operation": None}


def views(machines):
    return machine_views(
        [build_manifest(FLEET_ID, mid, label, [repo(n) for n in names], observed_at=STAMP)
         for mid, label, names in machines],
        NOW, 24, 7)


class StubProvider:
    """Records its calls so the tests can prove when the network was avoided."""

    def __init__(self, repos_by_owner, error=None):
        self.repos_by_owner, self.error, self.calls = repos_by_owner, error, []

    def list_repos(self, owner):
        self.calls.append(owner)
        if self.error:
            return None, self.error
        return [RepoRef(id=n, owner=owner, name=n, url=f"https://example.test/{owner}/{n}",
                        host="example.test")
                for n in self.repos_by_owner.get(owner, [])], None


def provider_lookup(provider):
    return lambda host: provider


# --- what is missing ------------------------------------------------------------------
fleet = views([
    ("mine", "MINE", ["alpha-tool"]),
    ("desk", "DESK", ["alpha-tool", "beta-service", "gamma-notes"]),
    ("pi", "PI", ["gamma-notes", "hidden-thing"]),
])
missing = missing_from(fleet, "mine")
check(set(missing) == {IDS["beta-service"], IDS["gamma-notes"], IDS["hidden-thing"]},
      f"missing set is wrong: {sorted(missing)}")
check(IDS["alpha-tool"] not in missing, "a repository this machine already has was called missing")
check(missing[IDS["gamma-notes"]] == ["DESK", "PI"],
      f"peer attribution is wrong: {missing[IDS['gamma-notes']]}")
check(missing_from(fleet, "desk").keys() == {IDS["hidden-thing"]},
      "missing_from is not relative to the machine asked about")
check(missing_from(views([("solo", "SOLO", ["alpha-tool"])]), "solo") == {},
      "a lone machine should be missing nothing")
check(missing_from(fleet, "unknown-machine").keys() ==
      {IDS["alpha-tool"], IDS["beta-service"], IDS["gamma-notes"], IDS["hidden-thing"]},
      "a machine that has not published should see every repository as missing")

# --- naming the unknown ---------------------------------------------------------------
provider = StubProvider({"sample-team": ["alpha-tool", "beta-service", "gamma-notes"]})
resolved, errors = resolve_missing(missing, [("example.test", "sample-team")], SECRET,
                                   provider_lookup(provider))
by_id = {r.repo_id: r for r in resolved}
check(not errors, f"unexpected errors: {errors}")
check(by_id[IDS["beta-service"]].name == "beta-service",
      "a repository the provider can see was not named")
check(by_id[IDS["beta-service"]].label == "sample-team/beta-service",
      f"unexpected label: {by_id[IDS['beta-service']].label}")
check(not by_id[IDS["hidden-thing"]].identified,
      "a repository the provider cannot see must stay unidentified, not be guessed")
check(by_id[IDS["hidden-thing"]].label.startswith("repo:"),
      "an unidentified repository should show a short stable id")
check([r.identified for r in resolved] == sorted([r.identified for r in resolved], reverse=True),
      "identified repositories should be listed before unidentified ones")

# a different fleet secret must not resolve anything: the digests simply will not match
wrong, _ = resolve_missing(missing, [("example.test", "sample-team")], "cd" * 32,
                           provider_lookup(StubProvider(
                               {"sample-team": ["alpha-tool", "beta-service", "gamma-notes"]})))
check(not any(r.identified for r in wrong),
      "candidates hashed under the wrong fleet secret should never match")

# --- the catalog avoids the network ---------------------------------------------------
known = {IDS["beta-service"]: {"host": "example.test", "owner": "sample-team",
                               "name": "beta-service"},
         IDS["gamma-notes"]: {"host": "example.test", "owner": "sample-team",
                              "name": "gamma-notes"},
         IDS["hidden-thing"]: {"host": "example.test", "owner": "sample-team",
                               "name": "hidden-thing"}}
quiet = StubProvider({"sample-team": []})
resolved_known, _ = resolve_missing(missing, [("example.test", "sample-team")], SECRET,
                                    provider_lookup(quiet), known=known)
check(quiet.calls == [],
      f"the provider was called even though the catalog knew every name: {quiet.calls}")
check(all(r.identified for r in resolved_known), "catalog seeding did not name everything")

partial = StubProvider({"sample-team": ["gamma-notes", "hidden-thing"]})
resolve_missing(missing, [("example.test", "sample-team")], SECRET, provider_lookup(partial),
                known={IDS["beta-service"]: {"host": "example.test", "owner": "sample-team",
                                             "name": "beta-service"}})
check(partial.calls == ["sample-team"],
      "the provider should still be asked about the names the catalog did not cover")

# --- failures are reported, not fatal --------------------------------------------------
broken, errors = resolve_missing(missing, [("example.test", "sample-team")], SECRET,
                                 provider_lookup(StubProvider({}, error="403 no access")))
check(any("403 no access" in e for e in errors), f"a provider error was not reported: {errors}")
check(not any(r.identified for r in broken), "a failed listing must not name anything")
_, no_provider = resolve_missing(missing, [("nowhere.test", "sample-team")], SECRET,
                                 lambda host: None)
check(any("no provider registered" in e for e in no_provider),
      f"an unregistered host was not reported: {no_provider}")

# --- catalog updates -------------------------------------------------------------------
updates = catalog_updates(resolved)
check(set(updates) == {IDS["beta-service"], IDS["gamma-notes"]},
      "catalog updates should cover exactly the newly identified repositories")
check(all("path" not in entry for entry in updates.values()),
      "a repository this machine does not have must not be given a local path")

# --- where a clone would go -------------------------------------------------------------
catalog = {
    "id1": {"owner": "sample-team", "path": "/archive/sample-team/one"},
    "id2": {"owner": "sample-team", "path": "/archive/sample-team/two"},
    "id3": {"owner": "sample-team", "path": "/elsewhere/three"},
    "id4": {"owner": "other-team", "path": "/archive/other-team/four"},
    "id5": {"owner": "no-path-team"},
}
roots = roots_by_owner(catalog)
check(roots.get("sample-team") == "/archive/sample-team",
      f"the common parent was not chosen: {roots.get('sample-team')}")
check(roots.get("other-team") == "/archive/other-team", "a single-repo owner root was not found")
check("no-path-team" not in roots, "an owner with no local path should yield no suggestion")

check(namespaces_from_catalog({"a": {"host": "example.test", "owner": "sample-team"},
                               "b": {"host": "example.test", "owner": "sample-team"},
                               "c": {"host": "other.test", "owner": "team-two"},
                               "d": {"display_name": "no identity"}}) ==
      [("example.test", "sample-team"), ("other.test", "team-two")],
      "namespace derivation from the catalog is wrong")

# --- the report ---------------------------------------------------------------------------
text = render_report(resolved, [], [("example.test", "sample-team")],
                     {"sample-team": "/archive/sample-team"})
check("sample-team/beta-service" in text, "the report omitted an identified repository")
check("DESK" in text, "the report does not say which machines have it")
check("--root /archive/sample-team" in text and "--github-owner sample-team" in text,
      "the report does not emit a concrete archive_sync command")
check("clones nothing itself" in text, "the report does not state that it will not clone")
check("could not be named" in text, "the report does not explain the unidentified entry")

empty = render_report([], [], [])
check("Nothing to converge" in empty, f"unexpected empty report: {empty}")

placeholder = render_report(resolved, [], [("example.test", "sample-team")], {})
check("<folder holding your sample-team repositories>" in placeholder,
      "with no known local root the report should say so rather than invent a path")

if failures:
    print("SYNC-CONVERGE-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-SYNC-CONVERGE-TESTS-PASS")
