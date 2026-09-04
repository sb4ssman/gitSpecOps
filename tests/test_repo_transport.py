"""Offline tests for the repository-backed manifest transport.

`gh` is faked, so nothing here touches the network or a real repository. What is being
pinned is the concurrency contract — a write must carry the blob sha it read, and a
rejected write must re-read rather than clobber — plus the guards that stop this from
being pointed somewhere unsafe.
"""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "git-sync-suggester"))
sys.path.insert(0, str(ROOT))

import repo_transport  # noqa: E402
from manifest import (branch_id, build_manifest, fleet_id_for,  # noqa: E402
                      repository_id)
from shared.gh_cli import GhError  # noqa: E402

failures = []
SECRET = "ab" * 32
FLEET_ID = fleet_id_for(SECRET)


def check(condition, message):
    if not condition:
        failures.append(message)


def make_manifest(machine_id="laptop", **over):
    repo = {"repo_id": repository_id("example.test", "team", "one", SECRET),
            "branch_id": branch_id("main", SECRET), "has_upstream": True,
            "upstream_observed_at": None,
            "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0, "untracked": 0,
            "stashes": 0, "operation": None}
    repo.update(over)
    return build_manifest(FLEET_ID, machine_id, machine_id.upper(), [repo],
                          observed_at="2026-09-03T12:00:00Z")


class FakeGh:
    """Records every gh invocation and replays scripted responses."""

    def __init__(self, responses):
        self.responses = responses      # list of dicts, GhError instances, or None
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        result = self.responses.pop(0) if self.responses else None
        if isinstance(result, GhError):
            raise result
        return SimpleNamespace(stdout="" if result is None else json.dumps(result),
                               stderr="", returncode=0)

    def fields(self, index):
        """The -f key=value pairs of call `index`, as a dict."""
        args, out = self.calls[index], {}
        for i, token in enumerate(args):
            if token == "-f" and i + 1 < len(args):
                key, _, value = args[i + 1].partition("=")
                out[key] = value
        return out

    def method(self, index):
        args = self.calls[index]
        return args[args.index("--method") + 1] if "--method" in args else "GET"

    def indexes(self, method):
        """Call indexes issued with the given HTTP method."""
        return [i for i in range(len(self.calls)) if self.method(i) == method]


def install(responses):
    fake = FakeGh(responses)
    repo_transport.run_gh = fake
    return fake


original_run_gh = repo_transport.run_gh

def encoded(payload: bytes, sha="blobsha1"):
    return {"content": base64.b64encode(payload).decode("ascii"), "sha": sha, "type": "file"}


try:
    # --- spec validation -------------------------------------------------------------
    for bad in ("", "no-slash", "a//b", "-bad/name", "owner/na me", None, "a/b/c"):
        try:
            repo_transport.RepoTransport(bad)
            failures.append(f"accepted a bad repo spec: {bad!r}")
        except ValueError:
            pass
    check(repo_transport.RepoTransport("sb4ssman/gitSpecOps-state").spec
          == "sb4ssman/gitSpecOps-state", "a valid spec was not kept")

    # --- listing ---------------------------------------------------------------------
    fake = install([[{"name": "b.json", "type": "file"}, {"name": "a.json", "type": "file"},
                     {"name": "notes.txt", "type": "file"}, {"name": "sub", "type": "dir"}]])
    names = repo_transport.RepoTransport("o/r").list_manifests()
    check(names == ["a.json", "b.json"],
          f"listing did not filter to sorted .json files: {names}")

    fake = install([GhError("gh api failed: HTTP 404: Not Found")])
    check(repo_transport.RepoTransport("o/r").list_manifests() == [],
          "a missing repo or folder should list as empty, not raise")

    fake = install([GhError("gh api failed: HTTP 403: Forbidden")])
    try:
        repo_transport.RepoTransport("o/r").list_manifests()
        failures.append("a 403 was swallowed like a 404 — permission errors must surface")
    except GhError:
        pass

    # --- reading ---------------------------------------------------------------------
    manifest = make_manifest()
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    fake = install([encoded(payload)])
    got = repo_transport.RepoTransport("o/r").read_manifest("laptop.json")
    check(got == manifest, "manifest did not survive a base64 round trip")

    for bad_name in ("../escape.json", "sub/laptop.json", "laptop.txt"):
        try:
            install([encoded(payload)])
            repo_transport.RepoTransport("o/r").read_manifest(bad_name)
            failures.append(f"accepted an unsafe manifest name: {bad_name}")
        except ValueError:
            pass

    # --- writing: the concurrency contract -------------------------------------------
    fake = install([encoded(payload, sha="existing-sha"), {"content": {}}])
    where = repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest)
    check(fake.method(1) == "PUT", f"the write was not a PUT: {fake.method(1)}")
    put = fake.fields(1)
    check(put.get("sha") == "existing-sha",
          f"the write did not carry the blob sha it read — that is the concurrency guard: {put}")
    check(base64.b64decode(put["content"]) == payload,
          "the written content is not the manifest that was passed in")
    check("laptop.json" in where, f"unexpected write location: {where}")

    # a file that does not exist yet must be created WITHOUT a sha
    fake = install([GhError("gh api failed: HTTP 404: Not Found"), {"content": {}}])
    repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest)
    check("sha" not in fake.fields(1),
          "a first-time write sent a sha, which would fail against an empty path")

    # a rejected write re-reads and retries once, and never forces
    fake = install([encoded(payload, sha="stale"),
                    GhError("gh api failed: HTTP 409: Conflict"),
                    encoded(payload, sha="fresh"),
                    {"content": {}}])
    repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest)
    puts = fake.indexes("PUT")
    check(len(puts) == 2, f"expected exactly two PUT attempts, got {len(puts)}")
    check(fake.fields(puts[1]).get("sha") == "fresh",
          "the retry did not use the freshly re-read sha")
    check(all("--force" not in " ".join(call) for call in fake.calls),
          "a force-like argument reached gh")

    # a persistently conflicting write gives up rather than clobbering
    fake = install([encoded(payload, sha="a"), GhError("gh api failed: HTTP 409: Conflict"),
                    encoded(payload, sha="b"), GhError("gh api failed: HTTP 409: Conflict")])
    try:
        repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest)
        failures.append("a repeatedly rejected write eventually succeeded — it must give up")
    except GhError:
        pass

    # --- writing: the guards ----------------------------------------------------------
    for bad_id in ("../evil", "has space", "", "a" * 200):
        try:
            install([])
            repo_transport.RepoTransport("o/r").write_own_manifest(bad_id, manifest)
            failures.append(f"accepted an unsafe machine id: {bad_id!r}")
        except ValueError:
            pass

    try:
        install([])
        repo_transport.RepoTransport("o/r").write_own_manifest("desktop", manifest)
        failures.append("wrote a manifest belonging to a different machine")
    except ValueError:
        pass

    # the v2 boundary still applies on the way out
    try:
        install([encoded(payload), {"content": {}}])
        leaky = {**manifest, "repositories": [{**manifest["repositories"][0],
                                               "head": "a" * 40}]}
        repo_transport.RepoTransport("o/r").write_own_manifest("laptop", leaky)
        failures.append("published a record carrying a field outside the v2 boundary")
    except ValueError:
        pass

    # --- compression is opt-in and honest about the filename --------------------------
    fake = install([GhError("gh api failed: HTTP 404: Not Found"), {"content": {}},
                    GhError("gh api failed: HTTP 404: Not Found")])
    where = repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest,
                                                                   compress=True)
    check(where.endswith("laptop.json.gz"),
          f"a compressed manifest must say so in its name: {where}")
    body = base64.b64decode(fake.fields(fake.indexes("PUT")[0])["content"])
    check(body[:2] == b"\x1f\x8b", "the compressed write did not actually send gzip")
    check(len(body) < len(payload), "the compressed write was not smaller")

    # switching compression must delete the counterpart, or one machine reads as two
    fake = install([GhError("gh api failed: HTTP 404: Not Found"), {"content": {}},
                    encoded(payload, sha="old-plain-sha"), {}])
    repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest, compress=True)
    deletes = fake.indexes("DELETE")
    check(len(deletes) == 1, f"the stale uncompressed manifest was not deleted: {fake.calls}")
    check(fake.fields(deletes[0]).get("sha") == "old-plain-sha",
          "the delete did not carry the stale blob's sha")
    check("laptop.json" in fake.calls[deletes[0]][1]
          and not fake.calls[deletes[0]][1].endswith(".gz"),
          f"the wrong path was deleted: {fake.calls[deletes[0]]}")

    # a failure while cleaning up must not fail the publish
    fake = install([GhError("gh api failed: HTTP 404: Not Found"), {"content": {}},
                    GhError("gh api failed: HTTP 500: Server Error")])
    repo_transport.RepoTransport("o/r").write_own_manifest("laptop", manifest, compress=True)

    # both extensions are listed and readable
    fake = install([[{"name": "a.json", "type": "file"}, {"name": "b.json.gz", "type": "file"},
                     {"name": "c.txt", "type": "file"}]])
    check(repo_transport.RepoTransport("o/r").list_manifests() == ["a.json", "b.json.gz"],
          "listing did not include compressed manifests")

    import gzip as _gzip
    fake = install([encoded(_gzip.compress(payload, mtime=0))])
    check(repo_transport.RepoTransport("o/r").read_manifest("laptop.json.gz") == manifest,
          "a gzipped manifest did not round trip")

    # --- doctor -----------------------------------------------------------------------
    fake = install([{"private": False, "permissions": {"push": True}}, []])
    report = repo_transport.RepoTransport("o/r").doctor()
    check(report["exists"] and report["private"] is False, f"doctor misread the repo: {report}")
    check("PUBLIC" in report.get("warning", ""),
          "doctor did not warn that a public repository would expose machine status")

    fake = install([{"private": True, "permissions": {"push": True}}, []])
    report = repo_transport.RepoTransport("o/r").doctor()
    check("warning" not in report, f"a private repo should not warn: {report}")

    fake = install([GhError("gh api failed: HTTP 404: Not Found")])
    check(repo_transport.RepoTransport("o/r").doctor().get("exists") is False,
          "doctor did not report a missing repository as absent")

    # --- creation is explicit ----------------------------------------------------------
    fake = install([{}])
    repo_transport.create_state_repo("o/gitSpecOps-state")
    created = fake.calls[0]
    check(created[:2] == ["repo", "create"] and "--private" in created,
          f"the state repo was not created private: {created}")
    for bad in ("nope", "", "a/b/c"):
        try:
            repo_transport.create_state_repo(bad)
            failures.append(f"create accepted a bad spec: {bad!r}")
        except ValueError:
            pass
finally:
    repo_transport.run_gh = original_run_gh

if failures:
    print("REPO-TRANSPORT-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-REPO-TRANSPORT-TESTS-PASS")
