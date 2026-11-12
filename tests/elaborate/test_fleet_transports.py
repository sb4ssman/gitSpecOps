"""Fleet-enabling features end to end: two machines really exchange status over each transport.

- Synced folder: two peers, each with its own library, publish into one shared folder; each
  then reads both machines, and the shared repository links them on the network map.
- Private GitHub state repository: the same exchange through a fake `gh` that stores files the
  way the Contents API does (no network, no account).
- Tailnet: one peer answers on loopback; the other pulls its report.
Everything runs in temporary folders with invented repositories.
"""
import base64
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import Elaborate._transport.repo as repo_transport  # noqa: E402
from Basic._providers.github import GhError  # noqa: E402
from Elaborate._fleet.local_view import display_from_manifests  # noqa: E402
from Elaborate._fleet.net import fetch_peer_report, make_peer_server  # noqa: E402
from Elaborate._fleet.peer import TransportPublisher, run_peer  # noqa: E402
from Special._sync.enrollment import new_config  # noqa: E402
from Special._sync.manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "44" * 32
FLEET = fleet_id_for(SECRET)
ENV = {"GIT_AUTHOR_NAME": "Example", "GIT_AUTHOR_EMAIL": "e@example.invalid",
       "GIT_COMMITTER_NAME": "Example", "GIT_COMMITTER_EMAIL": "e@example.invalid"}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def git(*args):
    import os
    subprocess.run(["git", *args], check=True, capture_output=True, env={**os.environ, **ENV})


def library(root: Path, names) -> Path:
    for name in names:
        repo = root / name
        git("init", "-q", "-b", "main", str(repo))
        (repo / "f.txt").write_text(name + "\n")
        git("-C", str(repo), "add", "f.txt")
        git("-C", str(repo), "commit", "-qm", "first")
        git("-C", str(repo), "remote", "add", "origin", f"https://github.com/example/{name}.git")
    return root


def run_once(config, state: Path):
    state.mkdir(parents=True, exist_ok=True)
    return run_peer(config, state, threading.Event(), once=True, log=lambda *_: None)


def machines_seen(transports) -> set:
    manifests, issues = TransportPublisher(transports).read_all()
    check(not issues, issues)
    return {manifest["machine_id"] for manifest in manifests}, manifests


def test_two_machines_share_status_through_a_synced_folder():
    with tempfile.TemporaryDirectory(prefix="fleet-folder-") as temp:
        tmp = Path(temp)
        shared = tmp / "synced"
        shared.mkdir()
        transports = {"folder": {"path": str(shared), "seconds": 1}}
        a = new_config("machine-a", "A", [library(tmp / "lib-a", ["shared", "only-a"])], SECRET,
                       transports=transports)
        b = new_config("machine-b", "B", [library(tmp / "lib-b", ["shared"])], SECRET,
                       transports=transports)
        check(run_once(a, tmp / "state-a") == 0, "machine A's peer failed")
        check(run_once(b, tmp / "state-b") == 0, "machine B's peer failed")
        seen, manifests = machines_seen(transports)
        check(seen == {"machine-a", "machine-b"}, f"each machine must see both: {seen}")
        document = display_from_manifests(manifests, fleet_id=FLEET)
        links = document["map"]["links"]
        check(len(links) == 1 and links[0]["shared"] == 1, f"the shared repository links them: {links}")


class FakeGitHub:
    """The Contents API's behavior for one private repository, held in memory."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.private = True

    def __call__(self, args, **_):
        endpoint, method = args[1], args[args.index("--method") + 1]
        fields = dict(value.split("=", 1) for flag, value in zip(args, args[1:]) if flag == "-f")
        path = endpoint.split("/contents/", 1)[1] if "/contents/" in endpoint else ""

        class Done:
            stdout = ""

        done = Done()
        if method == "GET" and "/contents/" not in endpoint:
            # The repository itself: the transport checks it is private and writable first.
            done.stdout = json.dumps({"private": self.private, "permissions": {"push": True}})
        elif method == "GET":
            if path in self.files:
                payload = {"content": base64.b64encode(self.files[path]).decode(), "type": "file",
                           "sha": f"sha-{path}-{len(self.files[path])}"}
            else:
                listing = [{"name": key.rsplit("/", 1)[1], "type": "file"} for key in self.files
                           if key.rsplit("/", 1)[0] == path]
                if not listing:
                    raise GhError("HTTP 404: Not Found")
                payload = listing
            done.stdout = json.dumps(payload)
        elif method == "PUT":
            self.files[path] = base64.b64decode(fields["content"])
            done.stdout = json.dumps({"content": {"path": path}})
        elif method == "DELETE":
            self.files.pop(path, None)
        return done


def test_two_machines_share_status_through_a_private_state_repository():
    fake, original = FakeGitHub(), repo_transport.run_gh
    repo_transport.run_gh = fake
    try:
        with tempfile.TemporaryDirectory(prefix="fleet-repo-") as temp:
            tmp = Path(temp)
            transports = {"repo": {"name": "example-owner/fleet-state", "seconds": 1}}
            a = new_config("machine-a", "A", [library(tmp / "lib-a", ["shared"])], SECRET,
                           transports=transports)
            b = new_config("machine-b", "B", [library(tmp / "lib-b", ["shared"])], SECRET,
                           transports=transports)
            run_once(a, tmp / "state-a")
            run_once(b, tmp / "state-b")
            check(any(path.endswith("machine-a.json") or path.endswith("machine-a.json.gz")
                      for path in fake.files), f"machine A's status file was not written: {list(fake.files)}")
            seen, _manifests = machines_seen(transports)
            check(seen == {"machine-a", "machine-b"}, f"both machines read from the repository: {seen}")
    finally:
        repo_transport.run_gh = original


def test_a_state_repository_made_public_receives_nothing():
    fake, original = FakeGitHub(), repo_transport.run_gh
    fake.private = False
    repo_transport.run_gh = fake
    try:
        with tempfile.TemporaryDirectory(prefix="fleet-public-") as temp:
            tmp = Path(temp)
            config = new_config("machine-a", "A", [library(tmp / "lib-a", ["shared"])], SECRET,
                                transports={"repo": {"name": "example-owner/fleet-state", "seconds": 1}})
            run_once(config, tmp / "state-a")
            check(fake.files == {}, f"status must never go to a public repository: {list(fake.files)}")
    finally:
        repo_transport.run_gh = original


def test_one_machine_pulls_another_over_the_tailnet():
    report = {"manifest": build_manifest(FLEET, "machine-a", "A", []), "names": {}, "issues": []}
    server = make_peer_server(("127.0.0.1", 0), lambda: report, SECRET, "me@example.invalid",
                              authenticate=lambda ip: {"machine_id": "ts-b", "label": "B"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import Elaborate._fleet.net as net

    original = net.validate_server_url
    try:
        port = server.server_address[1]
        check(fetch_peer_report("127.0.0.1", port) is None,
              "safeguard: a peer outside the Tailscale range (100.64.0.0/10) is never contacted")
        # Inside this test only, let the client reach the loopback stand-in for a tailnet peer.
        net.validate_server_url = lambda url: url
        pulled = fetch_peer_report("127.0.0.1", port)
        check(pulled is not None and pulled["manifest"]["machine_id"] == "machine-a",
              f"the other machine's report must arrive: {pulled}")
    finally:
        net.validate_server_url = original
        server.shutdown()
        server.server_close()


def test_every_transport_at_once_counts_each_machine_once():
    fake, original = FakeGitHub(), repo_transport.run_gh
    repo_transport.run_gh = fake
    try:
        with tempfile.TemporaryDirectory(prefix="fleet-all-") as temp:
            tmp = Path(temp)
            shared = tmp / "synced"
            shared.mkdir()
            transports = {"folder": {"path": str(shared), "seconds": 1},
                          "repo": {"name": "example-owner/fleet-state", "seconds": 1}}
            a = new_config("machine-a", "A", [library(tmp / "lib-a", ["shared"])], SECRET,
                           transports=transports)
            run_once(a, tmp / "state-a")
            _seen, manifests = machines_seen(transports)
            document = display_from_manifests(manifests, fleet_id=FLEET)
            check(len(document["machines"]) == 1, "one machine on two transports is one machine")
    finally:
        repo_transport.run_gh = original


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL-FLEET-TRANSPORT-TESTS-PASS ({len(tests)} checks)")


if __name__ == "__main__":
    main()
