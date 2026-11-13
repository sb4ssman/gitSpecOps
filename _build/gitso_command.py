"""Put `gitso` on the command path, or in your shells as an alias; find it; remove it.

Why:          `gitso` should be a command in any terminal, on Windows, macOS and Linux alike,
              without packaging, a compiled launcher, or anything a person cannot read.
Reads:        the launcher folder, the user PATH (Windows) and shell startup files.
May change:   only when setup's review is accepted:
              - launchers: plain-text files in ~/.gitspecops/bin (`gitso.cmd` and `gitso` on
                Windows, `gitso` elsewhere), and that folder on the user's PATH (Windows: the
                user Path setting; macOS/Linux: a marked block in the shell startup files);
              - aliases: a marked block defining `gitso` in each shell's profile (PowerShell,
                bash, zsh, fish), for the shells present.
              Removing deletes exactly those files and blocks.
Results:      `status()`: what is in place and whether it points at this folder.
Layer:        setup (_build).
Status:       working

The folder follows the convention of rustup (~/.cargo/bin), deno and bun: a tool's own folder in
the home folder, the same on every system. Each launcher runs this folder's .venv Python if it
exists, otherwise the Python that ran setup, on this folder's gitso.py. Nothing else is written.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITSO = ROOT / "gitso.py"
MARK = "gitSpecOps"


def system() -> str:
    return "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"


def bin_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".gitspecops" / "bin"


def fallback_python() -> str:
    """The Python that ran setup, used when this folder has no .venv. When setup itself ran from
    that .venv, the Python the .venv was made from: the fallback must outlive the .venv."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    return str(Path(base).resolve())


# --------------------------------------------------------------------------- launcher text
def _sh(text) -> str:
    """Safe inside sh double quotes."""
    return "".join("\\" + c if c in '\\"$`' else c for c in str(text))


def _cmd(text) -> str:
    """Safe inside a cmd.exe quoted path."""
    return str(text).replace("%", "%%")


def _ps(text) -> str:
    """Safe inside a PowerShell single-quoted string."""
    return str(text).replace("'", "''")


def launchers(osname: str, home: Path | None = None) -> dict[Path, str]:
    """Each launcher file and its full text."""
    folder, root, fallback = bin_dir(home), ROOT, fallback_python()
    note = f"gitSpecOps setup made this; remove it there. Runs {root / 'gitso.py'}."
    venv_posix = (root / ".venv" / ("Scripts/python.exe" if osname == "windows" else "bin/python")).as_posix()
    shell = "\n".join([
        "#!/bin/sh",
        f"# {note}",
        f'if [ -x "{_sh(venv_posix)}" ]; then exec "{_sh(venv_posix)}" "{_sh(GITSO.as_posix())}" "$@"; fi',
        f'exec "{_sh(Path(fallback).as_posix())}" "{_sh(GITSO.as_posix())}" "$@"', ""])
    if osname != "windows":
        return {folder / "gitso": shell}
    venv = root / ".venv" / "Scripts" / "python.exe"
    # Labels, not a parenthesised block: a path with ")" (Program Files (x86)) would end it early.
    cmd = "\r\n".join([
        "@echo off",
        f"rem {note}",
        f'if not exist "{_cmd(venv)}" goto fallback',
        f'"{_cmd(venv)}" "{_cmd(GITSO)}" %*',
        "exit /b %errorlevel%",
        ":fallback",
        f'"{_cmd(fallback)}" "{_cmd(GITSO)}" %*',
        "exit /b %errorlevel%", ""])
    # gitso.cmd for cmd and PowerShell; gitso (a shell script) for Git Bash.
    return {folder / "gitso.cmd": cmd, folder / "gitso": shell}


def alias_line(shell: str) -> str:
    venv = ROOT / ".venv" / ("Scripts/python.exe" if system() == "windows" else "bin/python")
    if shell == "powershell":
        return (f"function gitso {{ if (Test-Path '{_ps(venv)}') {{ & '{_ps(venv)}' '{_ps(GITSO)}' @args }} "
                f"else {{ & '{_ps(fallback_python())}' '{_ps(GITSO)}' @args }} }}")
    # A function, like the launchers: it picks this folder's .venv each time it runs.
    v, g, f = _sh(venv.as_posix()), _sh(GITSO.as_posix()), _sh(Path(fallback_python()).as_posix())
    if shell == "fish":
        return (f'function gitso; if test -x "{v}"; "{v}" "{g}" $argv; '
                f'else; "{f}" "{g}" $argv; end; end')
    return f'gitso() {{ if [ -x "{v}" ]; then "{v}" "{g}" "$@"; else "{f}" "{g}" "$@"; fi; }}'


def path_line(shell: str, home: Path | None = None) -> str:
    folder = "$HOME/.gitspecops/bin"
    if shell == "fish":
        return f"contains {folder} $PATH; or set -gx PATH {folder} $PATH"
    return f'case ":$PATH:" in *":{folder}:"*) ;; *) export PATH="{folder}:$PATH" ;; esac'


# --------------------------------------------------------------------------- marked blocks
def _markers(kind: str, comment: str = "#") -> tuple[str, str]:
    return (f"{comment} >>> {MARK} {kind} (added by gitSpecOps setup; remove it there) >>>",
            f"{comment} <<< {MARK} {kind} <<<")


def has_block(path: Path, kind: str) -> bool:
    try:
        return _markers(kind)[0] in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _without_block(text: str, kind: str) -> str:
    start, end = _markers(kind)
    out, inside = [], False
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n") == start:
            inside = True
            continue
        if inside:
            if line.rstrip("\r\n") == end:
                inside = False
            continue
        out.append(line)
    return "".join(out).rstrip("\n") + ("\n" if "".join(out).strip() else "")


def write_block(path: Path, kind: str, body: str) -> None:
    start, end = _markers(kind)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _without_block(text, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text + "\n" if text.strip() else "") + f"{start}\n{body}\n{end}\n", encoding="utf-8")


def remove_block(path: Path, kind: str) -> bool:
    if not has_block(path, kind):
        return False
    text = _without_block(path.read_text(encoding="utf-8"), kind)
    if text.strip():
        path.write_text(text, encoding="utf-8")
    else:
        path.unlink()  # setup made it, and nothing else is in it
    return True


# --------------------------------------------------------------------------- shells
def posix_path_files(home: Path | None = None, which=shutil.which) -> dict[Path, str]:
    """Where a POSIX system's shells read PATH at start, and the shell of each file. ~/.profile
    is read by login shells; ~/.bash_profile, when it exists, replaces it for bash; ~/.bashrc
    serves terminals that open non-login shells (most Linux desktops); ~/.zshenv is read by
    every zsh (macOS's default shell); fish reads conf.d."""
    home = home or Path.home()
    files = {home / ".profile": "sh"}
    for name in (".bash_profile", ".bashrc"):
        if (home / name).exists():
            files[home / name] = "sh"
    if which("zsh") or sys.platform == "darwin":
        files[home / ".zshenv"] = "sh"
    if which("fish"):
        files[home / ".config" / "fish" / "conf.d" / "gitspecops-path.fish"] = "fish"
    return files


def powershell_profiles(which=shutil.which) -> dict[Path, str]:
    """Each installed PowerShell's profile for all its hosts (the console, VS Code, ...)."""
    found = {}
    for exe in ("pwsh", "powershell"):
        if not which(exe):
            continue
        try:
            out = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command",
                                  "$PROFILE.CurrentUserAllHosts"], capture_output=True, text=True,
                                 timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out:
            found[Path(out)] = "powershell"
    return found


def alias_files(home: Path | None = None, which=shutil.which, osname: str | None = None) -> dict[Path, str]:
    """Each present shell's interactive profile, and the shell it belongs to."""
    home, osname = home or Path.home(), osname or system()
    files = {}
    if which("bash") and osname != "windows":
        files[home / ".bashrc"] = "sh"
    if which("zsh") or osname == "macos":
        files[home / ".zshrc"] = "sh"
    if which("fish"):
        files[home / ".config" / "fish" / "conf.d" / "gitspecops-alias.fish"] = "fish"
    files.update(powershell_profiles(which))
    return files


def powershell_runs_profiles(which=shutil.which) -> bool | None:
    """Windows PowerShell's default policy on a desktop (Restricted) never runs a profile."""
    exe = "pwsh" if which("pwsh") else "powershell" if which("powershell") else None
    if not exe:
        return None
    try:
        policy = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", "Get-ExecutionPolicy"],
                                capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return policy not in ("Restricted", "AllSigned")


# --------------------------------------------------------------------------- Windows user PATH
def _same(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.expandvars(a).rstrip("\\/")) == os.path.normcase(str(b).rstrip("\\/"))


def windows_path_has(folder: Path) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return False
    return any(_same(part, folder) for part in value.split(";") if part)


def windows_path_set(folder: Path, present: bool) -> bool:
    """Add or remove `folder` in the user Path; True when it changed. New terminals see it."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        parts = [part for part in value.split(";") if part]
        kept = [part for part in parts if not _same(part, folder)]
        wanted = kept + [str(folder)] if present else kept
        if wanted == parts:
            return False
        winreg.SetValueEx(key, "Path", 0, kind, ";".join(wanted))
    _announce_environment()
    return True


def _announce_environment() -> None:
    """Tell Explorer the environment changed, so terminals opened from now on see it."""
    try:
        import ctypes
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000,
                                                 ctypes.byref(result))
    except (OSError, AttributeError):
        pass


# --------------------------------------------------------------------------- status, apply
def status(home: Path | None = None, osname: str | None = None, which=shutil.which) -> dict:
    """What is in place now. Reads only."""
    osname = osname or system()
    files = launchers(osname, home)
    present = [path for path in files if path.exists()]
    ours = bool(present) and all(str(GITSO.as_posix()) in path.read_text(encoding="utf-8").replace("\\", "/")
                                 for path in present)
    if osname == "windows":
        on_path = windows_path_has(bin_dir(home))
    else:
        on_path = any(has_block(path, "path") for path in posix_path_files(home, which))
    aliases = [str(path) for path in alias_files(home, which, osname) if has_block(path, "alias")]
    return {"launcher": "here" if ours and len(present) == len(files) else "elsewhere" if present else "none",
            "on_path": on_path, "folder": str(bin_dir(home)), "aliases": aliases,
            "in_this_terminal": bool(shutil.which("gitso"))}


def install_launchers(home: Path | None = None, osname: str | None = None, which=shutil.which) -> str:
    osname = osname or system()
    for path, text in launchers(osname, home).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        if osname != "windows" or path.suffix == "":
            path.chmod(0o755)
    if osname == "windows":
        windows_path_set(bin_dir(home), True)
        return f"{bin_dir(home)} is on your Path; open a new terminal"
    changed = []
    for path, shell in posix_path_files(home, which).items():
        write_block(path, "path", path_line(shell, home))
        changed.append(path.name)
    return f"{bin_dir(home)} added to PATH in {', '.join(changed)}; open a new terminal"


def remove_launchers(home: Path | None = None, osname: str | None = None, which=shutil.which) -> str:
    osname = osname or system()
    for path in launchers(osname, home):
        if path.exists():
            path.unlink()
    folder = bin_dir(home)
    for directory in (folder, folder.parent):
        try:
            directory.rmdir()  # only when empty
        except OSError:
            break
    if osname == "windows":
        windows_path_set(folder, False)
    else:
        for path in posix_path_files(home, which):
            remove_block(path, "path")
    return "removed"


def install_aliases(home: Path | None = None, osname: str | None = None, which=shutil.which) -> str:
    done = []
    for path, shell in alias_files(home, which, osname).items():
        write_block(path, "alias", alias_line(shell))
        done.append(str(path))
    if not done:
        raise RuntimeError("no shell profile found to add an alias to")
    return f"alias in {len(done)} profile(s); open a new terminal"


def remove_aliases(home: Path | None = None, osname: str | None = None, which=shutil.which) -> str:
    removed = [path for path in alias_files(home, which, osname) if remove_block(path, "alias")]
    return f"removed from {len(removed)} profile(s)"
