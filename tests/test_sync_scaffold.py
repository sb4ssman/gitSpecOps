"""Synthetic, offline contract tests for the Sync Suggester scaffold."""

import sys
import subprocess
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "git-sync-suggester"
sys.path.insert(0, str(TOOL_DIR))

from advice import classify_repository, render_table  # noqa: E402
from folder_transport import FolderTransport  # noqa: E402
from manifest import build_manifest, decode_manifest, encode_manifest, repository_id  # noqa: E402
from observer import RootSpec, observe_roots  # noqa: E402

REPO_ID = repository_id("example.test", "sample-team", "alpha-repo")
BASE = {
    "repo_id": REPO_ID,
    "branch": "main",
    "head": "a" * 40,
    "upstream": "origin/main",
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

if REPO_ID != repository_id("EXAMPLE.TEST", "SAMPLE-TEAM", "ALPHA-REPO"):
    failures.append("repository identity is not case-insensitive")

manifest = build_manifest("machine-a", "workstation-a", [dict(BASE)], "2026-01-02T03:04:05Z")
payload = encode_manifest(manifest)
if decode_manifest(payload) != manifest:
    failures.append("manifest encode/decode round trip failed")
for forbidden in (b"alpha-repo", b"sample-team", b"example.test", b"/synthetic/path"):
    if forbidden in payload:
        failures.append(f"manifest leaked: {forbidden!r}")

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
    observation = observe_roots([RootSpec(collection)])
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
    ({"upstream": None, "ahead": None, "behind": None}, "unknown"),
]
for changes, expected in CASES:
    repo = dict(BASE)
    repo.update(changes)
    actual, _ = classify_repository(repo)
    if actual != expected:
        failures.append(f"classification {changes}: {actual}, expected {expected}")

table = render_table(manifest, {REPO_ID: {"display_name": "alpha-repo", "path": "/local-only"}})
if "alpha-repo" not in table or "/local-only" in table:
    failures.append("local display-name table did not preserve the privacy boundary")

if failures:
    print("SYNC-SCAFFOLD-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print(f"ALL-SYNC-SCAFFOLD-TESTS-PASS ({len(CASES)} advice cases)")
