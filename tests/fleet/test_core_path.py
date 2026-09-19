"""The core promise, pinned against the defects that broke it.

Every machine must show which repositories hold uncommitted work and which are behind their
remote -- without permanent false alarms, without spending the GitHub API budget, without
reporting an unreadable repository as clean, and without failing silently.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
import fleet_peer
from fleet_config import new_config
from fleet_events import NativeEvents
from fleet_observer import IncrementalObserver
from local_view import display_from_manifests
from manifest import build_manifest, fleet_id_for
from observer import fetch_repositories, observe_paths

SECRET = "66" * 32
FLEET = fleet_id_for(SECRET)
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false"]
NAMES = {"a" * 32: {"host": "github.com", "owner": "example", "name": "work"}}


def git(cwd, *args):
    result = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout


def stamp(seconds_ago):
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(**overrides):
    base = {"repo_id": "a" * 32, "branch_id": "c" * 16, "has_upstream": True,
            "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0,
            "unstaged": 0, "untracked": 0, "stashes": 0, "operation": None}
    base.update(overrides)
    return base


def fake_observer():
    observer = Mock()
    observer.inventory.return_value = 0
    report = {"manifest": build_manifest(FLEET, "machine-a", "A", []), "names": {}, "issues": []}
    observer.report.return_value = report
    observer.shared_report.return_value = (report, set())
    observer.excluded_from_observation = 0
    return observer


def run_with(config, root, stopping, source, observer, log=lambda *_: None):
    with patch("fleet_peer.IncrementalObserver", return_value=observer), \
            patch("fleet_peer.TransportPublisher") as publisher, \
            patch("fleet_peer.PeerNetwork"), \
            patch("local_dashboard.make_local_server"), \
            patch("fleet_peer.threading.Thread"):
        publisher.return_value.publish.return_value = []
        publisher.return_value.flush.return_value = []
        fleet_peer.run_peer(config, root, stopping, event_source=source, log=log)
    return publisher


def test_a_quiet_machine_is_not_a_false_alarm():
    """Was: stale two minutes after the last edit, so every repository needed attention."""
    with tempfile.TemporaryDirectory() as temp:
        folder = new_config("m", "M", [temp], SECRET,
                            transports={"folder": {"path": temp, "seconds": 300}})
        alone = new_config("m", "M", [temp], SECRET)
    assert fleet_peer.stale_after(alone) == 120
    assert fleet_peer.stale_after(folder) > 600, "a 5-minute folder is not stale at minute 7"

    quiet = build_manifest(FLEET, "m", "M", [record()], observed_at=stamp(400))
    view = display_from_manifests([quiet], fleet_id=FLEET, names=NAMES,
                                  stale_seconds=fleet_peer.stale_after(folder))
    assert view["machines"][0]["freshness"] == "current"
    assert view["summary"]["attention"] == 0, "a clean, quiet machine needs no attention"

    gone = build_manifest(FLEET, "m", "M", [record(unstaged=2)], observed_at=stamp(3600))
    view = display_from_manifests([gone], fleet_id=FLEET, names=NAMES,
                                  stale_seconds=fleet_peer.stale_after(folder))
    assert view["machines"][0]["freshness"] != "current"
    assert view["summary"]["attention"] == 1, "a silent machine's last-known dirty work stays"


def test_a_running_peer_heartbeats_without_rescanning():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = new_config("machine-a", "A", [root], SECRET)
        config["heartbeat"] = 1
        stopping, calls = threading.Event(), {"count": 0}

        class Source:
            def wait(self, **_):
                calls["count"] += 1
                if calls["count"] == 1:
                    time.sleep(1.2)
                else:
                    stopping.set()
                return set()

            def close(self):
                pass

        observer = fake_observer()
        publisher = run_with(config, root, stopping, Source(), observer)
    assert observer.report.call_count == 2, "initial report plus one heartbeat"
    assert publisher.return_value.publish.call_args_list[1].args[1] is False, \
        "a heartbeat carries unchanged state"
    observer.inventory.assert_called_once()
    observer.refresh.assert_not_called()


def test_dashboard_refreshes_share_one_transport_read():
    """Was: every tray poll and browser refresh read GitHub, most of the hourly API budget."""
    clock = [0.0]
    transport = Mock()
    transport.list_manifests.return_value = []
    publisher = fleet_peer.TransportPublisher({}, clock=lambda: clock[0])
    publisher.entries = [{"name": "repo", "transport": transport, "seconds": 1800, "next": 0.0}]
    for _ in range(60):
        publisher.read_all()
    assert transport.list_manifests.call_count == 1
    clock[0] = fleet_peer.READ_SECONDS["repo"]
    publisher.read_all()
    assert transport.list_manifests.call_count == 2
    transport.list_manifests.side_effect = OSError("rate limited")
    clock[0] += fleet_peer.READ_SECONDS["repo"]
    _manifests, issues = publisher.read_all()
    assert issues and "unreadable" in issues[0]
    transport.list_manifests.side_effect = None
    clock[0] += fleet_peer.READ_RETRY_SECONDS
    publisher.read_all()
    assert transport.list_manifests.call_count == 4, "a failed read retries soon"


def test_unreadable_status_is_never_reported_clean():
    """Was: a failing `git status` returned zero changes, so hidden work showed as clean."""
    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp) / "work"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "remote", "add", "origin", "https://github.com/example/work.git")
        (repo / "f.txt").write_text("one\n")
        git(repo, "add", "f.txt")
        git(repo, "commit", "-qm", "base")
        (repo / "f.txt").write_text("uncommitted\n")
        observer = IncrementalObserver(new_config("machine-a", "A", [temp], SECRET))
        assert observer.inventory() == 1
        assert observer.report()["manifest"]["repositories"][0]["unstaged"] == 1

        (repo / ".git" / "index").write_bytes(b"damaged")
        observation = observe_paths([repo], SECRET)
        assert observation.repositories == [], "no guessed counts"
        assert any("status unreadable" in issue for issue in observation.issues)

        observer.refresh({repo / "f.txt"})
        report = observer.report()
        assert report["manifest"]["repositories"][0]["unstaged"] == 1, "last known dirty kept"
        assert any("status unreadable" in issue for issue in report["issues"])


def test_scheduled_fetch_reveals_a_repository_that_is_behind():
    """Was: nothing ever fetched, so 'behind' reflected the last manual fetch."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        remote = root / "remote.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(remote))
        library = root / "library"
        library.mkdir()
        work = library / "work"
        git(root, "clone", "-q", str(remote), str(work))
        (work / "f.txt").write_text("one\n")
        git(work, "add", "f.txt")
        git(work, "commit", "-qm", "base")
        git(work, "push", "-q", "-u", "origin", "main")
        other = root / "other"
        git(root, "clone", "-q", str(remote), str(other))
        (other / "g.txt").write_text("new\n")
        git(other, "add", "g.txt")
        git(other, "commit", "-qm", "moved on")
        git(other, "push", "-q", "origin", "main")
        # Observation names repositories by their origin; the fetch below goes to the local remote.
        git(work, "remote", "set-url", "origin", "https://github.com/example/work.git")

        observer = IncrementalObserver(new_config("machine-a", "A", [library], SECRET))
        observer.inventory()
        before = observer.report()["manifest"]["repositories"][0]
        assert before["behind"] == 0 and before["upstream_observed_at"] is None

        def local_fetch(path, _timeout):
            result = subprocess.run(["git", "-C", str(path), "fetch", "-q", str(remote),
                                     "+refs/heads/*:refs/remotes/origin/*"],
                                    capture_output=True, text=True, check=False)
            return None if result.returncode == 0 else result.stderr

        paths = list(observer.paths)
        fetched, problems = fetch_repositories(paths, fetcher=local_fetch)
        assert not problems and len(fetched) == 1, problems
        observer.apply_fetch(fetched, problems, paths)
        after = observer.report()["manifest"]["repositories"][0]
        assert after["behind"] == 1, after
        assert after["upstream_observed_at"]

        (work / "f.txt").write_text("edit\n")
        observer.refresh({work / "f.txt"})
        kept = observer.report()["manifest"]["repositories"][0]["upstream_observed_at"]
        assert kept == after["upstream_observed_at"], "an ordinary edit does not un-check the remote"

        _fetched, failures = fetch_repositories(paths, fetcher=lambda *_: "authentication failed")
        observer.apply_fetch({}, failures, paths)
        assert any("fetch failed" in issue for issue in observer.report()["issues"])


def test_background_fetch_never_prompts_for_credentials():
    import observer as observer_module

    seen = {}

    def fake_run_git(_path, args, timeout=None, env=None):
        seen["args"], seen["env"] = list(args), dict(env or {})
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(observer_module, "run_git", fake_run_git):
        assert observer_module._fetch(Path("."), 5) is None
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert seen["env"]["GCM_INTERACTIVE"] == "never"
    assert "credential.interactive=never" in seen["args"]


def test_dashboard_tells_the_truth_about_remotes_and_settings():
    settings = {"fetch_seconds": 900,
                "transport_config": {"folder": {"path": "x", "seconds": 300},
                                     "repo": {"name": "someone/state", "seconds": 1800}}}
    checked = build_manifest(FLEET, "m", "M", [record(upstream_observed_at=stamp(60))])
    view = display_from_manifests([checked], fleet_id=FLEET, names=NAMES, settings=settings)
    assert view["rows"][0]["advice"] == "✓ up to date with the remote"
    integrations = {item["id"]: item for item in view["integrations"]}
    assert integrations["synced_folder"]["enabled"] and integrations["github"]["enabled"]
    assert not integrations["tailscale"]["enabled"], "was always reported on"

    unchecked = build_manifest(FLEET, "m", "M", [record()])
    view = display_from_manifests([unchecked], fleet_id=FLEET, names=NAMES, settings=settings)
    assert "unverified" in view["rows"][0]["advice"]

    behind = build_manifest(FLEET, "m", "M", [record(behind=3, upstream_observed_at=stamp(60))])
    view = display_from_manifests([behind], fleet_id=FLEET, names=NAMES, settings=settings)
    assert view["summary"]["attention"] == 1 and "PULL" in view["rows"][0]["advice"]


def test_packaged_app_opens_the_local_dashboard_without_tailscale():
    """Was: built a Tailscale host URL from retired keys and never opened anything."""
    import fleet_desktop

    with patch("fleet_net.local_identity", side_effect=AssertionError("must not need Tailscale")):
        assert fleet_desktop.dashboard_url({"mode": "peer", "local_port": 8761}) == \
            "http://127.0.0.1:8761/"


def test_dropped_filesystem_events_are_noticed():
    class Backend:
        def __init__(self):
            self.flag = True

        def wait(self, _timeout):
            return set()

        def take_overflow(self):
            flag, self.flag = self.flag, False
            return flag

        def close(self):
            pass

    events = NativeEvents([], backend=Backend())
    assert fleet_peer._overflowed(events) is True
    assert fleet_peer._overflowed(events) is False, "reported once"
    assert fleet_peer._overflowed(Mock()) is False, "a double without the method is no overflow"


def test_a_stopped_filesystem_watch_restarts_with_a_fresh_inventory():
    """Was: a failed Windows watch thread exited silently and nothing was observed again."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = new_config("machine-a", "A", [root], SECRET)
        stopping, calls, messages = threading.Event(), {"count": 0}, []

        class Source:
            def wait(self, **_):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise OSError("drive went away")
                stopping.set()
                return set()

            def close(self):
                pass

        observer = fake_observer()
        with patch.object(fleet_peer, "WATCH_RESTART_SECONDS", 0):
            run_with(config, root, stopping, Source(), observer, log=messages.append)
    assert observer.inventory.call_count == 2, "changes made while unwatched are re-read"
    assert any("Filesystem watching stopped" in message for message in messages)


def test_tray_log_keeps_the_reason_a_start_failed():
    import fleet_tray

    with tempfile.TemporaryDirectory() as temp:
        log = Path(temp) / "fleet.log"
        tee = fleet_tray._LogTee(log, None)
        print("Dashboard: http://127.0.0.1:8760/", file=tee)
        print("error: no saved configuration; run 'fleet setup' first", file=tee)
        tee.close()
        assert tee.last_error.startswith("no saved configuration")
        assert "error: no saved configuration" in log.read_text(encoding="utf-8")


def main():
    test_a_quiet_machine_is_not_a_false_alarm()
    test_a_running_peer_heartbeats_without_rescanning()
    test_dashboard_refreshes_share_one_transport_read()
    test_unreadable_status_is_never_reported_clean()
    test_scheduled_fetch_reveals_a_repository_that_is_behind()
    test_background_fetch_never_prompts_for_credentials()
    test_dashboard_tells_the_truth_about_remotes_and_settings()
    test_packaged_app_opens_the_local_dashboard_without_tailscale()
    test_dropped_filesystem_events_are_noticed()
    test_a_stopped_filesystem_watch_restarts_with_a_fresh_inventory()
    test_tray_log_keeps_the_reason_a_start_failed()
    print("ALL-CORE-PATH-TESTS-PASS")


if __name__ == "__main__":
    main()
