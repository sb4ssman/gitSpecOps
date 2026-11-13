"""The setup engine: what this computer has, what the person wants, and exactly what will change.

Why:          setup is one plan, reviewed and then applied, on every face: the terminal wizard
              (setup_gitspecops.py), the web view's Setup page, and agents. They share this
              engine, so they can never disagree about what a choice does.
Reads:        the settings profile, the start-at-login registration, installed desktop Git
              apps, Tailscale and synced-folder availability. Never a repository's contents.
May change:   nothing until `apply`. Then exactly the planned changes: library folders and
              the web view's reach (enrollment), the start-at-login entry, the desktop Git app,
              protected values, and the fleet (key and ways to share). Never a repository.
Results:      Current (detect), Choices (what the person wants), Change list (plan), and per
              change a result for the run screen.
Layer:        Elaborate: other machines or over time.
Status:       working

A plan is built from the current state and the choices alone; building it changes nothing.
Every Change carries the words the review shows: what it does, and what it reads or sends.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WEB_CHOICES = {"loopback": "this computer only", "tailnet": "this computer and your own Tailscale devices",
               "off": "not served"}
FLEET_MODES = ("none", "keep", "new", "join")


@dataclass
class Current:
    """What this computer has now. Detection reads no repository."""
    enrolled: bool = False
    machine: str = ""
    libraries: list = field(default_factory=list)
    web: str = "loopback"
    face: str = "web"
    start_at_login: bool | None = None          # None: this platform has no backend
    login_target: str = ""
    git_client: str = ""                        # "" when none is chosen
    clients: dict = field(default_factory=dict)  # id -> {"id", "executable"}
    protected: dict = field(default_factory=dict)  # list name -> values
    fleet_transports: dict = field(default_factory=dict)
    share_names: bool = True
    tailnet: bool = False
    synced_folders: list = field(default_factory=list)
    github: bool = False
    settings_file: str = ""


@dataclass
class Choices:
    """What the person wants. Starts as the current state; nothing here is saved until applied."""
    libraries: list = field(default_factory=list)
    web: str = "loopback"
    start_at_login: bool | None = None
    git_client: str = ""
    protect: list = field(default_factory=list)   # [(value, whole_word)] to add
    fleet_mode: str = "keep"                      # keep | none | new | join
    fleet_key: str = ""
    fleet_tailnet: bool = False
    fleet_folder: str = ""
    share_names: bool = True


@dataclass
class Change:
    key: str
    title: str
    review: list            # lines for the review screen: what it does, what it reads or sends
    apply: object = None    # callable() -> detail text; raises on failure


def detect(home=None, config_dir=None, *, python=None) -> Current:
    """The current state, read-only. `python`: the interpreter whose start-at-login entry counts."""
    from Elaborate._fleet.setup_state import setup_state
    from Special._sync.git_client import discover_clients

    state = setup_state(home, config_dir, readiness=True)
    current = Current()
    machine = state["machine"]
    if machine:
        current.enrolled, current.machine = True, machine["label"]
        current.libraries = list(machine["libraries"])
        current.web, current.face = machine["presentation"]["web"], machine["presentation"]["face"]
    if state["fleet"]:
        current.fleet_transports = dict(state["fleet"]["transports"])
        current.share_names = bool(state["fleet"]["share_names"])
    ready = state["readiness"]
    current.tailnet, current.github = bool(ready["tailnet"]), bool(ready["github"])
    current.synced_folders = list(ready["folders"])
    try:
        from Elaborate._fleet import autostart
        status = autostart.status()
        current.start_at_login = bool(status.get("enabled")) if status.get("supported", True) else None
        current.login_target = status.get("target") or ""
    except (OSError, ValueError, ImportError):
        current.start_at_login = None
    configured = _configured_client(home, config_dir)
    current.clients = discover_clients(configured)
    current.git_client = (configured or {}).get("id", "")
    try:
        from Special._security._policy_edit import policy_view
        current.protected = policy_view(home)["lists"]
    except ValueError:
        current.protected = {}
    try:
        from Special._settings.fleet import fleet_home
        current.settings_file = str(Path(fleet_home(home)) / "settings.json")
    except (OSError, ValueError):
        current.settings_file = "the gitSpecOps settings file"
    return current


def _configured_client(home, config_dir):
    try:
        from Elaborate._fleet.cli import load_saved
        from Special._settings.fleet import fleet_directory
        return (load_saved(fleet_directory(config_dir, home=home), home=home) or {}).get("git_client")
    except (OSError, ValueError, KeyError):
        return None


def choices_from(current: Current) -> Choices:
    """Choices that change nothing: the current state. A first setup also starts at login."""
    return Choices(libraries=list(current.libraries), web=current.web,
                   start_at_login=(True if not current.enrolled and current.start_at_login is not None
                                   else current.start_at_login),
                   git_client=current.git_client, fleet_mode="keep" if current.fleet_transports else "none",
                   fleet_tailnet="tailnet" in current.fleet_transports,
                   fleet_folder=(current.fleet_transports.get("folder") or {}).get("path", ""),
                   share_names=current.share_names)


def _same(a: str, b: str) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return a == b


def plan(current: Current, choices: Choices, home=None, config_dir=None, *, python=None) -> list[Change]:
    """Exactly what applying these choices would change, in the order it would happen."""
    from Special._sync import enrollment

    changes = []
    settings = current.settings_file
    added = [p for p in choices.libraries if not any(_same(p, have) for have in current.libraries)]
    removed = [p for p in current.libraries if not any(_same(p, want) for want in choices.libraries)]
    enrolled_after = bool(choices.libraries)
    if added:
        changes.append(Change(
            "libraries", "Library folders",
            [f"Add {', '.join(added)}.",
             "When the app starts it reads folder names there to find Git repositories, and each "
             "repository's Git status (branch, uncommitted and unpushed work). Never file contents.",
             f"Saved in {settings}."],
            lambda: f"{len(enrollment.add_libraries(added, home=home))} libraries"))
    for path in removed:
        if enrolled_after:
            changes.append(Change("libraries", "Library folders", [f"Stop watching {path} (nothing in it is touched)."],
                                  lambda path=path: f"{len(enrollment.remove_library(path, home=home))} libraries"))
    if enrolled_after and choices.web != current.web:
        changes.append(Change(
            "web", "Web view", [f"Serve the web view to {WEB_CHOICES[choices.web]}."]
            + (["Your own Tailscale devices can then open it; nothing else can."] if choices.web == "tailnet" else []),
            lambda: str(enrollment.set_presentation(face=current.face, web=choices.web, home=home))))
    if choices.start_at_login is not None and choices.start_at_login != current.start_at_login:
        if choices.start_at_login:
            entry = ('one "GitSpecOpsFleet" entry in your Windows sign-in list (your account only)'
                     if sys.platform == "win32" else "one autostart entry for your account")
            review = [f"Start gitSpecOps when you sign in: {entry}.",
                      "Remove it any time here, or in Task Manager under Startup apps."
                      if sys.platform == "win32" else "Remove it any time here."]
        else:
            review = ["Stop starting gitSpecOps when you sign in (removes its entry)."]
        changes.append(Change("login", "Start at sign-in", review,
                              lambda: _start_at_login(choices.start_at_login, python)))
    if enrolled_after and choices.git_client != current.git_client:
        label = (current.clients.get(choices.git_client) or {}).get("id", choices.git_client)
        from Special._sync.git_client import LABELS
        changes.append(Change(
            "git-client", "Desktop Git app",
            [f"Open repositories from the web view in {LABELS.get(label, label)}." if choices.git_client
             else "Open repositories in no desktop Git app."],
            lambda: _save_client(current.clients.get(choices.git_client), home, config_dir)))
    for value, whole in choices.protect:
        changes.append(Change(
            "protect", "Protected value",
            [f"Protect one more value ({'whole word only' if whole else 'anywhere in text'}): "
             "scans treat it as a high finding. Nothing is scanned now."],
            lambda value=value, whole=whole: _protect(value, whole, home)))
    fleet = _fleet_change(current, choices, home, config_dir, enrolled_after)
    if fleet:
        changes.append(fleet)
    return changes


def _fleet_change(current, choices, home, config_dir, enrolled_after):
    from Elaborate._fleet.setup_state import join_fleet, leave_fleet

    if choices.fleet_mode == "keep":
        return None
    if choices.fleet_mode == "none":
        if not current.fleet_transports:
            return None
        return Change("fleet", "Fleet", ["Leave the fleet: stop sharing with your other machines. "
                                         "This computer keeps its libraries."],
                      lambda: (leave_fleet(home, config_dir), "left the fleet")[1])
    if not enrolled_after:
        return None
    ways = (["Tailscale: your machines talk directly; this computer listens on its Tailscale "
             "address, port 8765, for your own devices only"] if choices.fleet_tailnet else [])
    ways += ([f"a synced folder ({choices.fleet_folder}): one small status file there every 5 minutes"]
             if choices.fleet_folder else [])
    shared = ("repository names, branches and commit counts" if choices.share_names
              else "repository status without names")
    review = [("Join the fleet whose key you pasted." if choices.fleet_mode == "join"
               else "Start a fleet with this computer; add your other machines with its key."),
              "Share through " + "; and ".join(ways) + ".",
              f"Shared with your own machines only: {shared}. Never file contents or folder paths."]
    key = choices.fleet_key if choices.fleet_mode == "join" else None
    return Change("fleet", "Fleet", review, lambda: (join_fleet(
        home, config_dir, key=key, folder=choices.fleet_folder or None, tailnet=choices.fleet_tailnet,
        share_names=choices.share_names), "joined")[1])


def problems(current: Current, choices: Choices) -> list[str]:
    """Choices that cannot be applied as they stand; the wizard says these before review."""
    found = []
    if choices.fleet_mode in ("new", "join"):
        if not choices.libraries:
            found.append("A fleet needs a library folder on this computer first.")
        if not (choices.fleet_tailnet or choices.fleet_folder):
            found.append("A fleet needs a way to share: Tailscale or a synced folder.")
        if choices.fleet_mode == "join" and len(choices.fleet_key) != 64:
            found.append("Joining needs the 64-character fleet key from your other machine.")
    if choices.web != current.web and not choices.libraries:
        found.append("The web view's reach is saved with a library folder; add one first.")
    return found


def _start_at_login(enable: bool, python) -> str:
    """Through the start_at_login command, run by the environment that has the desktop app, so
    the entry starts a tray that can actually start (Qt lives there, not in every Python)."""
    root = Path(__file__).resolve().parents[2]
    command = [str(python or sys.executable), str(root / "Elaborate" / "start_at_login.py"), "enable" if enable else "disable"]
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, errors="replace")
    if done.returncode:
        raise ValueError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip()
                         else "start at sign-in could not be changed")
    return "entry added" if enable else "entry removed"


def _save_client(choice, home, config_dir) -> str:
    from Elaborate._fleet.cli import load_saved
    from Elaborate._fleet.config import save_client_choice
    from Special._settings.fleet import fleet_directory

    directory = fleet_directory(config_dir, home=home)
    save_client_choice(directory, load_saved(directory, home=home), copy.deepcopy(choice) if choice else None)
    return "saved"


def _protect(value: str, whole: bool, home) -> str:
    from Special._security._policy_edit import policy_change

    policy_change(home, {"list": "never_publish_words" if whole else "never_publish", "add": [value]})
    return "added"
