"""Desktop handoff stays local, explicit, and separate from remote Git actions."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from git_client import DesktopIntegration, launch_arguments, validate_choice
from local_dashboard import make_local_server
from local_view import display_from_manifests
from manifest import build_manifest, fleet_id_for


def refused(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError("expected refusal")


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repository = root / "checkout with spaces & punctuation"
        repository.mkdir()
        subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
        executable = root / "GitHubDesktop.exe"
        executable.touch()
        choice = {"id": "github-desktop", "executable": str(executable)}
        validate_choice(None)
        refused(lambda: validate_choice({"id": "shell", "executable": str(executable)}))
        refused(lambda: validate_choice({"id": "github-desktop", "executable": "relative.exe"}))
        assert launch_arguments(choice, repository) == [str(executable), "--cli-open", str(repository)]
        with patch("git_client.sys.platform", "win32"):
            source = {**choice, "id": "sourcetree"}
            assert launch_arguments(source, repository) == [str(executable), "-f", str(repository), "status"]

        inventory = {"a" * 32: repository}
        save, launch = Mock(), Mock()
        with patch("git_client.discover_clients", return_value={choice["id"]: choice}):
            desktop = DesktopIntegration(None, lambda: inventory, save, launcher=launch)
        assert desktop.settings()["configured"] is False
        assert str(root) not in json.dumps(desktop.settings())
        refused(lambda: desktop.handle("open-git-client", {"repo_id": "a" * 32}))
        refused(lambda: desktop.handle("git-client", {"client_id": "shell"}))
        desktop.handle("git-client", {"client_id": "github-desktop"})
        save.assert_called_once_with(choice)
        assert desktop.settings()["available"]
        refused(lambda: desktop.handle("open-git-client", {"repo_id": "peer-only"}))
        refused(lambda: desktop.handle("open-git-client", {"repo_id": "a" * 32, "path": "elsewhere"}))
        assert launch.call_count == 0
        desktop.handle("open-git-client", {"repo_id": "a" * 32})
        assert launch.call_args.args[0] == [str(executable), "--cli-open", str(repository)]
        assert launch.call_args.kwargs["shell"] is False

        # HTTP authority never comes from names/paths or from remote report data.
        server = make_local_server(("127.0.0.1", 0), lambda: {"rows": []}, {}, desktop.handle)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        opener = build_opener(ProxyHandler({}))

        def request(path, body=None, headers=None):
            req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers or {})
            try:
                response = opener.open(req, timeout=3)
            except HTTPError as exc:
                response = exc
            with response:
                return response.status, json.loads(response.read())

        try:
            assert request("/v1/dashboard", headers={"Host": "evil.example"})[0] == 403
            status, document = request("/v1/dashboard")
            assert status == 200
            token = document["local_actions"]["token"]
            headers = {"Content-Type": "application/json", "Origin": base,
                       "X-GitSpecOps-Token": token}
            body = {"repo_id": "a" * 32}
            count = launch.call_count
            assert request("/v1/open-git-client")[0] == 404
            assert request("/v1/open-git-client", body)[0] == 403
            assert request("/v1/open-git-client", body, {**headers, "Origin": "https://evil.example"})[0] == 403
            assert request("/v1/open-git-client", body, {**headers, "X-GitSpecOps-Token": "wrong"})[0] == 403
            assert request("/v1/open-git-client", {"repo_id": "peer-only"}, headers)[0] == 400
            assert launch.call_count == count
            assert request("/v1/open-git-client", body, headers)[0] == 200
            assert launch.call_count == count + 1
            assert request("/v1/report", body, headers)[0] == 405
            assert request("/v1/git-client", {"client_id": ""}, headers)[0] == 200
            assert desktop.choice is None
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        desktop.handle("git-client", {"client_id": "github-desktop"})
        executable.unlink()
        assert not desktop.settings()["available"]
        refused(lambda: desktop.handle("open-git-client", {"repo_id": "a" * 32}))

    fleet = fleet_id_for("22" * 32)
    records = [{"repo_id": rid, "branch_id": "c" * 16, "has_upstream": False,
                "upstream_observed_at": None, "ahead": None, "behind": None,
                "staged": 0, "unstaged": 1, "untracked": 0, "stashes": 0,
                "operation": None} for rid in ("a" * 32, "b" * 32)]
    manifest = build_manifest(fleet, "machine-a", "A", records)
    view = display_from_manifests([manifest], fleet_id=fleet, settings={
        "local_repo_ids": ["a" * 32], "git_client": {"configured": True, "available": True,
        "id": "github-desktop", "label": "GitHub Desktop", "choices": []}})
    rows = {r["id"]: r for r in view["rows"]}
    assert rows["a" * 32]["desktop_action"]["available"]
    assert not rows["b" * 32]["desktop_action"]["available"]
    assert view["capabilities"]["repository_actions"]["available"] is False
    assert "executable" not in json.dumps(view)
    print("ALL-GIT-CLIENT-TESTS-PASS")


if __name__ == "__main__":
    main()
