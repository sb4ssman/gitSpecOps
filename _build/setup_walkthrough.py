"""The setup walkthrough: find what this computer already has, ask about each part, review, apply.

Why:          a person setting up gitSpecOps should be walked through everything it can connect
              to, told what is already in place, and asked before anything happens.
Reads:        Git, the GitHub CLI and its sign-in, uv, this folder's .venv, the gitso command,
              this machine's enrollment, start at sign-in, desktop Git apps, protected values,
              the secret scanners, Tailscale, synced folders. Never a repository's contents.
May change:   nothing until the review is accepted. Then exactly what was chosen, in order:
              installs (with the system's package tool, the command shown first), the GitHub
              sign-in, the Python environment, the gitso command, library folders, the web
              view's reach, start at sign-in, the desktop Git app, protected values, the
              scanners used in scans, the fleet.
Results:      the walkthrough screens, the review, a run screen of numbered steps.
Layer:        setup (_build): uses the layers' own functions; no policy of its own.
Status:       working

Screens follow the station script design (.agents/knowledge/station-script-design.md). Every
area offers the same answers: yes, no, or stop (nothing changes). Run again, each area shows what
is already set and asks whether to keep or change it. The fleet's status repository is
experimental and untested, so setup does not offer it.
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
AREAS = ("Requirements", "Python environment", "The gitso command", "This machine", "The app",
         "Desktop Git app", "Protection", "Scanners", "Fleet")

#: Package names per installer. Missing means setup cannot install it on that system.
PACKAGES = {
    "gh": {"winget": "GitHub.cli", "brew": "gh", "apt": "gh"},
    "uv": {"winget": "astral-sh.uv", "brew": "uv"},
    "gitleaks": {"winget": "Gitleaks.Gitleaks", "brew": "gitleaks", "apt": "gitleaks"},
    "betterleaks": {"winget": "Betterleaks.Betterleaks", "brew": "betterleaks"},
    "trufflehog": {"brew": "trufflehog"},
}
HOME_PAGES = {
    "gh": "https://cli.github.com", "uv": "https://docs.astral.sh/uv/",
    "gitleaks": "https://github.com/gitleaks/gitleaks", "betterleaks": "https://github.com/betterleaks/betterleaks",
    "trufflehog": "https://github.com/trufflesecurity/trufflehog", "tailscale": "https://tailscale.com/download",
}
SCANNERS = {
    "gitleaks": "The most widely used secret scanner: keys and tokens in files and full history. "
                "Runs offline. Recommended.",
    "betterleaks": "The successor to Gitleaks, by its original author. Setup installs version 1, "
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


@dataclass
class Plan:
    changes: list = field(default_factory=list)
    libraries: list = field(default_factory=list)   # to add
    enrolled_after: bool = False
    uv_after: bool = False
    venv_after: bool = False

    def add(self, title, review, apply):
        self.changes.append(Change(title, review, apply))


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
    found["gh_login"] = _run(["gh", "api", "user", "--jq", ".login"])[1] if found["gh_signed_in"] else ""
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
    found["tailnet"] = bool(state["readiness"]["tailnet"])
    found["synced_folders"] = list(state["readiness"]["folders"])
    try:
        status = autostart.status()
        found["login"] = bool(status.get("enabled")) if status.get("supported") else None
    except (OSError, ValueError, ImportError):
        found["login"] = None
    configured = _configured_client()
    found["client"] = (configured or {}).get("id", "")
    found["clients"] = discover_clients(configured)
    found["protected"], found["engines"] = _security()
    for name in SCANNERS:
        found[name] = shutil.which(name)
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
def screen(number: int, title: str) -> None:
    banner(f"Setup  {number}/{len(AREAS)}:  {title}", tagline=True)


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


def masked(value: str) -> str:
    """A protected value as it appears on screen: enough to recognise, not to copy."""
    if len(value) <= 3:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 3) + value[-1]


def tool_row(label: str, path: str | None, missing: str) -> None:
    row(label, "found" if path else missing, "success" if path else "warning")


def offer_install(plan: Plan, name: str, label: str, why: str) -> bool:
    """Ask to install a missing program; returns whether it will be installed."""
    command = install_command(name)
    if not command:
        line(f"Setup cannot install {label} on this system. Get it at {HOME_PAGES[name]}, then run "
             "setup again.", "muted")
        return False
    if not yes_no(f"Install {label}?", "y", f"{why} Runs: {' '.join(command)}".strip()):
        return False
    plan.add(f"Install {label}", f"{label}: {' '.join(command)}", lambda: _install(command, name))
    return True


def _install(command: list[str], name: str) -> str:
    code = subprocess.call(command)
    refresh_path()
    if code != 0 and not shutil.which(name):
        raise RuntimeError(f"the installer stopped with exit code {code}")
    return "installed" if shutil.which(name) else "installed; open a new terminal to use it"


# --------------------------------------------------------------------------- the areas
def area_requirements(found: dict, plan: Plan) -> None:
    screen(1, "Requirements")
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
            plan.add("Sign in to GitHub", "GitHub sign-in: gh auth login (you answer its questions)", _gh_login)


def _gh_login() -> str:
    if subprocess.call(["gh", "auth", "login"]) != 0:
        raise RuntimeError("gh auth login did not finish")
    return "signed in"


def area_environment(found: dict, plan: Plan) -> None:
    screen(2, "Python environment")
    tool_row("uv", found["uv"], "not installed")
    row("Environment", "ready (.venv in this folder)" if found["venv"] else "not built",
        "success" if found["venv"] else "warning")
    row("Desktop app", "installed" if found["desktop"] else "not installed",
        "success" if found["desktop"] else "warning")
    line("The desktop app (tray icon and map) needs uv to install its one dependency, Qt. The "
         "command-line tools need only Python.", "muted")
    plan.uv_after = bool(found["uv"]) or offer_install(plan, "uv", "uv", "")
    if not plan.uv_after:
        line("Without uv the desktop app cannot be installed; the command-line tools still work.", "warning")
        return
    verb = "Refresh" if found["venv"] else "Build"
    if yes_no(f"{verb} this folder's Python environment with the desktop app?", "n" if found["desktop"] else "y",
              "Runs: uv sync --extra app, in this folder only."):
        plan.add("Python environment", "Python environment: uv sync --extra app (in this folder)", _build_env)
        plan.venv_after = True
    else:
        plan.venv_after = found["venv"]


def _build_env() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is not on PATH; open a new terminal and run setup again")
    if subprocess.call([uv, "sync", "--extra", "app"], cwd=ROOT) != 0:
        raise RuntimeError("uv sync did not finish")
    return ".venv ready, with the desktop app"


def area_gitso(found: dict, plan: Plan) -> None:
    screen(3, "The gitso command")
    row("gitso command", "installed" if found["gitso"] else "not installed",
        "success" if found["gitso"] else "text")
    line("gitso runs every gitSpecOps command from any terminal, in any folder: gitso commands, "
         "gitso scan-tree ., and so on. Installed with uv as its own tool; it runs this folder, so "
         "a git pull updates it. Remove it any time with: uv tool uninstall git-spec-ops", "muted")
    if found["gitso"] or not plan.uv_after:
        if not plan.uv_after:
            line("Needs uv (the previous step).", "warning")
        return
    if yes_no("Install the gitso command?", "y", f"Runs: uv tool install --editable {ROOT}"):
        plan.add("The gitso command", "gitso command: uv tool install --editable (this folder)", _install_gitso)


def _install_gitso() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is not on PATH; open a new terminal and run setup again")
    if subprocess.call([uv, "tool", "install", "--editable", str(ROOT)]) != 0:
        raise RuntimeError("uv tool install did not finish")
    return "gitso works in a new terminal"


def area_machine(found: dict, plan: Plan) -> None:
    from Special._sync.enrollment import find_libraries, whole_machine_starts
    screen(4, "This machine")
    row("Enrolled", f"yes, as {found['machine']}" if found["enrolled"] else "not yet",
        "success" if found["enrolled"] else "warning")
    for path in found["libraries"]:
        row("Library folder", path)
    line("Library folders hold your Git repositories. gitSpecOps watches the repositories in them: "
         "their names and Git status, never file contents.", "muted")
    picked, found_dirs = [], []
    while True:
        say()
        for number, item in enumerate(found_dirs, 1):
            option(str(number), f"{item['path']}  ({item['repositories']} repositories)")
        option("L", "Look for library folders in your home folder")
        option("W", "Look on every drive" if WINDOWS else "Look everywhere in your home folder")
        option("P", "Add a folder by its path")
        option("N", "Done" if (picked or found["libraries"]) else "No library folders now")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        numbers = "".join(str(n) for n in range(1, len(found_dirs) + 1))
        answer = choose("lwpn0" + numbers, "n")
        if answer == "0":
            raise Stop
        if answer == "n":
            break
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
    plan.enrolled_after = found["enrolled"] or bool(picked)


def _add_libraries(paths) -> str:
    from Special._sync.enrollment import add_libraries
    return f"{len(add_libraries(paths))} library folders"


def area_app(found: dict, plan: Plan) -> None:
    from Special._sync.enrollment import set_presentation
    screen(5, "The app")
    if found["login"] is None:
        row("Start at sign-in", "not available on this system", "detail")
    else:
        row("Start at sign-in", "on" if found["login"] else "off")
    row("Web view", "this computer and your Tailscale devices" if found["web"] == "tailnet" else "this computer only")
    line("The app is a tray icon and a web view of your repositories. Starting at sign-in keeps it "
         "watching; the web view can also be opened from your own Tailscale devices.", "muted")
    if found["login"] is not None and plan.venv_after:
        want = yes_no("Start gitSpecOps when you sign in?" if not found["login"] else
                      "Keep starting gitSpecOps when you sign in?", "y",
                      "One entry for your account only; remove it any time here." if not found["login"] else "")
        if want != found["login"]:
            plan.add("Start at sign-in", ("Start at sign-in: add one entry for your account" if want
                                          else "Start at sign-in: remove the entry"),
                     lambda: _start_at_login(want))
    elif not plan.venv_after:
        line("Start at sign-in needs the Python environment (step 2).", "warning")
    if not plan.enrolled_after:
        line("The web view's reach is saved with a library folder (step 4).", "warning")
        return
    if found["tailscale"] or found["tailnet"]:
        tailnet = yes_no("Let your own Tailscale devices open the web view?", "y" if found["web"] == "tailnet" else "n",
                         "Your phone or another of your computers; nothing outside your tailnet can.")
        web = "tailnet" if tailnet else "loopback"
        if web != found["web"]:
            plan.add("Web view", f"Web view: {'this computer and your Tailscale devices' if tailnet else 'this computer only'}",
                     lambda: str(set_presentation(face=found["face"], web=web)["web"]))


def _start_at_login(enable: bool) -> str:
    command = [str(VENV_PYTHON), str(ROOT / "Elaborate" / "start_at_login.py"), "enable" if enable else "disable"]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors="replace")
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip()
                           else "start at sign-in could not be changed")
    return "entry added" if enable else "entry removed"


def area_client(found: dict, plan: Plan) -> None:
    from Special._sync.git_client import LABELS
    screen(6, "Desktop Git app")
    names = {key: LABELS.get(key, key) for key in found["clients"]}
    row("Found", ", ".join(names.values()) or "none (Sourcetree, GitHub Desktop)")
    row("Connected", names.get(found["client"], "none"))
    line("The web view can open any repository in your desktop Git app.", "muted")
    if not names or not plan.enrolled_after:
        if names:
            line("Connecting is saved with a library folder (step 4).", "warning")
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
    screen(7, "Protection")
    anywhere = found["protected"].get("never_publish", [])
    words = found["protected"].get("never_publish_words", [])
    row("Protected values", f"{len(anywhere) + len(words)}" + (f" ({len(words)} whole word only)" if words else ""))
    line("Values that must never be published: your name, email addresses, usernames. A checked "
         "commit or push holds anything that contains one, and scans report them. They stay on "
         "this computer.", "muted")
    if not plan.enrolled_after and not found["protected"]:
        line("Protected values are saved with this machine's settings, which a library folder "
             "creates (step 4).", "warning")
        return
    known = {v.casefold() for v in anywhere + words}
    suggestions = []
    # Not the GitHub login: it is public by design, and protecting it would hold every publish.
    for label, value in (("Your Git name", found["git_name"]), ("Your Git email", found["git_email"]),
                         ("This computer's user name", found["user"])):
        if value and value.casefold() not in known and value not in [v for _l, v in suggestions]:
            suggestions.append((label, value))
    adding = []
    for label, value in suggestions:
        short = len(value) < 6 or " " not in value and "@" not in value
        if yes_no(f"Protect {label.lower()} ({masked(value)})?", "y",
                  "As a whole word only (it also occurs inside other words)" if short else "Anywhere in text."):
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
            whole = ask("Only as a whole word, for a short value that also occurs inside other words? "
                        "[Y/N] [N]:", "n").lower() == "y"
            adding.append((value, whole))
            line("Will be added when you apply.", "success")
    for value, whole in adding:
        plan.add("Protected value", f"Protect {masked(value)} ({'whole word only' if whole else 'anywhere in text'})",
                 lambda value=value, whole=whole: _protect(value, whole))


def _protect(value: str, whole: bool) -> str:
    from Special._security._policy_edit import policy_change
    policy_change(None, {"list": "never_publish_words" if whole else "never_publish", "add": [value]})
    return "added"


def area_scanners(found: dict, plan: Plan) -> None:
    screen(8, "Scanners")
    for name in SCANNERS:
        state = ("installed, used in scans" if found[name] and name in found["engines"] else
                 "installed, not used" if found[name] else "not installed")
        row(name, state, "success" if name in found["engines"] else "text")
    line("gitSpecOps' own checks always run. A scanner adds hundreds of kinds of keys and tokens, "
         "across full history. Only use what is installed: a chosen scanner that is missing makes "
         "every scan incomplete, and an incomplete scan holds a publish.", "muted")
    will_have = {name for name in SCANNERS if found[name]}
    for name, about in SCANNERS.items():
        if found[name]:
            continue
        say()
        line(f"{name}: {about}", "muted")
        if offer_install(plan, name, name, ""):
            will_have.add(name)
    if not will_have:
        return
    if not plan.enrolled_after and not found["protected"]:
        line("Which scanners to use is saved with this machine's settings (step 4).", "warning")
        return
    chosen = []
    for name in SCANNERS:
        if name in will_have and yes_no(f"Use {name} in every scan?", "y" if name in found["engines"] or name == "gitleaks" else "n"):
            chosen.append(name)
    if sorted(chosen) != sorted(found["engines"]):
        plan.add("Scanners used", "Scanners used in scans: " + (", ".join(chosen) or "gitSpecOps' own checks only"),
                 lambda: _select_engines(chosen))


def _select_engines(chosen) -> str:
    from Special._settings.security import load_security_settings, save_security_settings
    missing = [name for name in chosen if not shutil.which(name)]
    if missing:
        raise RuntimeError(f"not installed: {', '.join(missing)} (open a new terminal and run setup again)")
    save_security_settings(load_security_settings(), {"engines": list(chosen)})
    return ", ".join(chosen) or "own checks only"


def area_fleet(found: dict, plan: Plan) -> None:
    from Elaborate._fleet.setup_state import join_fleet, leave_fleet
    screen(9, "Fleet")
    row("Tailscale", "connected" if found["tailnet"] else "installed, not connected" if found["tailscale"]
        else "not installed", "success" if found["tailnet"] else "warning")
    if not found["tailscale"]:
        line(f"Tailscale lets your machines talk directly. Get it at {HOME_PAGES['tailscale']}.", "muted")
    row("Synced folders", ", ".join(found["synced_folders"]) or "none found")
    row("This machine", ("in a fleet: " + ", ".join(found["fleet"])) if found["fleet"] else "on its own")
    line("A fleet is your machines watching each other: every machine's map shows every copy of "
         "every repository. Machines share names, branches and counts only; never file contents or "
         "folder paths. Experimental and untested: a status repository on GitHub (not offered here).",
         "muted")
    if not plan.enrolled_after:
        line("A fleet needs a library folder on this machine (step 4).", "warning")
        return
    say()
    if found["fleet"]:
        option("K", "Keep the fleet as it is")
        option("S", "Show this machine's fleet key", "To add another machine. It appears in this window only.")
        option("L", "Leave the fleet", "This machine keeps its libraries and web view.")
        option("0", "Stop the walkthrough", "Nothing has been changed.")
        answer = choose("ksl0", "k")
        if answer == "0":
            raise Stop
        if answer == "s":
            if ask("Anyone, or any program reading this window, who has the key can join your fleet. "
                   "Type SHOW to print it:") == "SHOW":
                subprocess.call([sys.executable, str(ROOT / "Elaborate" / "setup_fleet.py"), "fleet-key", "--show"],
                                cwd=ROOT)
                ask("Press Enter when you have copied it:")
        elif answer == "l":
            plan.add("Fleet", "Fleet: leave (this machine keeps its libraries)", lambda: (leave_fleet(), "left")[1])
        return
    option("1", "Start a fleet with this machine", "Then add your other machines with this machine's key.")
    option("2", "Join a fleet", "Needs the key shown on a machine already in the fleet.")
    option("N", "Not now")
    option("0", "Stop the walkthrough", "Nothing has been changed.")
    answer = choose("12n0", "n")
    if answer == "0":
        raise Stop
    if answer == "n":
        return
    key = None
    if answer == "2":
        key = ask("Paste the fleet key:")
        if len(key) != 64:
            line("A fleet key is 64 characters; nothing will be joined. Run setup again with the key.", "warning")
            return
    tailnet = bool(found["tailnet"]) and yes_no("Share over Tailscale?", "y", "Recommended: your machines talk directly.")
    folder = ""
    if found["synced_folders"] and yes_no("Also share through a synced folder?", "n",
                                          "One small status file there every 5 minutes; the folder's provider can read it."):
        folder = found["synced_folders"][0]
    if not (tailnet or folder):
        line("A fleet needs a way to share: Tailscale or a synced folder. Nothing will change.", "warning")
        return
    names = yes_no("Share repository names, branches and commit counts with your machines?", "y")
    ways = " and ".join(w for w in ("Tailscale" if tailnet else "", f"a synced folder ({folder})" if folder else "") if w)
    plan.add("Fleet", f"Fleet: {'join' if key else 'start'} a fleet, sharing through {ways}",
             lambda: (join_fleet(key=key, folder=folder or None, tailnet=tailnet, share_names=names), "joined")[1])


# --------------------------------------------------------------------------- review and apply
def review(plan: Plan, enrolled: bool) -> str:
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
    option("B", "Back to the start of the walkthrough")
    option("0", "Cancel", "Nothing has been changed.")
    answer = choose(key + "b0", "0")
    return "apply" if answer == key else answer


def apply(plan: Plan) -> bool:
    banner("Setup  /  Applying", f"folder: {ROOT}")
    say()
    steps = Steps(len(plan.changes))
    for change in plan.changes:
        steps.run(change.title, lambda change=change: ("changed", str(change.apply())))
    failed = [label for label, status, _detail in steps.results if status == "FAILED"]
    section("Summary")
    for label, status, detail in steps.results:
        bullet(f"{label}: {detail}", "error" if status == "FAILED" else "text")
    if failed:
        notice("Setup incomplete", f"{', '.join(failed)} did not finish; the other steps are done. "
               "Run setup again to finish.", "error")
        return False
    notice("Setup complete", "gitSpecOps is set up on this computer.", "success")
    return True


def start_app() -> None:
    pythonw = VENV_PYTHON.with_name("pythonw.exe")
    if not VENV_PYTHON.exists():
        return
    say()
    option("1", "Start gitSpecOps now", "Its tray icon appears; double-click it for your map.")
    option("0", "Close")
    if choose("10", "1") == "1":
        command = [str(pythonw if WINDOWS and pythonw.exists() else VENV_PYTHON), str(ROOT / "App" / "tray.py")]
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if WINDOWS else 0
        subprocess.Popen(command, cwd=ROOT, creationflags=flags, start_new_session=not WINDOWS,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        line("Started.", "success")


def walkthrough(detector=detect) -> int:
    """The whole walkthrough. Returns 0 when it finished or was stopped, 1 when a step failed."""
    while True:
        line("Looking at this computer (nothing changes)...", "detail")
        found = detector()
        plan = Plan()
        try:
            for area in (area_requirements, area_environment, area_gitso, area_machine, area_app,
                         area_client, area_protection, area_scanners, area_fleet):
                area(found, plan)
        except Stop:
            notice("Walkthrough stopped", "Nothing has been changed.", "warning")
            return 0
        answer = review(plan, found["enrolled"])
        if answer == "b":
            continue
        if answer != "apply":
            if plan.changes:
                notice("Cancelled", "Nothing has been changed.", "warning")
            return 0
        ok = apply(plan)
        if ok:
            start_app()
        return 0 if ok else 1
