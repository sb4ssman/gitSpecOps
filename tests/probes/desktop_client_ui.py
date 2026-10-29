"""Manual local UI check with synthetic repositories and a simulated desktop launcher.

Run explicitly, then visit the printed loopback URL. No desktop app is launched and no real
configuration is changed. Ctrl-C stops the server. All fixtures are temporary.
The security button reads a real synthetic working file under temporary policy; outgoing
history is explicitly unchecked in this unborn fixture. No finding is shared with a peer.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from git_client import DesktopIntegration
from local_dashboard import make_local_server
from local_view import display_from_manifests
from manifest import build_manifest, fleet_id_for
from ui_assets import load_ui_assets
from Special.security._advice import inspect_registered


def main():
    with tempfile.TemporaryDirectory(prefix="gitspecops-desktop-ui-") as temp, \
            patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"}):
        root = Path(temp)
        repository = root / "example-work"
        repository.mkdir()
        subprocess.run(["git", "init", str(repository)], capture_output=True, check=True)
        (repository / "demo.txt").write_text("demo-private-marker", encoding="utf-8")
        home = root / "profile"
        home.mkdir()
        (home / "settings.json").write_text(json.dumps({"schema_version": 2,
            "defaults": {"security": {"never_publish": ["demo-private-marker"]}}}), encoding="utf-8")
        executable = root / "GitHubDesktop.exe"
        executable.touch()
        choice = {"id": "github-desktop", "executable": str(executable)}
        rid = "a" * 32
        fleet = fleet_id_for("22" * 32)
        records = [{"repo_id": item, "branch_id": "c" * 16, "has_upstream": True,
                    "upstream_observed_at": None, "ahead": 1, "behind": 0,
                    "staged": 0, "unstaged": 1, "untracked": 0, "stashes": 0,
                    "operation": None} for item in (rid, "b" * 32)]
        manifest = build_manifest(fleet, "machine-a", "Example machine", records)
        names = {rid: {"host": "github.com", "owner": "example", "name": "work"},
                 "b" * 32: {"host": "github.com", "owner": "example", "name": "peer-only"}}

        def simulate(*args, **kwargs):
            print("SIMULATED desktop launch for the synthetic checkout", flush=True)
            return Mock()

        with patch("git_client.discover_clients", return_value={choice["id"]: choice}):
            desktop = DesktopIntegration(None, lambda: {rid: repository}, lambda _: None, simulate)

        def document():
            return display_from_manifests([manifest], fleet_id=fleet, names=names,
                now=datetime.now(timezone.utc), settings={"git_client": desktop.settings(),
                "local_repo_ids": [rid], "security_available": True})

        def security_action(action, payload):
            if action != "security-preview":
                raise ValueError("unsupported synthetic action")
            return inspect_registered(payload, lambda requested: [repository] if requested == rid else [], settings_home=home)

        server = make_local_server(("127.0.0.1", 0), document, load_ui_assets(), desktop.handle, security_action)
        print(f"Synthetic dashboard: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
