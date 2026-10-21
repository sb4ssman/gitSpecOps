"""Observation sees the work most at risk: repositories with no remote, and unpushed commits
on branches that are not checked out.

The bug this pins (2026-10-19): the observer dropped every repository without a parseable
`origin` -- a repository with no remote, the only copy of its whole history, appeared only as
an issue line -- and it judged only the current branch, so commits on any other branch were
invisible. Both fed the fleet map, `audit` and `safe-to-wipe`.

Real repositories in a temporary folder; remotes are local bare repositories (offline).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

import baskets  # noqa: E402
from advice import classify_repository, describe_repository, repository_flags  # noqa: E402
from aggregate import build_rows, machine_views  # noqa: E402
from convergence import namespaces_from_catalog  # noqa: E402
from fleet_config import new_config  # noqa: E402
from fleet_display import build_display  # noqa: E402
from fleet_observer import IncrementalObserver  # noqa: E402
from fleet_store import validate_report  # noqa: E402
from local_view import display_from_manifests  # noqa: E402
from manifest import SCHEMA_VERSION, build_manifest, fleet_id_for, validate_manifest  # noqa: E402
from observer import RootSpec, observe_roots  # noqa: E402

SECRET = "88" * 32
FLEET = fleet_id_for(SECRET)
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
FAILS: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(f"{label}: {detail}")


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"add {name}")


def local_only(where: Path) -> Path:
    where.mkdir(parents=True)
    git(where, "init", "-q")
    commit(where, "only-copy.txt")
    return where


def with_remote(tmp: Path, where: Path, url: str, remote: str = "origin") -> Path:
    """A clone of a local bare repository, pushed, then shown under a host-shaped `url`."""
    bare = tmp / "remotes" / f"{where.name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    git(tmp, "init", "-q", "--bare", str(bare))
    git(tmp, "clone", "-q", "-o", remote, str(bare), str(where))
    commit(where, "base.txt")
    git(where, "push", "-q", "-u", remote, "main")
    git(where, "remote", "set-url", remote, url)
    return where


def by_name(observation):
    names = {repo_id: entry["display_name"] for repo_id, entry in observation.catalog.items()}
    return {names[repo["repo_id"]]: repo for repo in observation.repositories}, \
        {entry["display_name"]: entry for entry in observation.catalog.values()}


with tempfile.TemporaryDirectory(prefix="at-risk-") as temp:
    tmp = Path(temp)
    lib = tmp / "lib"

    local_only(lib / "only-copy")
    (lib / "empty-history").mkdir(parents=True)
    git(lib / "empty-history", "init", "-q")
    pushed = with_remote(tmp, lib / "pushed", "https://example.test/team/pushed.git")
    side = with_remote(tmp, lib / "side-branch", "https://example.test/team/side-branch.git")
    git(side, "switch", "-qc", "wip")
    commit(side, "wip.txt")
    git(side, "switch", "-q", "main")
    other = with_remote(tmp, lib / "other-remote", "https://example.test/team/other-remote.git",
                        remote="github")
    odd = with_remote(tmp, lib / "odd-remote", "https://example.test/team/odd-remote.git")
    git(odd, "remote", "set-url", "origin", str(tmp / "somewhere" / "odd.git"))

    observation = observe_roots([RootSpec(lib)], SECRET)
    repos, catalog = by_name(observation)

    check("every repository is observed, none dropped",
          set(repos) == {"only-copy", "empty-history", "pushed", "side-branch", "other-remote",
                         "odd-remote"}, sorted(repos))
    check("no issue line stands in for a repository that has no origin",
          not any("origin" in issue for issue in observation.issues), observation.issues)

    one = repos.get("only-copy", {})
    check("a repository with no remote says so", one.get("has_remote") is False, one)
    check("its identity comes from its root commit", one.get("identity") == "root", one)
    check("all of its commits count as on no remote", one.get("unpushed") == 1, one)
    check("it is classified as the only copy", classify_repository(one)[0] == "local_only",
          classify_repository(one))
    check("its description says no remote, not merely no upstream",
          "no remote" in describe_repository(one)
          and "no upstream" not in describe_repository(one), describe_repository(one))
    check("its catalog entry is marked, so converge never asks a host about it",
          catalog["only-copy"].get("identity") == "root"
          and namespaces_from_catalog({"x": catalog["only-copy"]}) == [], catalog["only-copy"])

    empty = repos.get("empty-history", {})
    check("a repository with no commits is still observed, with a per-machine identity",
          empty.get("identity") == "local" and empty.get("has_remote") is False, empty)

    check("a pushed repository has nothing on no remote",
          repos.get("pushed", {}).get("unpushed") == 0
          and classify_repository(repos.get("pushed", {}))[0] == "synced", repos.get("pushed"))

    s = repos.get("side-branch", {})
    check("commits on a branch that is not checked out are counted", s.get("unpushed") == 1, s)
    check("and classified, though the current branch is clean and level",
          classify_repository(s)[0] == "unpushed" and "unpushed" in repository_flags(s),
          classify_repository(s))

    o = repos.get("other-remote", {})
    check("a remote not named origin still gives a remote identity",
          o.get("identity") == "remote" and catalog["other-remote"].get("owner") == "team", o)

    d = repos.get("odd-remote", {})
    check("an unrecognizable remote URL falls back to the root identity, remote noted",
          d.get("identity") == "root" and d.get("has_remote") is True, d)

    # Two machines holding the same no-remote repository match without exchanging a name.
    second = tmp / "machine-b"
    git(tmp, "clone", "-q", "--no-hardlinks", str(lib / "only-copy"), str(second / "only-copy"))
    git(second / "only-copy", "remote", "remove", "origin")
    theirs, _ = by_name(observe_roots([RootSpec(second)], SECRET))
    check("the same history on two machines has the same identity",
          theirs.get("only-copy", {}).get("repo_id") == one.get("repo_id"))
    unrelated, _ = by_name(observe_roots([RootSpec(tmp / "unrelated-lib")], SECRET)) \
        if local_only(tmp / "unrelated-lib" / "only-copy") else ({}, {})
    check("an unrelated history with the same folder name does not",
          unrelated.get("only-copy", {}).get("repo_id") != one.get("repo_id"))

    # --- the manifest carries the new facts and nothing more -------------------------------
    manifest = build_manifest(FLEET, "machine-a", "A", observation.repositories)
    check("the manifest is schema v5", manifest["schema_version"] == SCHEMA_VERSION == 5)
    check("names are left out unless asked for", manifest["carries_names"] is False and not any(
        set(repo) & {"name", "branch", "head"} for repo in manifest["repositories"]))
    for bad in ({"identity": "name"}, {"has_remote": "yes"}, {"unpushed": -1},
                {"unpushed": "3"}):
        # The published (name-free) record, so the only thing wrong is `bad`.
        record = {**manifest["repositories"][0], **bad}
        try:
            validate_manifest({**manifest, "repositories": [record]})
            check(f"a record with {bad} is refused", False)
        except ValueError:
            check(f"a record with {bad} is refused", True)
    payload = str(manifest)
    check("no folder name or path is published", "only-copy" not in payload
          and str(tmp) not in payload)

    # --- v5: names, branch and head where names are shared; paths never --------------------
    named = build_manifest(FLEET, "machine-a", "A", observation.repositories,
                           carries_names=True)
    records = {repo["name"]["name"]: repo for repo in named["repositories"]}
    only = records.get("only-copy", {})
    check("a named manifest names every repository, the no-remote one included",
          named["carries_names"] is True and only.get("name", {}).get("owner") == "no-remote")
    check("it carries the readable branch and the checked-out commit",
          only.get("branch") == git(lib / "only-copy", "branch", "--show-current").strip()
          and only.get("head") == git(lib / "only-copy", "rev-parse", "HEAD").strip(),
          (only.get("branch"), only.get("head")))
    check("still no path is published", str(tmp) not in str(named))
    for bad in ({"name": {"host": "h", "owner": "o"}}, {"name": "o/n"}, {"branch": ""},
                {"head": "abc"}, {"head": "g" * 40}):
        try:
            validate_manifest({**named, "repositories": [{**named["repositories"][0], **bad}]})
            check(f"a named record with {bad} is refused", False)
        except ValueError:
            check(f"a named record with {bad} is refused", True)
    try:
        validate_manifest({**manifest, "repositories": [named["repositories"][0]]})
        check("names in a manifest that says it carries none are refused", False)
    except ValueError:
        check("names in a manifest that says it carries none are refused", True)
    two = [{**named["repositories"][0], "head": "a" * 40},
           {**named["repositories"][0], "head": "b" * 40}]
    merged = build_manifest(FLEET, "machine-a", "A", two, carries_names=True)["repositories"]
    check("two checkouts on different commits merge to an unknown head, not a guess",
          len(merged) == 1 and merged[0]["head"] is None)

    # --- v5 on another machine: it holds none of these repositories itself ----------------
    shared_b = build_manifest(FLEET, "machine-b", "B", observation.repositories,
                              carries_names=True)
    quiet_c = build_manifest(FLEET, "machine-c", "C", observation.repositories)
    for order in ((shared_b, quiet_c), (quiet_c, shared_b)):
        seen = display_from_manifests(list(order), fleet_id=FLEET)
        named_rows = {row["name"] for row in seen["rows"]}
        check("a machine holding none of them sees their names, whatever the reading order",
              "team/pushed" in named_rows and not any(n.startswith("unidentified")
                                                       for n in named_rows), sorted(named_rows))
    seen = display_from_manifests([shared_b, quiet_c], fleet_id=FLEET)
    pushed_row = next(row for row in seen["rows"] if row["name"] == "team/pushed")
    check("the sharing machine's branch and commit reach the detail; the other's do not",
          pushed_row["cells"]["machine-b"]["facts"]["branch"] == "main"
          and len(pushed_row["cells"]["machine-b"]["facts"]["head"] or "") == 40
          and pushed_row["cells"]["machine-c"]["facts"]["head"] is None)
    withheld = display_from_manifests([quiet_c], fleet_id=FLEET)
    check("without names, a stranger's repositories stay honest placeholders",
          all(row["name"].startswith("unidentified") for row in withheld["rows"]))

    quiet_peer = IncrementalObserver({**new_config("machine-a", "A", [lib], SECRET),
                                      "share_names": False})
    quiet_peer.inventory()
    quiet_report = quiet_peer.report()
    shared, _ = quiet_peer.shared_report(quiet_report)
    check("with names turned off, nothing named leaves the machine by any route",
          shared["manifest"]["carries_names"] is False and shared["names"] == {}
          and quiet_report["names"])   # ...while its own dashboard still names them

    # --- end to end: the live peer's report, the store's boundary, the display -------------
    observer = IncrementalObserver(new_config("machine-a", "A", [lib], SECRET))
    count = observer.inventory()
    report = observer.report()
    check("the peer's inventory holds every repository", count == 6, count)
    validate_report(report, "machine-a", FLEET)
    check("a live report with these records passes the store's boundary", True)
    now = datetime.now(timezone.utc)
    view = build_display([report], FLEET, now=now)
    rows = {row["name"]: row for row in view["rows"]}
    only_row = next((row for name, row in rows.items() if name.endswith("only-copy")), None)
    check("the dashboard shows the no-remote repository", only_row is not None, sorted(rows))
    if only_row:
        cell = only_row["cells"]["machine-a"]
        check("as danger, needing attention", cell["tone"] == "danger"
              and only_row["needs_attention"], cell)
        check("with advice that names the risk", "no remote" in only_row["advice"].lower(),
              only_row["advice"])
        check("and a filterable tag", "local_only" in only_row["tags"], only_row["tags"])
    check("the dashboard offers a filter for it",
          any(item["id"] == "local_only" for item in view["filters"]), view["filters"])
    side_row = next((row for name, row in rows.items() if name.endswith("side-branch")), None)
    check("side-branch commits reach the dashboard as unpushed work",
          side_row is not None and "ahead" in side_row["tags"]
          and side_row["cells"]["machine-a"]["tone"] == "warning", side_row)

    # Going quiet does not make the only copy safe.
    old = build_manifest(FLEET, "machine-a", "A", observation.repositories,
                         observed_at="2020-01-01T00:00:00Z")
    stale_rows = {row.repo_id: row for row in build_rows(machine_views([old], now, 1, 7), {})}
    check("a stale machine's only-copy warning survives",
          stale_rows[one["repo_id"]].severity_key in ("local_only", "stale_work"),
          stale_rows[one["repo_id"]].severity_key)

    # Two checkouts of one repository on one machine (a second clone, a copied folder, a linked
    # worktree) share an identity. The dashboard used to keep one and drop the other -- a dirty
    # copy could hide behind a clean one -- and peers refused the whole machine's report.
    twins = tmp / "twins"
    local_only(twins / "project")
    git(tmp, "clone", "-q", "--no-hardlinks", str(twins / "project"), str(twins / "project-copy"))
    git(twins / "project-copy", "remote", "remove", "origin")
    (twins / "project-copy" / "draft.txt").write_text("unsaved idea", encoding="utf-8")
    observer = IncrementalObserver(new_config("machine-a", "A", [twins], SECRET))
    observer.inventory()
    twin_report = observer.report()
    records = twin_report["manifest"]["repositories"]
    check("two checkouts of one repository become one record", len(records) == 1, records)
    check("that record says there are two checkouts", records[0].get("checkouts") == 2, records)
    check("and keeps the dirty copy's work visible", records[0]["untracked"] == 1, records)
    try:
        validate_report(twin_report, "machine-a", FLEET)
        check("a peer accepts the machine's report", True)
    except ValueError as exc:
        check("a peer accepts the machine's report", False, exc)
    check("both folders stay watched, so an edit in either is noticed",
          {p.name for p in observer.paths} == {"project", "project-copy"}
          and observer.affected_repositories({twins / "project" / "x.txt"})
          == {(twins / "project").resolve()}, observer.paths)
    # The same with the dirty copy sorting first: this once passed only by sort-order luck.
    flipped = tmp / "twins-flipped"
    local_only(flipped / "b-original")
    git(tmp, "clone", "-q", "--no-hardlinks", str(flipped / "b-original"), str(flipped / "a-copy"))
    git(flipped / "a-copy", "remote", "remove", "origin")
    (flipped / "a-copy" / "draft.txt").write_text("unsaved idea", encoding="utf-8")
    flipped_observer = IncrementalObserver(new_config("machine-a", "A", [flipped], SECRET))
    flipped_observer.inventory()
    flipped_records = flipped_observer.report()["manifest"]["repositories"]
    check("whichever folder sorts first, the dirty copy's work is kept",
          len(flipped_records) == 1 and flipped_records[0]["untracked"] == 1, flipped_records)
    twin_view = build_display([twin_report], FLEET, now=now)
    check("the dashboard shows the work and the second checkout",
          "2 checkouts" in twin_view["rows"][0]["cells"]["machine-a"]["description"]
          and twin_view["rows"][0]["cells"]["machine-a"]["tone"] == "danger", twin_view["rows"])

    # Baskets can name the no-remote group like any namespace.
    only_local = baskets.parse_selection("only", [baskets.namespace_of(catalog["only-copy"])])
    check("a basket can select repositories with no remote",
          baskets.selects(only_local, baskets.namespace_of(catalog["only-copy"]))
          and not baskets.selects(only_local, baskets.namespace_of(catalog["pushed"])))

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    for failure in FAILS:
        print(" -", failure)
    raise SystemExit(1)
print("\nALL-OBSERVE-AT-RISK-TESTS-PASS")
