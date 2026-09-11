"""Optional local desktop Git clients. Fixed launch arguments, no shell or Git mutations."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

from shared.git_facts import run_git

LABELS = {"sourcetree": "Sourcetree", "github-desktop": "GitHub Desktop"}


def validate_choice(choice):
    if choice is None:
        return
    if not isinstance(choice, dict) or set(choice) != {"id", "executable"} \
            or choice.get("id") not in LABELS:
        raise ValueError("invalid desktop Git client configuration")
    executable = choice.get("executable")
    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise ValueError("desktop Git client executable must be an absolute local path")
    if sys.platform == "win32" and Path(executable).suffix.lower() != ".exe":
        raise ValueError("select the desktop client's .exe, not a shell command")


def discover_clients(configured=None) -> dict:
    """Check standard install locations only; never install or select a client implicitly."""
    candidates = {}
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            for client, folder, filename in (
                ("sourcetree", "SourceTree", "SourceTree.exe"),
                ("github-desktop", "GitHubDesktop", "GitHubDesktop.exe")):
                root = Path(local) / folder
                paths = [root / filename, *sorted(root.glob(f"app-*/{filename}"),
                                                 key=lambda p: p.stat().st_mtime, reverse=True)]
                found = next((p for p in paths if p.is_file()), None)
                if found:
                    candidates[client] = {"id": client, "executable": str(found.resolve())}
    elif sys.platform == "darwin":
        # GitHub Desktop's native executable handles --cli-open on macOS as on Windows.
        for root in (Path("/Applications"), Path.home() / "Applications"):
            path = root / "GitHub Desktop.app/Contents/MacOS/GitHub Desktop"
            if path.is_file():
                candidates["github-desktop"] = {"id": "github-desktop", "executable": str(path)}
    if configured:
        validate_choice(configured)
        if Path(configured["executable"]).is_file():
            candidates[configured["id"]] = dict(configured)
    return candidates


def launch_arguments(choice: dict, repository: Path) -> list[str]:
    validate_choice(choice)
    if not Path(choice["executable"]).is_file():
        raise ValueError("the configured Git client is unavailable; select its installed location")
    if choice["id"] == "sourcetree":
        if sys.platform != "win32":
            raise ValueError("the Sourcetree adapter currently supports Windows")
        return [choice["executable"], "-f", str(repository), "status"]
    return [choice["executable"], "--cli-open", str(repository)]


def open_repository(choice: dict, repository: Path, launcher=None):
    repository = repository.resolve(strict=True)
    fact = run_git(repository, ["rev-parse", "--show-toplevel"], timeout=10,
                   env={"GIT_OPTIONAL_LOCKS": "0"})
    if fact.returncode or Path(fact.stdout.strip()).resolve() != repository:
        raise ValueError("the local checkout is no longer available")
    args = launch_arguments(choice, repository)
    environment = dict(os.environ)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    # Intentionally visible: this is the user's explicit request to open an interactive app.
    process = (launcher or subprocess.Popen)(args, cwd=repository, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        shell=False)
    if launcher is None:
        # Reap the child when it exits; do not block the dashboard on the client's lifetime.
        threading.Thread(target=process.wait, daemon=True).start()


class DesktopIntegration:
    """Local UI boundary. The browser supplies only a known client id or repository id."""
    def __init__(self, choice, repositories, save_choice, launcher=None):
        self.choice = choice
        self.repositories = repositories
        self.save_choice = save_choice
        self.launcher = launcher
        self.candidates = discover_clients(choice)
        self.lock = threading.Lock()

    def settings(self):
        with self.lock:
            choice = self.choice
            available = bool(choice and Path(choice["executable"]).is_file())
            return {"configured": bool(choice), "available": available,
                    "id": choice["id"] if choice else "",
                    "label": LABELS[choice["id"]] if choice else "Desktop Git client",
                    "choices": [{"id": key, "label": LABELS[key]}
                                for key in self.candidates],
                    "reason": ("Open a local checkout for review and Git operations in your client."
                               if available else "Choose an installed desktop Git client in App & setup."
                               if self.candidates else "No supported desktop Git client found.")}

    def handle(self, action, payload):
        with self.lock:
            if action == "git-client":
                if set(payload) != {"client_id"} or not isinstance(payload["client_id"], str):
                    raise ValueError("select a known desktop Git client")
                client = payload["client_id"]
                if client and client not in self.candidates:
                    raise ValueError("the selected desktop Git client was not detected locally")
                choice = self.candidates.get(client)
                if choice and not Path(choice["executable"]).is_file():
                    raise ValueError("the selected desktop Git client is no longer installed")
                self.save_choice(choice)
                self.choice = choice
                return {"message": f"Selected {LABELS[client]}." if client else "Desktop shortcut disabled."}
            if action != "open-git-client" or set(payload) != {"repo_id"} \
                    or not isinstance(payload["repo_id"], str):
                raise ValueError("unknown desktop action")
            if not self.choice:
                raise ValueError("select a desktop Git client first")
            repository = self.repositories().get(payload["repo_id"])
            if repository is None:
                raise ValueError("this repository is not in the local observed inventory")
            open_repository(self.choice, Path(repository), self.launcher)
            return {"message": f"Open request sent to {LABELS[self.choice['id']]}."}
