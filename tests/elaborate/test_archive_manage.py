"""archive_manage against a disposable archive, with all state in a temporary GITSPECOPS_HOME.

Pins what makes a scheduled refresh safe to leave running: the registry and the refresh-all
launcher live in the per-user state folder (never the checkout); every launcher it writes runs
only `--update` or `--sync`; and a refresh fast-forwards through archive_sync in-process.
Offline: the "remote" is a bare repository in the same temporary folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

FAILS: list[str] = []
FORBIDDEN = ("--publish", "--reconcile", "--rename-folders")


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


with tempfile.TemporaryDirectory(prefix="archive-manage-") as tmp:
    tmp = Path(tmp)
    os.environ["GITSPECOPS_HOME"] = str(tmp / "home")

    from Elaborate import archive_manage as manage  # noqa: E402  (after GITSPECOPS_HOME is set)
    from Elaborate._archive_registry import load_registry, registered_roots, registry_path  # noqa: E402

    check("registry lives in the per-user state folder",
          registry_path() == tmp / "home" / "gitspecops_managed_archives.json")
    check("registry is never inside the checkout", ROOT not in registry_path().parents)

    bare = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    for repo in (seed,):
        git(repo, "config", "user.email", "t@example.test")
        git(repo, "config", "user.name", "T")
    (seed / "a.txt").write_text("a", encoding="utf-8")
    git(seed, "add", "a.txt")
    git(seed, "commit", "-q", "-m", "a")
    git(seed, "push", "-q", "origin", "main")

    archive = tmp / "archive"
    archive.mkdir()
    subprocess.run(["git", "clone", "-q", str(bare), str(archive / "work")], check=True,
                   capture_output=True)
    prefixes = [str(tmp)]  # the "approved remote" is anything under this temporary folder

    record = manage.install_launchers(archive, prefixes, mode=manage.MODE_UPDATE)
    written = [p for p in archive.iterdir() if p.name.startswith(manage.ARCHIVE_LAUNCHER)]
    check("per-archive launcher written", bool(written) and Path(record.launcher).is_file())
    text = "\n".join(p.read_text(encoding="utf-8") for p in written)
    check("launcher runs Special/archive_sync.py --update --yes",
          "Special/archive_sync.py" in text and "--update" in text and "--yes" in text)
    check("launcher never carries a publish/reconcile/rename verb",
          not any(flag in text for flag in FORBIDDEN))
    check("registry records the archive", registered_roots() == [str(archive.resolve())])

    sync_args = manage.automated_sync_args(archive, prefixes, manage.MODE_SYNC)
    check("sync mode adds only --sync", "--sync" in sync_args
          and not any(flag in sync_args for flag in FORBIDDEN))
    item = load_registry()["installations"][0]
    for scan_only in (True, False):
        for force in (True, False):
            argv = manage.refresh_argv(item, scan_only, force)
            check(f"refresh argv (scan_only={scan_only}, force_sync={force}) is safe",
                  not any(flag in argv for flag in FORBIDDEN))

    refresh = manage.write_refresh_all_script()
    check("refresh-all launcher lives in the per-user state folder", refresh.parent == tmp / "home")
    refresh_text = "\n".join(p.read_text(encoding="utf-8")
                             for p in (tmp / "home").glob(f"{manage.REFRESH_ALL_LAUNCHER}.*"))
    check("refresh-all launcher runs Elaborate/archive_manage.py --refresh-all",
          "Elaborate/archive_manage.py" in refresh_text and "--refresh-all" in refresh_text)
    check("refresh-all launcher knows where the checkout is", str(ROOT) in refresh_text)

    # New upstream work, then an in-process refresh must fast-forward the archive's clone.
    (seed / "b.txt").write_text("b", encoding="utf-8")
    git(seed, "add", "b.txt")
    git(seed, "commit", "-q", "-m", "b")
    git(seed, "push", "-q", "origin", "main")
    code = manage.refresh_all(scan_only=False)
    check("refresh-all succeeds", code == 0)
    check("refresh-all fast-forwarded the clone", (archive / "work" / "b.txt").exists())
    after = json.loads(registry_path().read_text(encoding="utf-8"))["installations"][0]
    check("refresh-all recorded the run", after.get("last_run_result") == "ok")
    check("the manager's log is in the state folder", manage.log_path().parent == tmp / "home")

    check("forget removes the entry", manage.forget_installation(archive)
          and registered_roots() == [])

code_only = (ROOT / "Elaborate" / "archive_manage.py").read_text(encoding="utf-8").split('"""', 2)[2]
check("archive_manage code never names --publish", "--publish" not in code_only)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-ARCHIVE-MANAGE-TESTS-PASS")
