"""Synthetic, offline contract tests for the Sync Suggester scaffold."""

import sys
import subprocess
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "git-sync-suggester"
sys.path.insert(0, str(TOOL_DIR))

from advice import classify_repository, render_table  # noqa: E402
from folder_transport import FolderTransport  # noqa: E402
from manifest import (branch_id, build_manifest, decode_manifest,  # noqa: E402
                      encode_manifest, fleet_id_for, is_fleet_secret, new_fleet_secret,
                      repository_id)
from observer import RootSpec, observe_roots  # noqa: E402

SECRET = "ab" * 32
FLEET_ID = fleet_id_for(SECRET)
REPO_ID = repository_id("example.test", "sample-team", "alpha-repo", SECRET)
BRANCH = "feature/private-plans"
BRANCH_ID = branch_id(BRANCH, SECRET)
BASE = {
    "repo_id": REPO_ID,
    "branch_id": BRANCH_ID,
    "has_upstream": True,
    "upstream_observed_at": None,
    "ahead": 0,
    "behind": 0,
    "staged": 0,
    "unstaged": 0,
    "untracked": 0,
    "stashes": 0,
    "operation": None,
}

failures = []

if REPO_ID != repository_id("EXAMPLE.TEST", "SAMPLE-TEAM", "ALPHA-REPO", SECRET):
    failures.append("repository identity is not case-insensitive")

# --- v2: the identity must actually depend on the fleet secret ----------------------
other = repository_id("example.test", "sample-team", "alpha-repo", "cd" * 32)
if other == REPO_ID:
    failures.append("a different fleet secret produced the same repository identity")
unsalted = repository_id("example.test", "sample-team", "alpha-repo")
if unsalted == REPO_ID:
    failures.append("the salted identity matches the unsalted one — the secret is being ignored")
from manifest import BRANCH_ID_HEX, REPO_ID_HEX  # noqa: E402
if len(REPO_ID) != REPO_ID_HEX or int(REPO_ID, 16) < 0:
    failures.append(f"salted identity is not a {REPO_ID_HEX}-character hex digest")
if len(BRANCH_ID) != BRANCH_ID_HEX:
    failures.append(f"branch identity is not a {BRANCH_ID_HEX}-character hex digest")

if fleet_id_for(SECRET) != FLEET_ID or fleet_id_for("cd" * 32) == FLEET_ID:
    failures.append("fleet id is not a stable, secret-dependent label")
if SECRET in FLEET_ID or FLEET_ID in SECRET:
    failures.append("the public fleet id exposes part of the secret")

for bad in (None, "", "xyz", "ab" * 31, "zz" * 32, 12345):
    if is_fleet_secret(bad):
        failures.append(f"is_fleet_secret accepted {bad!r}")
# None is the documented "no fleet, local preview only" value and must stay allowed;
# anything else malformed must raise rather than silently produce a weak identity.
for bad in ("", "xyz", "ab" * 31, "zz" * 32, 12345):
    try:
        repository_id("h", "o", "n", bad)
    except ValueError:
        pass
    else:
        failures.append(f"repository_id accepted the malformed secret {bad!r}")

generated = new_fleet_secret()
if not is_fleet_secret(generated) or generated == new_fleet_secret():
    failures.append("new_fleet_secret is not producing fresh, valid secrets")

manifest = build_manifest(FLEET_ID, "machine-a", "workstation-a", [dict(BASE)],
                          "2026-01-02T03:04:05Z")
payload = encode_manifest(manifest)
if decode_manifest(payload) != manifest:
    failures.append("manifest encode/decode round trip failed")
for forbidden in (b"alpha-repo", b"sample-team", b"example.test", b"/synthetic/path"):
    if forbidden in payload:
        failures.append(f"manifest leaked: {forbidden!r}")
# The secret must never ride along with the data it protects.
if SECRET.encode() in payload:
    failures.append("the fleet secret leaked into a published manifest")
# v2 dropped the commit SHA: it identified public repositories and nothing read it.
if b'"head"' in payload:
    failures.append("the manifest still publishes a commit SHA")
# v3: a human-authored branch name must never appear either.
if BRANCH.encode() in payload or b'"branch"' in payload or b'"upstream"' in payload:
    failures.append("the manifest still publishes a readable branch or upstream name")
if branch_id(BRANCH, "cd" * 32) == BRANCH_ID:
    failures.append("branch_id does not depend on the fleet secret")
if branch_id(None, SECRET) is not None:
    failures.append("a detached HEAD should produce no branch id")

stale = {**manifest, "schema_version": 1}
try:
    encode_manifest(stale)
except ValueError as exc:
    if "re-run" not in str(exc):
        failures.append(f"a v1 manifest was rejected without actionable guidance: {exc}")
else:
    failures.append("a v1 manifest was accepted by the v2 validator")

try:
    encode_manifest({**manifest, "repositories": [{**BASE, "head": "a" * 40}]})
except ValueError:
    pass
else:
    failures.append("a repository record carrying head was accepted")

leaky = dict(manifest)
leaky["local_path"] = "/synthetic/path"
try:
    encode_manifest(leaky)
except ValueError:
    pass
else:
    failures.append("top-level local_path was accepted")

with tempfile.TemporaryDirectory(prefix="folder-transport-test-") as temp:
    transport = FolderTransport(temp)
    destination = transport.write_own_manifest("machine-a", manifest)
    if destination.name != "machine-a.json":
        failures.append(f"unexpected destination: {destination}")
    if transport.list_manifests() != ["machine-a.json"]:
        failures.append(f"manifest listing failed: {transport.list_manifests()}")
    if transport.read_manifest("machine-a.json") != manifest:
        failures.append("folder transport read failed")

with tempfile.TemporaryDirectory(prefix="observer-test-") as temp:
    collection = Path(temp) / "collection"
    repo_path = collection / "alpha-repo"
    repo_path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(repo_path)], check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "remote", "add", "origin",
         "https://example.test/sample-team/alpha-repo.git"],
        check=True,
    )
    (repo_path / "draft.txt").write_text("synthetic\n", encoding="utf-8")
    observation = observe_roots([RootSpec(collection)], SECRET)
    if len(observation.repositories) != 1:
        failures.append(f"observer repositories: {observation.repositories}")
    elif observation.repositories[0]["untracked"] != 1:
        failures.append(f"observer untracked count: {observation.repositories[0]}")
    if observation.catalog.get(REPO_ID, {}).get("display_name") != "alpha-repo":
        failures.append(f"observer local catalog: {observation.catalog}")

CASES = [
    ({}, "synced"),
    ({"unstaged": 1}, "dirty"),
    ({"stashes": 1}, "stashed"),
    ({"operation": "rebase"}, "operation"),
    ({"ahead": 2}, "ahead"),
    ({"behind": 3}, "behind"),
    ({"ahead": 1, "behind": 1}, "diverged"),
    ({"has_upstream": False, "ahead": None, "behind": None}, "unknown"),
]
for changes, expected in CASES:
    repo = dict(BASE)
    repo.update(changes)
    actual, _ = classify_repository(repo)
    if actual != expected:
        failures.append(f"classification {changes}: {actual}, expected {expected}")

table = render_table(manifest, {REPO_ID: {"display_name": "alpha-repo", "path": "/local-only"}},
                     {BRANCH_ID: BRANCH})
if "alpha-repo" not in table or "/local-only" in table:
    failures.append("local display-name table did not preserve the privacy boundary")
if BRANCH not in table:
    failures.append("a locally known branch name was not resolved for display")
unknown_branch = render_table(manifest, {}, {})
if BRANCH in unknown_branch or f"branch:{BRANCH_ID[:8]}" not in unknown_branch:
    failures.append("a branch this machine has never seen should show as an opaque id")

if failures:
    print("SYNC-SCAFFOLD-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print(f"ALL-SYNC-SCAFFOLD-TESTS-PASS ({len(CASES)} advice cases, v2 schema)")
