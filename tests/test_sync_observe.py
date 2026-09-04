"""Synthetic, offline tests for observation: in-progress operations and the opt-in fetch.

Real git repositories are created in a temporary directory, but nothing here reaches the
network. The fetch boundary is injected (`observe_roots(..., fetcher=...)`), so success and
failure are both exercised without a single connection — a real fetch of an `example.test`
remote would still perform a DNS lookup, which is exactly the kind of quiet network access an
offline suite should not have.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "git-sync-suggester"))

from observer import RootSpec, _in_progress_operation, observe_roots  # noqa: E402

failures = []
SECRET = "ab" * 32


def check(condition, message):
    if not condition:
        failures.append(message)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def make_repo(parent: Path, name: str, origin: str) -> Path:
    repo = parent / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    git(repo, "config", "user.email", "test@example.test")
    git(repo, "config", "user.name", "Test")
    git(repo, "remote", "add", "origin", origin)
    (repo / "file.txt").write_text("content\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "initial")
    return repo


with tempfile.TemporaryDirectory(prefix="sync-observe-") as tmp:
    tmp = Path(tmp)
    collection = tmp / "collection"
    repo = make_repo(collection, "alpha-repo", "https://example.test/sample-team/alpha-repo.git")

    # --- in-progress operations -----------------------------------------------------
    check(_in_progress_operation(repo) is None,
          "a quiet repository was reported as mid-operation")

    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip())
    for marker, expected, is_dir in [
        ("MERGE_HEAD", "merge", False),
        ("CHERRY_PICK_HEAD", "cherry-pick", False),
        ("REVERT_HEAD", "revert", False),
        ("BISECT_LOG", "bisect", False),
        ("rebase-merge", "rebase", True),
        ("rebase-apply", "rebase", True),
    ]:
        target = git_dir / marker
        if is_dir:
            target.mkdir()
        else:
            target.write_text("0" * 40 + "\n", encoding="utf-8")
        check(_in_progress_operation(repo) == expected,
              f"{marker} should report '{expected}', got {_in_progress_operation(repo)!r}")
        if is_dir:
            target.rmdir()
        else:
            target.unlink()
    check(_in_progress_operation(repo) is None,
          "the repository did not return to quiet after the markers were removed")

    # An in-progress operation must reach the manifest, since nothing set it before.
    (git_dir / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
    observation = observe_roots([RootSpec(collection)], SECRET)
    check(len(observation.repositories) == 1,
          f"unexpected repositories: {observation.repositories}")
    check(observation.repositories[0]["operation"] == "merge",
          f"operation did not reach the record: {observation.repositories[0]['operation']}")
    (git_dir / "MERGE_HEAD").unlink()

    # --- fetch is opt-in ------------------------------------------------------------
    quiet = observe_roots([RootSpec(collection)], SECRET)
    check(quiet.repositories[0]["upstream_observed_at"] is None,
          "upstream_observed_at was stamped without --fetch")
    check(not quiet.issues, f"a no-fetch observation reported issues: {quiet.issues}")

    # --- an unparseable origin is skipped, with a reason ----------------------------
    make_repo(collection, "odd-remote", "/some/local/path/not/a/url")
    odd = observe_roots([RootSpec(collection)], SECRET)
    check(any("unrecognized origin" in issue for issue in odd.issues),
          f"a repository with an unusable origin was not reported: {odd.issues}")
    check(len(odd.repositories) == 1,
          "a repository with an unusable origin should be skipped, not guessed at")

    # --- fetch success and failure, with the network boundary stubbed ---------------
    make_repo(collection, "beta-repo", "https://example.test/sample-team/beta-repo.git")
    attempted = []

    def stub_fetch(path, timeout):
        attempted.append(path.name)
        return None if path.name == "alpha-repo" else "fatal: could not read from remote"

    fetched = observe_roots([RootSpec(collection)], SECRET, fetch=True, fetcher=stub_fetch)
    names = {repo_id: entry["name"] for repo_id, entry in fetched.catalog.items()}
    stamps = {names[r["repo_id"]]: r["upstream_observed_at"] for r in fetched.repositories}

    check(sorted(attempted) == ["alpha-repo", "beta-repo", "odd-remote"],
          f"fetch was not attempted for every discovered repository: {sorted(attempted)}")
    check(len(fetched.repositories) == 2,
          f"a failed fetch lost a repository: {len(fetched.repositories)}")
    check(stamps.get("alpha-repo") is not None,
          "a successful fetch did not stamp upstream_observed_at")
    check(str(stamps.get("alpha-repo")).endswith("Z"),
          f"the stamp is not in the manifest's UTC form: {stamps.get('alpha-repo')!r}")
    check(stamps.get("beta-repo") is None,
          "a repository whose fetch failed must not claim fresh remote knowledge")
    check(any("fetch failed" in issue and "beta-repo" in issue for issue in fetched.issues),
          f"the fetch failure was not reported: {fetched.issues}")

    # A fetch that raises must not take the whole observation down with it.
    def exploding_fetch(path, timeout):
        raise RuntimeError("network stack on fire")

    survived = observe_roots([RootSpec(collection)], SECRET, fetch=True,
                             fetcher=exploding_fetch)
    check(len(survived.repositories) == 2,
          "a raising fetcher took the whole observation down; failures must be collected")
    check(all(r["upstream_observed_at"] is None for r in survived.repositories),
          "a repository was stamped despite the fetch raising")
    check(any("network stack on fire" in issue for issue in survived.issues),
          f"the raised failure was not reported: {survived.issues}")

    attempted.clear()
    observe_roots([RootSpec(collection)], SECRET, fetch=False, fetcher=stub_fetch)
    check(attempted == [], f"fetch ran without being asked for: {attempted}")

    # --- progress is reported --------------------------------------------------------
    seen = []
    observe_roots([RootSpec(collection)], SECRET,
                  progress=lambda done, total, path: seen.append((done, total)))
    check(seen and seen[-1][0] == seen[-1][1] == 3,
          f"progress callback did not run to completion: {seen}")

if failures:
    print("SYNC-OBSERVE-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-SYNC-OBSERVE-TESTS-PASS")
