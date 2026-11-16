"""The setup walkthrough: find what this computer already has, ask about each part, review, apply.

Why:          a person setting up gitSpecOps should be walked through everything it can connect
              to, told what is already in place, and asked before anything happens.
Reads:        Git, the GitHub CLI and its sign-in, uv, this folder's .venv, the gitso command,
              this machine's enrollment, start at sign-in, desktop Git apps, protected values,
              the secret scanners, Tailscale, synced folders. Never a repository's contents.
May change:   nothing until the review is accepted. Then exactly what was chosen, built up
              in gitSpecOps' own order: installs (with the system's package tool, the
              command shown first), the GitHub sign-in, the gitso command, library folders,
              protected values, the scanners used in scans, archives, the fleet, the
              desktop app, the desktop Git app, start at sign-in, starting the app.
Results:      the walkthrough screens, the review, a run screen of numbered steps.
Layer:        setup (_build): uses the layers' own functions; no policy of its own.
Status:       working

Screens follow the station script design (.agents/knowledge/station-script-design.md). Every
area offers the same answers: yes, no, or stop (nothing changes). Run again, each area shows what
is already set and asks whether to keep or change it. The fleet's state repository is
experimental and untested: setup offers it, says so, and its answer defaults to no. After the
review is applied, setup asks whether to read the library now (the first scan); nothing starts
unless the person chooses it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Basic._station import (  # noqa: E402
    Steps, ask, banner, bullet, choose, line, notice, option, row, say, section)

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if WINDOWS else "bin/python")
# In gitSpecOps' own order, built up from below: Basic (Git, GitHub, the gitso command), Special
# (this machine: libraries, protection, scanners, archives), Elaborate (other machines: the fleet),
# then the App (the desktop app, opening a desktop Git app from it, running it).
AREAS = ("Requirements", "The gitso command", "This machine", "Protection", "Scanners", "Archives",
         "Fleet", "The desktop app", "Desktop Git app", "Running the app")

from Special._security._audit import INSTALL_PACKAGES  # noqa: E402  the Security tab suggests the same

#: Package names per installer. Missing means setup cannot install it on that system.
PACKAGES = {
    "gh": {"winget": "GitHub.cli", "brew": "gh", "apt": "gh"},
    "uv": {"winget": "astral-sh.uv", "brew": "uv"},
    **INSTALL_PACKAGES,
}
HOME_PAGES = {
    "gh": "https://cli.github.com", "uv": "https://docs.astral.sh/uv/",
    "gitleaks": "https://github.com/gitleaks/gitleaks", "betterleaks": "https://github.com/betterleaks/betterleaks",
    "trufflehog": "https://github.com/trufflesecurity/trufflehog", "tailscale": "https://tailscale.com/download",
}
SCANNERS = {
    "gitleaks": "The most widely used secret scanner: keys and tokens in files and full history. "
                "Runs offline. Recommended.",
    "betterleaks": "From the makers of Gitleaks, including its original author. Setup installs version 1, "
                   "which gitSpecOps supports; version 2 changes its output and is not supported yet.",
    "trufflehog": "Hundreds of credential detectors. gitSpecOps runs it with verification off, so "
                  "nothing found is sent to any provider.",
}


class Stop(Exception):
    """The person stopped the walkthrough; nothing was changed."""


@dataclass
class Change:
    title: str
    review: str
    apply: object  # callable() -> short detail
    loud: bool = False  # runs another program that prints (an installer, uv, gh)


@dataclass
class Plan:
    changes: list = field(default_factory=list)
    libraries: list = field(default_factory=list)   # to add
    enrolled_after: bool = False
    uv_after: bool = False
    venv_after: bool = False
    desktop_after: bool = False  # the tray app (Qt) will be installed

    def add(self, title, review, apply, loud=False):
        self.changes.append(Change(title, review, apply, loud))


# --------------------------------------------------------------------------- detection
def _run(command, timeout=30) -> tuple[int, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout)
        return done.returncode, (done.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def installer() -> str | None:
    """This system's package tool, if setup can use it."""
    if WINDOWS and shutil.which("winget"):
        return "winget"
    if MAC and shutil.which("brew"):
        return "brew"
    if sys.platform.startswith("linux") and shutil.which("apt-get"):
        return "apt"
    return None


def install_command(name: str) -> list[str] | None:
    tool = installer()
    package = PACKAGES.get(name, {}).get(tool or "")
    if not package:
        return None
    if tool == "winget":
        return ["winget", "install", "--id", package, "--exact", "--accept-source-agreements",
                "--accept-package-agreements"]
    if tool == "brew":
        return ["brew", "install", package]
    code, out = _run(["apt-cache", "policy", package])
    if code or "Candidate: (none)" in out or "Candidate:" not in out:
        return None
    return ["sudo", "apt-get", "install", "-y", package]


def refresh_path() -> None:
    """After an install, find the new program without restarting setup."""
    extra = [str(Path.home() / ".local" / "bin")]
    if WINDOWS:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    extra += [os.path.expandvars(p) for p in winreg.QueryValueEx(handle, "Path")[0].split(";") if p]
            except OSError:
                pass
        local = os.environ.get("LOCALAPPDATA")
        if local:
            extra.append(str(Path(local) / "Microsoft" / "WinGet" / "Links"))
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(current + [p for p in extra if p and p not in current])


def detect() -> dict:
    """What this computer has now. Reads only."""
    from Elaborate._fleet.setup_state import setup_state
    from Elaborate._fleet import autostart
    from Special._sync.git_client import discover_clients

    found = {"git": shutil.which("git"), "gh": shutil.which("gh"), "uv": shutil.which("uv"),
             "gitso": shutil.which("gitso"), "tailscale": shutil.which("tailscale"),
             "venv": VENV_PYTHON.exists(),
             "desktop": (VENV_DIR / "Lib/site-packages/PySide6").exists()
             or any(VENV_DIR.glob("lib/python*/site-packages/PySide6"))}
    found["gh_signed_in"] = bool(found["gh"]) and _run(["gh", "auth", "status"])[0] == 0
    account = _run(["gh", "api", "user", "--jq", '.login + " " + (.id | tostring)'])[1].split() \
        if found["gh_signed_in"] else []
    found["gh_login"], found["gh_id"] = account if len(account) == 2 else ("", "")
    found["git_name"] = _run(["git", "config", "--global", "user.name"])[1] if found["git"] else ""
    found["git_email"] = _run(["git", "config", "--global", "user.email"])[1] if found["git"] else ""
    import getpass
    found["user"] = getpass.getuser()
    state = setup_state(readiness=True)
    machine = state["machine"] or {}
    found["enrolled"] = bool(machine)
    found["machine"] = machine.get("label", "")
    found["libraries"] = list(machine.get("libraries", []))
    found["web"] = (machine.get("presentation") or {}).get("web", "loopback")
    found["face"] = (machine.get("presentation") or {}).get("face", "web")
    found["fleet"] = dict((state["fleet"] or {}).get("transports") or {})
    found["fleet_name"] = (state["fleet"] or {}).get("name")
    found["tailnet"] = bool(state["readiness"]["tailnet"])
    found["synced_folders"] = list(state["readiness"]["folders"])
    found["login"], found["login_elsewhere"] = None, ""
    try:
        status = autostart.status()
        if status.get("supported"):
            found["login"] = ("elsewhere" if status.get("turned_off_elsewhere")
                              else "on" if status.get("enabled") else "off")
            found["login_elsewhere"] = status.get("elsewhere") or ""
    except (OSError, ValueError, ImportError):
        pass
    configured = _configured_client()
    found["client"] = (configured or {}).get("id", "")
    found["clients"] = discover_clients(configured)
    found["protected"], found["engines"] = _security()
    from _build import gitso_command
    found["gitso_command"] = gitso_command.status()
    found["alias_targets"] = [str(path) for path in gitso_command.alias_files()]
    from Basic._paths import find_program
    for name in SCANNERS:
        found[name] = find_program(name)
    found["archives"] = _archives()
    found["app_running"] = app_running()
    from Special._sync.enrollment import current_fetch_minutes
    found["fetch_minutes"] = current_fetch_minutes()
    return found


def _configured_client():
    try:
        from Elaborate._fleet.cli import load_saved
        from Special._settings.fleet import fleet_directory
        return (load_saved(fleet_directory()) or {}).get("git_client")
    except (OSError, ValueError, KeyError):
        return None


def _security() -> tuple[dict, list]:
    try:
        from Special._security._policy_edit import policy_view
        from Special._settings.security import load_security_settings
        lists = policy_view(None)["lists"]
        engines = list(load_security_settings().owned_policy().get("engines", []))
        return lists, engines
    except (OSError, ValueError, KeyError):
        return {}, []


# --------------------------------------------------------------------------- screens
def step(title: str) -> str:
    """'step N' for a part, from its place in AREAS."""
    return f"step {AREAS.index(title) + 1}"


def screen(title: str) -> None:
    banner(f"Setup  {AREAS.index(title) + 1}/{len(AREAS)}:  {title}", tagline=True)


def yes_no(question: str, default: str = "y", explanation: str = "") -> bool:
    """[Y] Yes, [N] No, [0] Stop the walkthrough."""
    say()
    line(question)
    if explanation:
        line(explanation, "muted")
    option("Y", "Yes")
    option("N", "No")
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    answer = choose("yn0", default)
    if answer == "0":
        raise Stop
    return answer == "y"


NOREPLY_DOMAIN = "@users.noreply.github.com"


def public_git_name(name: str, login: str) -> bool:
    """A Git name made from the public GitHub login (the login, or login@machine) is public."""
    name, login = name.casefold(), login.casefold()
    return bool(name and login) and (name == login or name.startswith(login + "@"))


def public_git_email(email: str) -> bool:
    """GitHub's no-reply addresses are public by design; any other address is treated as private."""
    email = email.casefold()
    return email.endswith(NOREPLY_DOMAIN) or email == "noreply@github.com"


def noreply_address(login: str, user_id: str) -> str:
    """GitHub's no-reply address for an account: ID+LOGIN@users.noreply.github.com."""
    return f"{user_id}+{login}{NOREPLY_DOMAIN}" if login and user_id.isdigit() else ""


def tool_row(label: str, path: str | None, missing: str) -> None:
    row(label, "found" if path else missing, "success" if path else "warning")


def offer_install(plan: Plan, name: str, label: str, why: str) -> bool:
    """Ask to install a missing program; returns whether it will be installed."""
    command = install_command(name)
    if command:
        if not yes_no(f"Install {label}?", "y", f"{why} Runs: {' '.join(command)}".strip()):
            return False
        plan.add(f"Install {label}", f"{label}: {' '.join(command)}", lambda: _install(command, name), loud=True)
        return True
    from _build import release_install  # no package here: the project's own release, checked
    if release_install.available(name):
        if not yes_no(f"Install {label}?", "y", f"{why} {release_install.describe(name)}".strip()):
            return False
        plan.add(f"Install {label}", f"{label}: {release_install.describe(name)}",
                 lambda: release_install.install(name))
        return True
    line(f"Setup cannot install {label} on this system, so there is nothing to decide here. To add "
         f"it later, get it at {HOME_PAGES[name]} and run setup again.", "muted")
    return False


def _install(command: list[str], name: str) -> str:
    code = subprocess.call(command)
    refresh_path()
    if code != 0 and not shutil.which(name):
        raise RuntimeError(f"the installer stopped with exit code {code}")
    return "installed" if shutil.which(name) else "installed; open a new terminal to use it"


# --------------------------------------------------------------------------- the areas
def area_requirements(found: dict, plan: Plan) -> None:
    screen("Requirements")
    if not found["git"]:
        notice("Git is required", "Install it from https://git-scm.com/downloads, then run setup again. "
               "Nothing has been changed.", "error")
        raise Stop
    tool_row("Git", found["git"], "missing")
    tool_row("GitHub CLI", found["gh"], "not installed")
    if found["gh"]:
        row("GitHub sign-in", found["gh_login"] or "signed in" if found["gh_signed_in"] else "not signed in",
            "success" if found["gh_signed_in"] else "warning")
    line("The GitHub CLI is how gitSpecOps talks to GitHub with your own sign-in: copying "
         "organizations, archive sync, publishing. Everything else works without it.", "muted")
    will_have_gh = bool(found["gh"]) or offer_install(plan, "gh", "the GitHub CLI", "")
    if will_have_gh and not found["gh_signed_in"]:
        if yes_no("Sign in to GitHub?", "y", "Runs gh auth login during setup; you answer its questions. "
                  "gitSpecOps never sees or stores your credentials."):
            plan.add("Sign in to GitHub", "GitHub sign-in: gh auth login (you answer its questions)", _gh_login, loud=True)


def _gh_login() -> str:
    if subprocess.call(["gh", "auth", "login"]) != 0:
        raise RuntimeError("gh auth login did not finish")
    return "signed in"


def area_environment(found: dict, plan: Plan) -> None:
    screen("The desktop app")
    row("Desktop app", "installed" if found["desktop"] else "not installed",
        "success" if found["desktop"] else "warning")
    tool_row("uv", found["uv"], "not installed")
    line("The desktop app is gitSpecOps' tray icon, by the clock, and the map of your repositories it "
         "opens: its colour says whether everything is in order. It is drawn with Qt, which setup "
         "installs with uv into this folder's .venv; nothing system-wide. The gitso commands need "
         "only Python.", "muted")
    plan.desktop_after = found["desktop"]
    plan.uv_after = bool(found["uv"]) or offer_install(plan, "uv", "uv", "The desktop app is installed with it.")
    if not plan.uv_after:
        line("Without uv the desktop app cannot be installed; the gitso commands still work.", "warning")
        plan.venv_after = found["venv"]
        return
    # `uv sync --extra app`: make this folder's .venv exactly what uv.lock lists, plus the "app"
    # extra (Qt). Without --extra app, a sync would remove Qt.
    if found["desktop"]:
        question = "The desktop app is installed. Update it?"
        hint = ("Only needed after updating gitSpecOps: brings Qt in this folder's .venv to the version "
                "gitSpecOps expects (uv sync --extra app).")
        summary = "Desktop app (tray icon and map): update Qt in this folder's .venv (uv sync --extra app)"
    else:
        question = "Install the desktop app, the tray icon and map?"
        hint = "Installs Qt into this folder's .venv with uv; nothing system-wide (uv sync --extra app)."
        summary = "Desktop app (tray icon and map): install Qt into this folder's .venv (uv sync --extra app)"
    if yes_no(question, "n" if found["desktop"] else "y", hint):
        plan.add("Desktop app", summary, _build_env, loud=True)
        plan.venv_after = plan.desktop_after = True
    else:
        plan.venv_after = found["venv"]


def _build_env() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is not on PATH; open a new terminal and run setup again")
    from Elaborate._fleet.sealed import venv_has  # a sync keeps only what it names
    extras = ["--extra", "app", *(["--extra", "crypto"] if venv_has("cryptography") else [])]
    if subprocess.call([uv, "sync", *extras], cwd=ROOT) != 0:
        raise RuntimeError("uv sync did not finish")
    return ".venv ready, with the desktop app"


def _remove_desktop() -> str:
    """`uv sync` without `--extra app`: the .venv keeps what uv.lock lists and drops Qt."""
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(f"uv is not on PATH; delete {VENV_DIR} to remove the desktop app")
    if subprocess.call([uv, "sync"], cwd=ROOT) != 0:
        raise RuntimeError("uv sync did not finish")
    if (VENV_DIR / "Lib/site-packages/PySide6").exists() or any(VENV_DIR.glob("lib/python*/site-packages/PySide6")):
        raise RuntimeError("Qt is still in this folder's .venv")
    return "removed"


def area_gitso(found: dict, plan: Plan) -> None:
    from _build import gitso_command as command
    screen("The gitso command")
    state = found["gitso_command"]
    where = state["folder"]
    row("Command path", {"here": "set up", "elsewhere": "set up for another gitSpecOps folder",
                         "none": "not set up"}[state["launcher"]]
        + (", but its folder is not on PATH" if state["launcher"] != "none" and not state["on_path"] else ""),
        "success" if state["launcher"] == "here" and state["on_path"] else "text")
    row("Shell alias", ", ".join(Path(p).name for p in state["aliases"]) or "none")
    files = "gitso.cmd and gitso (for Git Bash)" if WINDOWS else "gitso"
    reach = "adds that folder to your user Path" if WINDOWS else \
        "adds that folder to PATH with a marked line in your shell startup files"
    line("gitso is a command of its own, alongside git and gh: gitSpecOps' special operations in "
         "any terminal, in any folder (gitso commands, gitso scan ., and so on), using git and "
         f"gh underneath. It replaces nothing. Setup writes {files}, small text files you can read, "
         f"in {where}, and {reach}. They run this folder's gitso.py with Python; nothing is compiled "
         "or installed. Without it, the same commands run as: python gitso.py <command>.", "muted")
    say()
    if state["launcher"] == "none":
        option("A", "Put gitso on your command path")
        option("N", "Not now")
        keys, default = "an0", "a"
    elif state["launcher"] == "here" and state["on_path"]:
        option("K", "Keep it")
        option("R", "Remove it", f"Deletes the files in {where} and takes the folder off PATH.")
        keys, default = "kr0", "k"
    else:
        option("F", "Fix it", "Point it at this folder and put its folder on PATH.")
        option("K", "Leave it as it is")
        option("R", "Remove it", f"Deletes the files in {where} and takes the folder off PATH.")
        keys, default = "fkr0", "f"
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    answer = choose(keys, default)
    if answer == "0":
        raise Stop
    if answer in ("a", "f"):
        plan.add("The gitso command", f"gitso command: write {files} in {where}; {reach}",
                 lambda: command.install_launchers())
    elif answer == "r":
        plan.add("The gitso command", f"gitso command: delete it from {where} and take the folder off PATH",
                 lambda: command.remove_launchers())
    targets = found["alias_targets"]
    if state["aliases"]:
        if not yes_no("Keep the gitso alias in your shell profiles?", "y"):
            plan.add("gitso alias", "gitso alias: remove the marked lines from " + ", ".join(state["aliases"]),
                     lambda: command.remove_aliases())
    elif targets:
        warn = ""
        if any("/onedrive" in Path(t).as_posix().casefold() for t in targets):  # also "OneDrive - Work"
            warn += (" A profile here is in OneDrive, which copies it to your other PCs: there the "
                     "alias would point at this PC's folder.")
        if WINDOWS:
            warn += (" Windows may refuse the change (Controlled Folder Access protects Documents); "
                     "then setup shows the line to add yourself.")
        if yes_no("Also add gitso to your shell profiles, as an alias?", "n",
                  "Optional: the command path above is enough. Adds a marked block to: "
                  + ", ".join(targets) + "." + warn):
            plan.add("gitso alias", "gitso alias: a marked block in " + ", ".join(targets), _install_alias)


class Skipped(Exception):
    """A change that could not be made and is not a failure: the step says why and what to do."""


def _install_alias() -> str:
    from _build import gitso_command as command
    try:
        return command.install_aliases()
    except command.ProfileRefused as refused:
        raise Skipped(str(refused)) from None


def area_machine(found: dict, plan: Plan) -> None:
    from Special._sync.enrollment import find_libraries, whole_machine_starts
    screen("This machine")
    row("Enrolled", f"yes, as {found['machine']}" if found["enrolled"] else "not yet",
        "success" if found["enrolled"] else "warning")
    for path in found["libraries"]:
        row("Library folder", path)
    line("Library folders hold your Git repositories. gitSpecOps watches the repositories in them: "
         "their names and Git status, never file contents.", "muted")
    picked, found_dirs, removed = [], [], []
    while True:
        say()
        for number, item in enumerate(found_dirs, 1):
            option(str(number), f"{item['path']}  ({item['repositories']} repositories)")
        option("L", "Look for library folders in your home folder")
        option("W", "Look on every drive" if WINDOWS else "Look everywhere in your home folder")
        option("P", "Add a folder by its path")
        kept = [path for path in found["libraries"] if path not in removed]
        if kept:
            option("R", "Stop watching a library folder", "Nothing in it is changed or deleted.")
        option("N", "Done" if (picked or found["libraries"]) else "No library folders now")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        numbers = "".join(str(n) for n in range(1, len(found_dirs) + 1))
        answer = choose("lwpn0" + ("r" if kept else "") + numbers, "n")
        if answer == "0":
            raise Stop
        if answer == "n":
            break
        if answer == "r":
            for number, path in enumerate(kept[:9], 1):
                option(str(number), path)
            option("0", "Keep them all")
            which = choose("".join(str(n) for n in range(1, min(len(kept), 9) + 1)) + "0", "0")
            if which != "0":
                removed.append(kept[int(which) - 1])
                line(f"Will stop watching {removed[-1]}.", "success")
            continue
        if answer in ("l", "w"):
            line("Reading folder names only...", "detail")
            starts = [Path.home()] if answer == "l" else whole_machine_starts()
            found_dirs = [d for d in find_libraries(starts)
                          if d["path"] not in found["libraries"] and d["path"] not in picked][:9]
            if not found_dirs:
                line("No folders with repositories found there.", "warning")
        elif answer == "p":
            path = ask("Folder path:")
            if path and Path(path).expanduser().is_dir():
                picked.append(str(Path(path).expanduser().resolve()))
                line(f"Will add {picked[-1]}.", "success")
            elif path:
                line("That folder does not exist.", "warning")
        else:
            chosen = found_dirs[int(answer) - 1]["path"]
            picked.append(chosen)
            found_dirs = [d for d in found_dirs if d["path"] != chosen]
            line(f"Will add {chosen}.", "success")
    if picked:
        plan.libraries = picked
        plan.add("Library folders", "Library folders: add " + "; ".join(picked)
                 + ". Reads folder names and each repository's Git status, never file contents.",
                 lambda: _add_libraries(picked))
    if removed:
        plan.add("Library folders", "Library folders: stop watching " + "; ".join(removed)
                 + ". Nothing in them is changed or deleted.", lambda: _remove_libraries(removed))
    plan.enrolled_after = found["enrolled"] or bool(picked)


def _remove_libraries(paths) -> str:
    from Special._sync.enrollment import remove_library
    for path in paths:
        remove_library(path)
    return f"stopped watching {len(paths)} library folder(s); the app reads its libraries again when it restarts"


def _add_libraries(paths) -> str:
    from Special._sync.enrollment import add_libraries
    return f"{len(add_libraries(paths))} library folders"


#: Where each system lets people switch start-up items on and off without gitSpecOps.
LOGIN_SWITCH = ("Task Manager > Startup apps" if WINDOWS else "System Settings > Login Items" if MAC
                else "Startup Applications")


def area_app(found: dict, plan: Plan) -> None:
    screen("Running the app")
    state, where = found["login"], found.get("login_elsewhere") or LOGIN_SWITCH
    row("Running now", "yes" if found.get("app_running") else "no",
        "success" if found.get("app_running") else "text")
    row("Start at sign-in", {None: "not available on this system", "on": "on", "off": "off"}.get(
        state, f"off: turned off in {where}"), "success" if state == "on" else "text")
    line("The app is the tray icon and the map of your repositories, on this computer. Starting it at "
         f"sign-in keeps it watching. It appears in {LOGIN_SWITCH} like any other start-up item; "
         "switching it there is noticed here and in the tray menu.", "muted")
    if not plan.desktop_after:
        line(f"The app needs the desktop app ({step('The desktop app')}).", "warning")
        return
    if state is not None:
        _sign_in_choice(plan, state, where)
    if plan.enrolled_after:
        _fetch_choice(plan, found.get("fetch_minutes"))
    if found.get("app_running"):
        line("The app is running. To use what setup changes, quit it from its tray menu and start it "
             "again (gitso tray).", "muted")
    else:
        line("Starting it is offered once setup has applied your choices: the first scan.", "muted")


FETCH_CHOICES = (("d", "Once a day", 1440, "Recommended."),
                 ("h", "Every hour", 60, ""),
                 ("n", "Only when you ask", 0, "From the tray's menu: Preview catch-up (fresh fetch)."))


def fetch_words(minutes: int) -> str:
    return {0: "only when you ask", 60: "every hour", 1440: "once a day"}.get(minutes, f"every {minutes} minutes")


def _fetch_choice(plan: Plan, current: int | None) -> None:
    """How often the app checks GitHub for new commits (a read-only fetch of every repository)."""
    say()
    line("Checking GitHub for new commits: the app fetches each repository's remote, read-only "
         "(your branches and files never change), so the map can say what is behind. How often?"
         + (f" Now: {fetch_words(current)}." if current is not None else ""), "muted")
    for key, label, _minutes, hint in FETCH_CHOICES:
        option(key.upper(), label, hint)
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    default = {minutes: key for key, _label, minutes, _hint in FETCH_CHOICES}.get(current, "d")
    answer = choose("dhn0", default)
    if answer == "0":
        raise Stop
    minutes = next(minutes for key, _label, minutes, _hint in FETCH_CHOICES if key == answer)
    if minutes != current:
        plan.add("Checking GitHub", f"Checking GitHub for new commits: {fetch_words(minutes)}",
                 lambda: _set_fetch(minutes))


def _set_fetch(minutes: int) -> str:
    from Special._sync.enrollment import set_fetch_minutes
    set_fetch_minutes(minutes)
    return fetch_words(minutes)


def _sign_in_choice(plan: Plan, state: str, where: str) -> None:
    say()
    if state == "on":
        option("K", "Keep starting at sign-in")
        option("R", "Remove it", "gitSpecOps no longer starts when you sign in; the entry is deleted.")
        keys, default = "kr0", "k"
    elif state == "elsewhere":
        option("T", "Turn it back on", f"It was turned off in {where}; this turns it on there again.")
        option("K", f"Leave it off in {where}")
        option("R", "Remove the entry", f"It disappears from {where} too.")
        keys, default = "tkr0", "k"
    else:
        option("A", "Start gitSpecOps when you sign in", "One entry for your account only. Remove it "
               f"here any time, or switch it off in {LOGIN_SWITCH}.")
        option("N", "Not now")
        keys, default = "an0", "a"
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    answer = choose(keys, default)
    if answer == "0":
        raise Stop
    if answer in ("a", "t"):
        plan.add("Start at sign-in", "Start at sign-in: " + ("add one entry for your account" if answer == "a"
                                                              else f"turn it back on in {where}"),
                 lambda: _start_at_login(True))
    elif answer == "r":
        plan.add("Start at sign-in", "Start at sign-in: remove the entry", lambda: _start_at_login(False))


def _start_at_login(enable: bool) -> str:
    command = [str(VENV_PYTHON), str(ROOT / "Elaborate" / "start_at_sign_in.py"), "enable" if enable else "disable"]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors="replace")
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip()
                           else "start at sign-in could not be changed")
    return "on" if enable else "entry removed"


def area_client(found: dict, plan: Plan) -> None:
    from Special._sync.git_client import LABELS
    screen("Desktop Git app")
    names = {key: LABELS.get(key, key) for key in found["clients"]}
    row("Found", ", ".join(names.values()) or "none (Sourcetree, GitHub Desktop)")
    row("Connected", names.get(found["client"], "none"))
    line("The web view can open any repository in your desktop Git app.", "muted")
    if not names or not plan.enrolled_after:
        if names:
            line(f"Connecting is saved with a library folder ({step('This machine')}).", "warning")
        return
    say()
    keys = list(names)
    for number, key in enumerate(keys, 1):
        option(str(number), names[key] + ("  (connected)" if key == found["client"] else ""))
    option("N", "None")
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    current = str(keys.index(found["client"]) + 1) if found["client"] in keys else "1"
    answer = choose("".join(str(n) for n in range(1, len(keys) + 1)) + "n0", current)
    if answer == "0":
        raise Stop
    chosen = "" if answer == "n" else keys[int(answer) - 1]
    if chosen != found["client"]:
        plan.add("Desktop Git app", f"Desktop Git app: {names.get(chosen, 'none')}",
                 lambda: _save_client(found["clients"].get(chosen)))


def _save_client(choice) -> str:
    from Elaborate._fleet.cli import load_saved
    from Elaborate._fleet.config import save_client_choice
    from Special._settings.fleet import fleet_directory
    directory = fleet_directory()
    save_client_choice(directory, load_saved(directory), dict(choice) if choice else None)
    return "saved"


def area_protection(found: dict, plan: Plan) -> None:
    screen("Protection")
    anywhere = found["protected"].get("never_publish", [])
    words = found["protected"].get("never_publish_words", [])
    row("Protected values", f"{len(anywhere) + len(words)}" + (f" ({len(words)} whole word only)" if words else ""))
    line("Protected values are things that must never be published. A checked commit or push stops "
         "anything that contains one, and scans report them. The list stays on this computer.", "muted")
    say()
    line("Worth adding:", "muted")
    for tip in PROTECTION_TIPS:
        bullet(tip, "muted")
    line("Leave out your GitHub handle, and a Git name or email that is already public: every commit "
         "carries those, so protecting one would stop every commit.", "muted")
    say()
    line(f"Change the list any time: run setup again (Set up one part, then Protection), use the "
         f"Security tab in the app, or edit the never_publish lists in the \"security\" section of {settings_file()}.", "muted")
    retired = commit_identity(found, plan)
    if not plan.enrolled_after and not found["protected"]:
        line("Protected values are saved with this machine's settings, which a library folder "
             f"creates ({step('This machine')}).", "warning")
        return
    known = {v.casefold() for v in anywhere + words}
    suggestions = []
    login = found.get("gh_login", "").casefold()
    # Never the public GitHub login or a commit identity still in use: every commit carries those,
    # so protecting one would hold every commit. A private name or email is suggested once commits
    # stop carrying it (commit_identity above).
    for label, value in retired + [("This computer's user name", found["user"])]:
        if value and value.casefold() not in known and value.casefold() != login \
                and value not in [v for _l, v in suggestions]:
            suggestions.append((label, value))
    adding = []
    for label, value in suggestions:
        short = len(value) < 6 or " " not in value and "@" not in value
        if yes_no(f"Protect {label.lower()}, {value}?", "y",
                  f"Matched only as a separate word, so longer words that contain \"{value}\" are not "
                  "flagged." if short else "Matched anywhere in text."):
            adding.append((value, short))
    while True:
        say()
        option("A", "Add another value")
        option("N", "Done")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        answer = choose("an0", "n")
        if answer == "0":
            raise Stop
        if answer == "n":
            break
        value = ask("Value:")
        if value:
            # A name with a space or an email address is matched anywhere. Only a single short
            # word needs the choice: "pat" anywhere would also match "pattern".
            whole = (len(value) < 6 or " " not in value and "@" not in value) and yes_no(
                f"Match {value} only as a separate word?", "y",
                f"Yes: \"{value}\" on its own. No: also inside longer words, which flags much more text.")
            adding.append((value, whole))
            line("Will be added when you apply.", "success")
    for value, whole in adding:
        plan.add("Protected value", f"Protect {value} ({'whole word only' if whole else 'anywhere in text'})",
                 lambda value=value, whole=whole: _protect(value, whole))


PROTECTION_TIPS = (
    "Your full name as you write it, such as \"Pat Example\". Add your last name on its own too if it "
    "is uncommon. Your first name alone usually matches too much ordinary text.",
    "Other names: nicknames, a former name, family members' names.",
    "Every email address you use, old ones included.",
    "Usernames on other sites, and this computer's user name.",
    "Your street address and phone numbers.",
)


def settings_file() -> str:
    """Where the protected values are saved, for a person to open."""
    from Special._settings import SETTINGS_NAME, SettingsError, select_home
    try:
        return str(Path(select_home()[0]) / SETTINGS_NAME)
    except SettingsError:
        return f"{SETTINGS_NAME} in your gitSpecOps settings folder"


def commit_identity(found: dict, plan: Plan) -> list[tuple[str, str]]:
    """Show the name and email every commit carries; offer public ones in place of private ones.

    Returns the private values commits will stop carrying, for protection. A private value still
    in use is not offered for protection: every commit would then be held.
    """
    login, name, email = found.get("gh_login", ""), found["git_name"], found["git_email"]
    if not (name or email):
        return []
    say()
    line("Every commit carries your Git name and email, and history keeps them for good. Commit "
         "under public ones: your GitHub handle and GitHub's no-reply address.", "muted")
    retired = []
    if name:
        if public_git_name(name, login):
            row("Git name", f"{name}  (public)", "success")
        else:
            row("Git name", name, "warning")
            if login and yes_no(f"Commit as {login} instead of {name}?", "y",
                                "Sets Git's user.name for your account (git config --global). Commits "
                                "already made keep the name they were made with."):
                plan.add("Git name", f"Git name: commit as {login} (git config --global user.name)",
                         lambda: _git_identity("user.name", login))
                retired.append(("Your old Git name", name))
            else:
                line("Not protected while commits carry it: that would hold every commit.", "muted")
    if email:
        if public_git_email(email):
            row("Git email", f"{email}  (public)", "success")
        else:
            row("Git email", email, "warning")
            address = noreply_address(login, found.get("gh_id", ""))
            if not address:
                line("Your no-reply address is on https://github.com/settings/emails, with \"Keep my "
                     "email addresses private\" turned on. It ends in " + NOREPLY_DOMAIN + ".", "muted")
                typed = ask("Paste it to commit with it, or press Enter to keep your current email:")
                address = typed if public_git_email(typed) else ""
                if typed and not address:
                    line("That is not a GitHub no-reply address; your email is unchanged.", "warning")
            if address and yes_no(f"Commit as {address} instead of {email}?", "y",
                                  "Sets Git's user.email for your account (git config --global). Commits "
                                  "already made keep the email they were made with."):
                plan.add("Git email", f"Git email: commit as {address} (git config --global user.email)",
                         lambda: _git_identity("user.email", address))
                retired.append(("Your old Git email", email))
            else:
                line("Not protected while commits carry it: that would hold every commit.", "muted")
    return retired


def _git_identity(key: str, value: str) -> str:
    if subprocess.call(["git", "config", "--global", key, value]) != 0:
        raise RuntimeError(f"git config --global {key} did not finish")
    return "set"


def _protect(value: str, whole: bool) -> str:
    from Special._security._policy_edit import policy_change
    policy_change(None, {"list": "never_publish_words" if whole else "never_publish", "add": [value]})
    return "added"


def area_scanners(found: dict, plan: Plan) -> None:
    screen("Scanners")
    for name in SCANNERS:
        state = ("installed, used in scans" if found[name] and name in found["engines"] else
                 "installed, not used" if found[name] else "not installed")
        row(name, state, "success" if name in found["engines"] else "text")
    line("gitSpecOps' own checks always run. A scanner adds hundreds of kinds of keys and tokens, "
         "across full history. Only use what is installed: a chosen scanner that is missing makes "
         "every scan incomplete, and an incomplete scan holds a publish.", "muted")
    installing = []  # a scanner you choose to install is used in every scan: one decision, not two
    for name, about in SCANNERS.items():
        if found[name]:
            continue
        say()
        line(f"{name}: {about}", "muted")
        if offer_install(plan, name, name, f"gitSpecOps will use it whenever it checks for secrets: {SCANS}."):
            installing.append(name)
    installed = [name for name in SCANNERS if found[name]]
    if not (installed or installing):
        return
    if not plan.enrolled_after and not found["protected"]:
        line(f"Which scanners to use is saved with this machine's settings ({step('This machine')}).", "warning")
        return
    chosen = list(installing)
    for name in installed:
        if yes_no(f"{name} is already installed. Use it whenever gitSpecOps checks for secrets?",
                  "y" if name in found["engines"] or name == "gitleaks" else "n", f"That is: {SCANS}."):
            chosen.append(name)
    chosen = [name for name in SCANNERS if name in chosen]
    if sorted(chosen) != sorted(found["engines"]):
        plan.add("Scanners used", "Scanners used in scans: " + (", ".join(chosen) or "gitSpecOps' own checks only"),
                 lambda: _select_engines(chosen))


def _select_engines(chosen) -> str:
    from Special._settings.security import load_security_settings, save_security_settings
    from Basic._paths import find_program
    missing = [name for name in chosen if not find_program(name)]
    if missing:
        raise RuntimeError(f"not installed: {', '.join(missing)} (open a new terminal and run setup again)")
    save_security_settings(load_security_settings(), {"engines": list(chosen)})
    return ", ".join(chosen) or "own checks only"


def _archives() -> list:
    try:
        from Special._archive.manager import registry_record
        return registry_record(False)["archives"]
    except (OSError, ValueError, KeyError):
        return []


def area_archives(found: dict, plan: Plan) -> None:
    from Special._archive.manager import registration_plan
    screen("Archives")
    for item in found["archives"]:
        row("Archive", f"{item['root']}  ({'update' if item['mode'] == 'update' else 'update and clone missing'})")
    if not found["archives"]:
        row("Archives", "none yet")
    line("An archive is a folder full of clones you want kept current: a copy of every repository "
         "of a GitHub organization, say. gitSpecOps fast-forwards each clone (it never merges, "
         "resets or deletes) and, if you choose, clones repositories that are new on GitHub. Each "
         "archive gets a small launcher in its folder; a monthly task can run them all.", "muted")
    added = []
    while True:
        say()
        option("P", "Add a folder of clones by its path")
        option("N", "Done" if (added or found["archives"]) else "No archives now")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        answer = choose("pn0", "n")
        if answer == "0":
            raise Stop
        if answer == "n":
            break
        path = ask("Folder of clones:")
        if not path:
            continue
        folder = Path(path).expanduser()
        if not folder.is_dir():
            line("That folder does not exist.", "warning")
            continue
        say()
        option("1", "Keep the clones already there current", "Fast-forward only.")
        option("2", "Also clone repositories that are missing", "Compared with the GitHub owner of the clones.")
        mode = "sync" if choose("12", "1") == "2" else "update"
        line("Reading the folder (nothing changes)...", "detail")
        try:
            proposal = registration_plan(folder, None, mode)
        except (ValueError, OSError) as exc:
            line(f"Not added: {exc}.", "warning")
            continue
        count = len(proposal["repositories"])
        added.append(proposal["root"])
        line(f"Will add {proposal['root']}: {count} repositories it can keep current.", "success")
        plan.add("Archive", f"Archive: register {proposal['root']} "
                 f"({'update' if mode == 'update' else 'update and clone missing'}; {count} repositories) "
                 "and write its launcher there. Nothing is pulled or cloned now.",
                 lambda folder=folder, mode=mode, repos=proposal["repositories"]: _register_archive(folder, mode, repos))
    if (added or found["archives"]) and yes_no(
            "Refresh every archive once a month?", "n",
            "A scheduled task for your account, on the 1st of each month at 09:00, each archive in its "
            "own mode. Remove it any time: archive schedule --remove-task."):
        plan.add("Monthly refresh", "Monthly refresh: a scheduled task for your account runs every archive "
                 "on the 1st of each month at 09:00.", _schedule_archives)


def _register_archive(folder, mode, repos) -> str:
    from Special._archive.manager import install_launchers
    record = install_launchers(folder, None, prevalidated_repos=repos, mode=mode)
    return f"{record.root} ({record.mode})"


def _schedule_archives() -> str:
    from Elaborate.archive_schedule import DEFAULT_TASK_NAME, install_monthly_task
    if install_monthly_task(DEFAULT_TASK_NAME, 1, "09:00"):
        raise RuntimeError("the scheduled task was not created")
    return "1st of each month, 09:00"


SCANS = ("before a checked commit or push, in gitso scan and gitso history scan, and in the "
         "app's Security tab")


CONNECTIONS = (  # (name, what kind, what it does): the list and each question use the same words
    ("Tailscale", "Live",
     "Your machines ask each other for their status every few minutes (you choose), directly, "
     "between your own devices."),
    ("A synced folder", "In between",
     "A small status file every 5 minutes, in a folder a sync service already copies to your "
     "machines: OneDrive, Syncthing, an Obsidian Sync vault and others. The service's provider can "
     "read the file."),
    ("A GitHub state repository", "Durable, kept while every machine is off; experimental and untested",
     "A private repository written through your gh sign-in. GitHub can read it."),
)
FLEET_FOLDER = "gitSpecOps fleet"


def area_fleet(found: dict, plan: Plan) -> None:
    from Elaborate._fleet.setup_state import leave_fleet
    screen("Fleet")
    has_tailscale = bool(found["tailscale"] or found["tailnet"])
    current = found["fleet"]
    row("Tailscale", "connected" if found["tailnet"] else "installed, not connected" if found["tailscale"]
        else "not installed (optional)", "success" if found["tailnet"] else "text")
    row("Synced folders", ", ".join(found["synced_folders"]) or "none found")
    if current:
        row("This machine", f"in the fleet {found.get('fleet_name') or '(unnamed)'}, connected by "
            + ", ".join(_connection_names(current)), "success")
    else:
        row("This machine", "on its own")
    line("A fleet is your machines watching each other: every machine's map shows every copy of every "
         "repository. Never shared: file contents, folder paths, web addresses, commit messages. "
         "Machines connect in up to three ways; choose any combination, each is another place a "
         "machine leaves its last report:", "muted")
    for name, kind, about in CONNECTIONS:
        bullet(f"{name}. {kind}. {about}", "muted")
    if not has_tailscale:
        line(f"Tailscale is free for personal use: {HOME_PAGES['tailscale']}. Run setup again after "
             "installing it to connect over it.", "muted")
    if not plan.enrolled_after:
        line(f"A fleet needs a library folder on this machine ({step('This machine')}).", "warning")
        return
    say()
    if current:
        option("K", "Keep the fleet as it is")
        option("C", "Change how this machine connects", "Tailscale, a synced folder, the state repository.")
        option("R", "Rename the fleet", "Every machine in it takes the new name.")
        option("S", "Show this machine's fleet key", "Only for a machine without Tailscale: on Tailscale, "
               "other machines join the fleet by its name. It appears in this window only.")
        option("L", "Leave the fleet", "This machine keeps its libraries and map.")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        answer = choose("kcrsl0", "k")
        if answer == "r":
            name = ask("New name for the fleet:", found.get("fleet_name") or "")
            if name.strip():
                plan.add("Fleet", f"Fleet: rename to {name.strip()}", lambda: _rename_fleet(name))
            return
        if answer == "0":
            raise Stop
        if answer == "s":
            if ask("Anyone, or any program reading this window, who has the key can join your fleet. "
                   "Type SHOW to print it:") == "SHOW":
                _show_fleet_key()
                ask("Press Enter when you have copied it:")
        elif answer == "l":
            plan.add("Fleet", "Fleet: leave (this machine keeps its libraries)", lambda: (leave_fleet(), "left")[1])
            _browser_reach(found, plan, False)
            return
        elif answer == "c":
            chosen = _choose_connections(found, has_tailscale, current)
            if chosen is None:
                return
            tailnet, folder, repo, create, seconds = chosen
            if not (tailnet or folder or repo):
                plan.add("Fleet", "Fleet: no connections left; this machine leaves the fleet",
                         lambda: (leave_fleet(), "left")[1])
                _browser_reach(found, plan, False)
                return
            names = _ask_names(tailnet, folder, repo, current)
            plan.add("Fleet", "Fleet: connect by " + ", ".join(_described(tailnet, folder, repo, create, names,
                                                                          seconds)),
                     lambda: _set_connections(current, tailnet, folder, repo, create, names, seconds))
            _offer_sealing(plan, bool(folder))
            _browser_reach(found, plan, tailnet)
            return
        _offer_sealing(plan, "folder" in current)
        _browser_reach(found, plan, "tailnet" in current)
        return
    option("1", "Start a fleet with this machine", "You name it; your other machines then join it by "
           "that name over Tailscale.")
    option("2", "Join a fleet", "One your other machines are in: found by name on Tailscale.")
    option("N", "Not now")
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    answer = choose("12n0", "n")
    if answer == "0":
        raise Stop
    if answer == "n":
        return
    key, name, named_at = None, None, None
    if answer == "1":
        name = " ".join(ask("Name the fleet:", "My fleet").split())[:60] or "My fleet"
    if answer == "2":
        joined = _ask_join(found)
        if joined is None:
            line("Not joining a fleet; nothing will change. Run setup again to join.", "warning")
            return
        key, named = joined
        if named:
            name, named_at = named.get("name"), named.get("at")
    chosen = _choose_connections(found, has_tailscale, {})
    if chosen is None:
        return
    tailnet, folder, repo, create, seconds = chosen
    if not (tailnet or folder or repo):
        line("A fleet needs at least one connection. Nothing will change.", "warning")
        return
    names = _ask_names(tailnet, folder, repo, {})
    ways = ", ".join(_described(tailnet, folder, repo, create, names, seconds))
    which = f"join {name}" if key and name else "join the fleet of that key" if key else f"start {name}"
    plan.add("Fleet", f"Fleet: {which}, connected by {ways}",
             lambda: _start_fleet(key, tailnet, folder, repo, create, names, seconds, name, named_at))
    _offer_sealing(plan, bool(folder))
    _browser_reach(found, plan, tailnet)


def _offer_sealing(plan: Plan, has_folder: bool) -> None:
    """Protected values are shared with the fleet over Tailscale already. Through a synced folder
    (someone else's servers) only sealed: optional, off unless chosen here or in the app."""
    from Elaborate._fleet.sealed import venv_has
    from Special._sync.enrollment import _snapshot
    say()
    line("Your protected values are shared with your other machines over Tailscale: one added on any "
         "machine is added on all; one removed, or an allowed value added, is asked about on the "
         "others (App & setup tab).", "muted")
    if not has_folder:
        return
    try:
        config = _snapshot(None).config("app") or {}
    except Exception:  # noqa: BLE001 - not enrolled yet: the question still applies
        config = {}
    if config.get("seal_settings"):
        line("They also go through the synced folder, sealed.", "muted")
        return
    installed = venv_has("cryptography")
    if not yes_no("Also share them through the synced folder, sealed?", "n",
                  "Sealed with a key made from the fleet key, so the sync service cannot read them. "
                  + ("" if installed else "Installs the cryptography package into this folder's .venv. ")
                  + "Without it, Tailscale alone carries them."):
        return
    plan.add("Fleet", "Shared protected values: also through the synced folder, sealed"
             + ("" if installed else " (installs cryptography into this folder's .venv)"), _seal_on, loud=not installed)


def _seal_on() -> str:
    from Elaborate._fleet import sealed
    from Special._sync.enrollment import set_seal_settings
    done = [] if sealed.venv_has("cryptography") else [sealed.install()]
    set_seal_settings(True)
    return "; ".join([*done, "sealed through the synced folder; the app uses it when it restarts"])


def _show_fleet_key() -> None:
    """The key alone on one line, never wrapped, so it copies whole."""
    from Special._settings.fleet import load_fleet_settings
    snapshot = load_fleet_settings()
    secret = ((snapshot.document if snapshot is not None else {}).get("machine") or {}).get("fleet_secret")
    if not secret:
        line("This machine has no fleet key yet.", "warning")
        return
    say()
    line("The fleet key is the line below. Copy all of it; setup on the other machine also "
         "accepts it in parts if it wraps.", "muted")
    say()
    print(secret, flush=True)
    say()


def _ask_join(found: dict) -> tuple[str, dict | None] | None:
    """(fleet key, fleet name) to join, or None to not join.

    On Tailscale the fleets your machines are in are listed by name and one is chosen: a machine
    in it hands over the key (setup_state.key_from_fleet). Nobody copies a key (the user,
    2026-11-16: a pasted key failed twice). Pasting stays for a machine without Tailscale; a key
    copied over two lines is collected in parts, and anything wrong is asked again."""
    if found.get("tailnet"):
        from Elaborate._fleet.setup_state import fleets_on_tailnet, key_from_fleet
        try:
            fleets = fleets_on_tailnet()
        except (OSError, ValueError) as exc:
            line(f"Could not look on Tailscale ({exc}).", "warning")
            fleets = []
        if not fleets:
            line("No fleet is answering on your tailnet. On a machine in the fleet, the app must be "
                 "running with Tailscale as one of its connections; then run this again.", "warning")
        for number, fleet in enumerate(fleets[:9], 1):
            option(str(number), fleet["name"], "on " + ", ".join(fleet["machines"]))
        option("K", "Paste a fleet key instead", "Only needed without Tailscale.")
        option("0", "Do not join")
        answer = choose("".join(str(n) for n in range(1, min(len(fleets), 9) + 1)) + "k0",
                        "1" if fleets else "0")
        if answer == "0":
            return None
        if answer != "k":
            fleet = fleets[int(answer) - 1]
            try:
                secret, named = key_from_fleet(fleet["fleet_id"])
            except ValueError as exc:
                line(str(exc), "warning")
                return None
            line(f"Joining {fleet['name']}: {fleet['machines'][0]} handed over what is needed.", "success")
            return secret, named
    key = _ask_fleet_key()
    return None if key is None else (key, None)


def _ask_fleet_key() -> str | None:
    import re
    collected, prompt = "", ("Paste the fleet key: 64 characters, not the 16-character fleet ID "
                             "(Enter alone: do not join):")
    while True:
        text = re.sub(r"[\s-]", "", ask(prompt))
        if not text:
            return None
        if not re.fullmatch(r"[0-9a-fA-F]+", text):
            line("A fleet key has only digits and the letters a to f. Paste only the key.", "warning")
            collected, prompt = "", "Paste the fleet key (Enter alone: do not join):"
            continue
        collected += text
        if len(collected) == 64:
            return collected.lower()
        if len(collected) > 64:
            line(f"That is {len(collected)} characters; a fleet key has 64. Paste it again.", "warning")
            collected, prompt = "", "Paste the fleet key (Enter alone: do not join):"
            continue
        prompt = (f"{len(collected)} of 64 so far: a key copied over two lines arrives in parts. "
                  "Paste the rest (Enter alone: do not join):")


def _connection_names(transports: dict) -> list[str]:
    return [{"tailnet": "Tailscale", "folder": "a synced folder",
             "repo": "the state repository (experimental)"}.get(name, name) for name in transports]


def _described(tailnet, folder, repo, create, names=None, seconds=None) -> list[str]:
    names = names or {}

    def carried(key):
        return "" if key not in names else ", with names" if names[key] else ", ids only"
    every = (f" every {seconds // 60} minute{'s' if seconds != 60 else ''}" if seconds else "")
    return [part for part in (
        f"Tailscale{every}{carried('tailnet')}" if tailnet else "",
        f"a synced folder ({folder}{carried('folder')})" if folder else "",
        (f"the state repository {repo} ({'create it, private' if create else 'existing'}; experimental"
         f"{carried('repo')})" if repo else "")) if part]


# Repository names per connection: over Tailscale only your own devices see them; a synced
# folder's provider and GitHub could read them, so those carry unnamed ids unless chosen.
NAMES_DEFAULT = {"tailnet": True, "folder": False, "repo": False}


def _ask_names(tailnet, folder, repo, current: dict) -> dict:
    """Whether each chosen connection carries repository names. The current choice is the default."""
    asked = [(key, label, reader) for key, on, label, reader in (
        ("tailnet", tailnet, "over Tailscale", "only your own devices"),
        ("folder", folder, "through the synced folder", "the sync service's provider, too"),
        ("repo", repo, "to the state repository", "GitHub, too")) if on]
    if not asked:
        return {}
    say()
    line("Repository names: Yes shows other maps which repository is which, with its branch and "
         "commit. No sends unnamed ids: your machines still see what is ahead, behind or unpushed. "
         "Never sent either way: folder paths, web addresses, file names, contents, commit messages.",
         "muted")
    names = {}
    for key, label, reader in asked:
        default = (current.get(key) or {}).get("names", NAMES_DEFAULT[key])
        names[key] = yes_no(f"Send repository names {label}?", "y" if default else "n",
                            f"Who could read them: {reader}.")
    return names


def _choose_connections(found: dict, has_tailscale: bool, current: dict):
    """Ask about each connection. Returns (tailnet, folder, repo, create_repo), or None to stop."""
    say()
    tailnet = has_tailscale and yes_no("Connect over Tailscale?", "y" if not current or "tailnet" in current
                                       else "n", f"{CONNECTIONS[0][1]}. {CONNECTIONS[0][2]}")
    if tailnet and not found["tailnet"]:
        line("Tailscale is installed but not connected; sign in to Tailscale for your machines to see "
             "each other.", "warning")
    seconds = _ask_poll_seconds((current.get("tailnet") or {}).get("seconds")) if tailnet else None
    folder = (current.get("folder") or {}).get("path", "")
    if yes_no("Connect through a synced folder?", "y" if folder or (not current and not tailnet) else "n",
              f"{CONNECTIONS[1][1]}. {CONNECTIONS[1][2]}"):
        folder = _pick_synced_folder(found, folder)
    else:
        folder = ""
    repo, create = (current.get("repo") or {}).get("name", ""), False
    if found.get("gh_signed_in") and yes_no(
            "Also keep status in a GitHub state repository? Experimental and untested.",
            "y" if repo else "n", f"Kept while every machine is off. {CONNECTIONS[2][2]} Say no unless "
            "you want to test it."):
        repo, create = _pick_state_repo(found, repo)
    elif not found.get("gh_signed_in"):
        line("The state repository needs a GitHub sign-in (step 1); not offered.", "muted")
        repo = ""
    else:
        repo = ""
    return bool(tailnet), folder, repo, create, seconds


POLL_CHOICES = (("1", "Every minute", 60), ("5", "Every 5 minutes", 300), ("3", "Every 30 minutes", 1800))


def _ask_poll_seconds(current) -> int:
    """How often machines ask each other for their status over Tailscale."""
    say()
    line("How often should your machines ask each other for their status? Each ask is a small "
         "request over Tailscale, never a Git command.", "muted")
    for key, label, seconds in POLL_CHOICES:
        option(key, label, "Recommended." if seconds == 300 else "")
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    default = {seconds: key for key, _label, seconds in POLL_CHOICES}.get(current, "5")
    answer = choose("1530", default)
    if answer == "0":
        raise Stop
    return next(seconds for key, _label, seconds in POLL_CHOICES if key == answer)


def _pick_synced_folder(found: dict, current: str) -> str:
    """A folder of its own inside a synced folder: setup creates it when the change is applied."""
    roots = found["synced_folders"]
    say()
    for number, root in enumerate(roots, 1):
        option(str(number), str(Path(root) / FLEET_FOLDER), f"A new folder inside {root}.")
    option("P", "Another folder, by its path", "Any folder your sync service copies, such as one in an "
           "Obsidian Sync vault. It must already exist.")
    keys = "".join(str(n) for n in range(1, min(len(roots), 9) + 1)) + "p"
    default = "1" if roots else "p"
    if current:
        line(f"Now: {current}. Enter keeps it.", "muted")
        answer = ask(f"Choose [{'Enter' if current else default.upper()}]:", "")
        if not answer:
            return current
    else:
        answer = choose(keys, default)
    if answer.lower() == "p":
        path = ask("Folder path:")
        return path if path and Path(path).expanduser().is_dir() else ""
    if answer.isdigit() and 1 <= int(answer) <= len(roots):
        return str(Path(roots[int(answer) - 1]) / FLEET_FOLDER)
    return ""


def _pick_state_repo(found: dict, current: str) -> tuple[str, bool]:
    """owner/name, and whether to create it. The suggestion creates nothing until applied."""
    suggestion = current or f"{found.get('gh_login') or 'you'}/gitspecops-state"
    name = ask(f"Repository [{suggestion}]:", suggestion)
    exists = _run(["gh", "repo", "view", name, "--json", "name"])[0] == 0
    if exists:
        line(f"{name} exists: it is used only if it is private and you can write to it.", "muted")
        return name, False
    line(f"{name} does not exist yet: it will be created, private, when you apply.", "muted")
    return name, True


def _start_fleet(key, tailnet, folder, repo, create, names, seconds=None, name=None, named_at=None) -> str:
    from Elaborate._fleet.setup_state import join_fleet
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
    state = join_fleet(key=key, folder=folder or None, tailnet=tailnet, repo=repo or None, create_repo=create,
                       names=names, tailnet_seconds=seconds, name=name, named_at=named_at)
    fleet = state.get("fleet") or {}
    return f"in the fleet {fleet.get('name') or ''} ({fleet.get('fleet_id')})".replace("  ", " ")


def _rename_fleet(name: str) -> str:
    from Elaborate._fleet.setup_state import name_fleet
    return f"renamed to {name_fleet(name=name)['name']}; the other machines take it on their next round"


def _set_connections(current: dict, tailnet, folder, repo, create, names=None, seconds=None) -> str:
    from Elaborate._fleet.cli import load_saved
    from Elaborate._fleet.setup_state import apply_transports
    from Special._settings.fleet import fleet_directory
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
    directory = fleet_directory()
    apply_transports(load_saved(directory), tailnet=tailnet, clear_tailnet=not tailnet,
                     folder=folder or None, clear_folder=not folder and "folder" in current,
                     repo=repo or None, create_repo=create, clear_repo=not repo and "repo" in current,
                     directory=directory, names=names, tailnet_seconds=seconds)
    return "connected by " + ", ".join(_described(tailnet, folder, repo, create, names, seconds))


def _browser_reach(found: dict, plan: Plan, over_tailscale: bool) -> None:
    """Separate from the fleet: whether a browser on another Tailscale device may open this
    machine's map. Machines in the fleet do not need it; they each show the fleet themselves."""
    from Special._sync.enrollment import set_presentation
    now = found["web"] == "tailnet"
    want = over_tailscale and yes_no(
        "Let your other Tailscale devices, such as a phone, open this machine's map in a browser?",
        "y" if now else "n",
        "Nothing opens by itself: the map is served at this machine's Tailscale address, port 8770, "
        "for your devices to visit when you choose. Your fleet machines do not need this; each shows "
        "the fleet on its own map. Only devices in your own tailnet can reach it.")
    if want != now:
        web = "tailnet" if want else "loopback"
        plan.add("Map in a browser", "Map in a browser: " + ("this computer and your Tailscale devices" if want
                                                             else "this computer only"),
                 lambda: str(set_presentation(face=found["face"], web=web)["web"]))


# --------------------------------------------------------------------------- review and apply
def review(plan: Plan, enrolled: bool, again: str = "Back to the start of the walkthrough") -> str:
    banner("Setup  /  Review", tagline=True)
    if not plan.changes:
        notice("Nothing to change", "Everything is as you chose.", "success")
        say()
        option("0", "Close")
        choose("0", "0")
        return "0"
    notice("These changes will be made", "", "accent")
    for change in plan.changes:
        bullet(change.review)
    say()
    line("For your account only. Not changed: your repositories, your files, anything else.")
    say()
    key = "a" if enrolled else "i"
    option(key.upper(), "Apply" if enrolled else "Install")
    option("B", again)
    option("0", "Cancel", "Nothing has been changed.")
    answer = choose(key + "b0", "0")
    return "apply" if answer == key else answer


def apply(plan: Plan, done: tuple[str, str] = ("Setup complete", "gitSpecOps is set up on this computer."),
          title: str = "Applying") -> bool:
    banner(f"Setup  /  {title}", f"folder: {ROOT}")
    say()
    steps = Steps(len(plan.changes))
    def run(change):
        try:
            return "changed", str(change.apply())
        except Skipped as skipped:
            return "skipped", str(skipped)
    for change in plan.changes:
        steps.run(change.title, lambda change=change: run(change), loud=change.loud)
    failed = [label for label, status, _detail in steps.results if status == "FAILED"]
    section("Summary")
    for label, status, detail in steps.results:
        bullet(f"{label}: {detail}", "error" if status == "FAILED" else "text")
    if failed:
        notice("Not finished", f"{', '.join(failed)} did not finish; the other steps are done. "
               "Run setup again to finish.", "error")
        return False
    notice(*done, "success")
    return True


# --------------------------------------------------------------------------- uninstall
def find_app_processes() -> list[int]:
    """Process ids of this folder's tray app (its peer included). Only looks."""
    target = str(ROOT / "App" / "tray.py")
    if WINDOWS:
        script = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { "
                  f"$_.CommandLine -like '*{target.replace(chr(39), chr(39) * 2)}*' }} | "
                  "ForEach-Object { $_.ProcessId }")
        code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    else:
        code, out = _run(["ps", "-ax", "-o", "pid=,command="])
        out = "\n".join(entry.split(None, 1)[0] for entry in out.splitlines() if target in entry)
    return sorted({int(word) for word in out.split() if word.isdigit()}) if code == 0 else []


def _stop_app(pids: list[int]) -> str:
    import signal
    for pid in pids:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    left = find_app_processes()
    if left:
        raise RuntimeError(f"still running: process {', '.join(map(str, left))}; quit it from its tray menu")
    return f"stopped ({len(pids)} process{'es' if len(pids) != 1 else ''})"


def _delete_folder(path: Path) -> str:
    shutil.rmtree(path)
    parent = path.parent
    if parent.name == ".gitspecops" and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()  # nothing of ours is left in ~/.gitspecops
    return "deleted"


def _archive_task_present() -> bool:
    if not WINDOWS:
        return False
    from Elaborate.archive_schedule import DEFAULT_TASK_NAME
    return _run(["schtasks", "/Query", "/TN", DEFAULT_TASK_NAME])[0] == 0


def _remove_archive_task() -> str:
    from Elaborate.archive_schedule import DEFAULT_TASK_NAME, remove_task
    if remove_task(DEFAULT_TASK_NAME):
        raise RuntimeError("the scheduled task was not removed")
    return "removed"


def uninstall(detector=detect) -> int:
    """Stop the app and remove what setup added, after a review. Your settings only on request."""
    from _build import gitso_command as command
    from Basic._paths import config_home, tools_home
    from Elaborate._fleet.setup_state import leave_fleet
    banner("Setup  /  Uninstall", tagline=True)
    line("Looking at this computer (nothing changes)...", "detail")
    found, pids = detector(), find_app_processes()
    state, settings, tools = found["gitso_command"], config_home(), tools_home()
    task = _archive_task_present()
    say()
    # Shown, and removed, in the reverse of setup's order: the App first, Basic last.
    row("App running", f"yes ({len(pids)} process{'es' if len(pids) != 1 else ''})" if pids else "no")
    row("Start at sign-in", {"on": "on", "elsewhere": "turned off elsewhere"}.get(found["login"], "no"))
    row("Desktop app", "installed (Qt in this folder's .venv)" if found["desktop"] else "none")
    row("Fleet", "this machine is in one" if found["fleet"] else "none")
    row("Monthly refresh", "scheduled" if task else "none")
    row("Downloaded tools", str(tools) if tools.exists() else "none")
    row("Settings", str(settings) if settings.exists() else "none")
    row("gitso alias", ", ".join(state["aliases"]) or "none")
    row("gitso command", {"here": state["folder"], "elsewhere": "another gitSpecOps folder's (left alone)"}.get(
        state["launcher"], "none"))
    delete_settings = settings.exists() and yes_no(
        "Also delete your gitSpecOps settings?", "n",
        f"{settings}: your protected values, library folders, fleet membership, logs and reports. "
        "Keep them and setup finds them again next time.")
    plan = Plan()
    if pids:
        plan.add("Stop the app", f"Stop the app: end its {len(pids)} process(es)", lambda: _stop_app(pids))
    if found["login"] in ("on", "elsewhere"):
        plan.add("Start at sign-in", "Start at sign-in: remove the entry", lambda: _start_at_login(False))
    if found["desktop"]:
        plan.add("Desktop app", "Desktop app: remove Qt from this folder's .venv (uv sync, without the app "
                 "extra)", _remove_desktop, loud=True)
    if found["fleet"] and not delete_settings:
        plan.add("Fleet", "Fleet: leave (this machine's settings are kept)", lambda: (leave_fleet(), "left")[1])
    if task:
        plan.add("Monthly refresh", "Monthly archive refresh: delete the scheduled task", _remove_archive_task)
    if tools.exists():
        plan.add("Downloaded tools", f"Downloaded tools: delete {tools}", lambda: _delete_folder(tools))
    if delete_settings:
        plan.add("Settings", f"Settings: delete {settings}", lambda: _delete_folder(settings))
    if state["aliases"]:
        plan.add("gitso alias", "gitso alias: remove the marked lines from " + ", ".join(state["aliases"]),
                 command.remove_aliases)
    if state["launcher"] == "here":
        plan.add("The gitso command", f"gitso command: delete it from {state['folder']} and take the folder off "
                 "PATH", command.remove_launchers)
    say()
    line("Not removed: this folder (delete it yourself to remove gitSpecOps completely), your "
         "repositories, and programs installed with your package manager, such as Gitleaks (winget "
         "uninstall Gitleaks.Gitleaks), Git, the GitHub CLI and uv.", "muted")
    if not plan.changes:
        notice("Nothing to remove", "Setup has nothing installed on this computer.", "success")
        return 0
    notice("These changes will be made", "", "accent")
    for change in plan.changes:
        bullet(change.review)
    say()
    option("U", "Uninstall")
    option("0", "Cancel", "Nothing has been changed.")
    if choose("u0", "0") != "u":
        notice("Cancelled", "Nothing has been changed.", "warning")
        return 0
    return 0 if apply(plan, ("Uninstalled", "What setup added is gone. Delete this folder to remove gitSpecOps "
                             "completely."), title="Uninstalling") else 1


def app_running() -> bool:
    """Whether the app is running for this profile: it holds the fleet folder's lock. Only looks;
    no lock file yet means it is not running."""
    from Special._settings.fleet import fleet_directory
    from Special._sync.lock import PEER_LOCK, TRAY_LOCK, app_lock
    try:
        directory = fleet_directory()
    except Exception:  # noqa: BLE001 - unreadable settings: say not running; never stop setup here
        return False
    for name in (TRAY_LOCK, PEER_LOCK):  # a tray whose peer stopped is still running
        if not (directory / name).exists():
            continue
        try:
            with app_lock(directory, name):
                pass
        except (ValueError, OSError):
            return True
    return False


def _start_app(wait: float = 5.0) -> str:
    """Start the tray app on its own (App._detach): closing setup's window must not close it."""
    from App._detach import start
    return start(wait=wait)


AREA_STEPS = (area_requirements, area_gitso, area_machine, area_protection, area_scanners,
              area_archives, area_fleet, area_environment, area_client, area_app)
PART_HINTS = (
    "Git, the GitHub CLI and your GitHub sign-in.",
    "gitso on your command path, and an optional shell alias.",
    "Library folders: where your repositories are.",
    "Values that must never be published.",
    "Extra secret scanners: Gitleaks, Betterleaks, TruffleHog.",
    "Folders of clones kept current.",
    "Your machines watching each other, over Tailscale or a synced folder.",
    "The tray icon and map: Qt in this folder's .venv, installed with uv.",
    "Open repositories from the map in Sourcetree or GitHub Desktop.",
    "Start the tray app now, and when you sign in.",
)
assert len(AREA_STEPS) == len(AREAS) == len(PART_HINTS)


def choose_part() -> int | None:
    """One part of the walkthrough to set up, change or repair; None goes back."""
    banner("Setup  /  One part", tagline=True)
    line("Set up, change or repair one part on its own. It shows what is there now, and nothing "
         "changes until you review it.", "muted")
    say()
    for number, (title, hint) in enumerate(zip(AREAS, PART_HINTS), 1):
        option(str(number), title, hint)
    option("0", "Back to the setup menu")
    while True:
        answer = ask(f"Part [1-{len(AREAS)}, or 0]:", "0")
        if answer == "0":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(AREAS):
            return int(answer) - 1
        line("Choose a number from the list.", "warning")


def walkthrough(detector=detect, only: int | None = None) -> int:
    """The whole walkthrough, or one part of it (`only`, an index into AREAS). Returns 0 when it
    finished or was stopped, 1 when a step failed."""
    while True:
        line("Looking at this computer (nothing changes)...", "detail")
        found = detector()
        if only is None:
            plan, steps = Plan(), AREA_STEPS
        else:  # the parts before this one are as this computer has them
            plan = Plan(enrolled_after=found["enrolled"], uv_after=bool(found["uv"]), venv_after=found["venv"],
                        desktop_after=found["desktop"])
            steps = (AREA_STEPS[only],)
        try:
            for area in steps:
                area(found, plan)
        except Stop:
            notice("Walkthrough stopped", "Nothing has been changed.", "warning")
            return 0
        answer = review(plan, found["enrolled"], "Back to the start of the walkthrough" if only is None
                        else f"Back to the start of {AREAS[only]}")
        if answer == "b":
            continue
        if answer != "apply" and plan.changes:
            notice("Cancelled", "Nothing has been changed.", "warning")
            return 0
        ok = apply(plan) if answer == "apply" else True
        if only is None:
            first_scan(plan)
        return 0 if ok else 1


def first_scan(plan: Plan) -> None:
    """After setup: read the library now? Always asked, never automatic; nothing starts on No."""
    if not plan.enrolled_after:
        return
    banner("Setup  /  First scan", tagline=True)
    line("gitSpecOps reads the Git status of every repository in your library folders. It is "
         "read-only: nothing in them changes, and nothing is fetched. Nothing starts until you choose.",
         "muted")
    running = app_running()
    app = plan.desktop_after and not running
    say()
    if running:
        line("The app is running: it already watches your library. Double-click its tray icon for the map.",
             "success")
    if app:
        option("A", "Start the app", "It reads your library, then keeps watching it. Double-click its tray "
               "icon (by the clock, or under the ^ arrow) for the map; quit it from the tray menu.")
    option("T", "Read it here, in this terminal", "Each repository as it is read, then what each one "
           "needs. Nothing keeps running afterwards.")
    option("N", "Not now", "Later: gitso machine check, or gitso tray for the app.")
    answer = choose(("a" if app else "") + "tn", "n")
    if answer == "a":
        try:
            line(_start_app(), "success")
        except RuntimeError as exc:
            line(str(exc), "error")
    elif answer == "t":
        python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
        subprocess.call([str(python), str(ROOT / "gitso.py"), "machine", "check"], cwd=ROOT)
