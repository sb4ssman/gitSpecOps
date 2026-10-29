"""Local archive management and scheduling against disposable archives and temporary state.

Pins what makes a scheduled refresh safe to leave running: the registry and the refresh-all
launcher live in the per-user state folder (never the checkout); every launcher it writes runs
only the Special manager refresh action; a refresh fast-forwards through the shared runner.
Offline: the "remote" is a bare repository in the same temporary folder.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

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

    from Special import archive_manager as manage  # noqa: E402  (after GITSPECOPS_HOME is set)
    from Special._archive import manager as engine  # noqa: E402
    from Elaborate import archive_manage as scheduled  # noqa: E402
    from Special._archive.registry import load_registry, registered_roots, registry_path  # noqa: E402

    check("scheduling exposes no duplicate local-management API",
          not hasattr(scheduled, "refresh_all") and not hasattr(scheduled, "install_launchers"))
    check("importing management commands creates no user state", not (tmp / "home").exists())
    with redirect_stderr(io.StringIO()):
        try:
            manage.parse_args(["--install-monthly-task"])
        except SystemExit as exc:
            check("Special manager refuses scheduling flags", exc.code == 2)
        else:
            check("Special manager refuses scheduling flags", False)

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
    check("launcher resolves saved choices through the manager at its selected profile",
          "Special/archive_manager.py" in text and "--refresh" in text and "--settings-home" in text
          and str(tmp / "home") in text and "--update" not in text and "--yes" not in text)
    check("launcher never carries a publish/reconcile/rename verb",
          not any(flag in text for flag in FORBIDDEN))
    check("registry records the archive", registered_roots() == [str(archive.resolve())])
    with redirect_stdout(io.StringIO()):
        check("Special lists the registered archive", manage.main(["--list"]) == 0)

    refresh = scheduled.write_refresh_all_script()
    check("refresh-all launcher lives in the per-user state folder", refresh.parent == tmp / "home")
    refresh_text = "\n".join(p.read_text(encoding="utf-8")
                             for p in (tmp / "home").glob(f"{scheduled.REFRESH_ALL_LAUNCHER}.*"))
    check("refresh-all launcher runs Special/archive_manager.py --refresh-all",
          "Special/archive_manager.py" in refresh_text and "--refresh-all" in refresh_text)
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

    # A common profile becomes authoritative; old receipt copies remain historical data.
    receipts = json.loads(registry_path().read_text(encoding="utf-8"))
    receipts["installations"][0]["mode"] = "sync"
    receipts["installations"][0]["approved_remote_prefixes"] = ["https://old.example.test/"]
    registry_path().write_text(json.dumps(receipts), encoding="utf-8")
    (tmp / "home" / "settings.json").write_text(json.dumps({"schema_version": 2, "components": {
        "archive_manage": {"options": {"archives": [{"root": str(archive.resolve()), "mode": "update",
                                                     "approved_remote_prefixes": prefixes}]}}}}), encoding="utf-8")
    (seed / "c.txt").write_text("c", encoding="utf-8")
    git(seed, "add", "c.txt")
    git(seed, "commit", "-q", "-m", "c")
    git(seed, "push", "-q", "origin", "main")
    common_path = tmp / "home" / "settings.json"
    common_before = common_path.read_bytes()
    denied = json.loads(common_before)
    denied["components"]["archive_manage"]["options"]["archives"][0]["approved_remote_prefixes"] = ["https://denied.example.test/"]
    common_path.write_text(json.dumps(denied), encoding="utf-8")
    check("common-profile remote allowance prevents an out-of-scope real pull",
          manage.refresh_archive(archive) == 1 and not (archive / "work" / "c.txt").exists())
    common_path.write_bytes(common_before)
    scratch = archive / "work" / "a.txt"
    original_a = scratch.read_bytes()
    scratch.write_text("keep local work", encoding="utf-8")
    check("common-profile refresh preserves dirty work",
          manage.refresh_archive(archive) == 0 and not (archive / "work" / "c.txt").exists()
          and scratch.read_text(encoding="utf-8") == "keep local work")
    scratch.write_bytes(original_a)  # Restore only this test's known temporary file contents.
    check("common-profile single refresh fast-forwards using current allowances",
          manage.refresh_archive(archive) == 0 and (archive / "work" / "c.txt").exists())
    retained = json.loads(registry_path().read_text(encoding="utf-8"))["installations"][0]
    check("receipt-only refresh retains historical mode and remote copies",
          retained["mode"] == "sync" and retained["approved_remote_prefixes"] == ["https://old.example.test/"]
          and retained["last_run_result"] == "ok")

    check("forget removes the entry", manage.forget_installation(archive)
          and registered_roots() == [])

    # Both saved modes reach the shared headless operation, without network discovery.
    update_root, sync_root = tmp / "update-archive", tmp / "sync-archive"
    update_root.mkdir()
    sync_root.mkdir()
    fixture = {"version": 1, "installations": [
        {"root": str(update_root), "mode": "update"},
        {"root": str(sync_root), "mode": "sync"},
    ]}
    from Special._archive import operation
    with patch.object(operation, "execute_archive", return_value={"exit_code": 0, "effects_possible": False, "result": {}}) as run, \
         patch.object(operation, "load_registry") as loader, patch.object(operation, "save_registry"), \
         redirect_stdout(io.StringIO()):
        from unittest.mock import MagicMock
        data = MagicMock()
        data.__getitem__.side_effect = fixture.__getitem__
        data.home, data.preferences = tmp / "mode-profile", None
        loader.return_value = data
        code = manage.refresh_all(scan_only=False)
    verbs = [call.args[0] for call in run.call_args_list]
    check("manager preserves saved update and sync pathways",
          code == 0 and len(verbs) == 2 and verbs[0]["mode"] == "update" and verbs[1]["mode"] == "sync")

    # Scheduling stays above Special; no real OS task is created by this check.
    with patch.object(scheduled, "write_refresh_all_script", return_value=tmp / "refresh"), \
         patch.object(scheduled.schedule, "install_monthly", return_value=0) as install, \
         patch.object(scheduled, "log_event"):
        check("Elaborate retains monthly task installation",
              scheduled.install_monthly_task("fixture-task", 1, "09:00") == 0)
        check("monthly task uses the retained refresh launcher",
              install.call_args.args == ("fixture-task", tmp / "refresh", 1, "09:00"))

code_only = (ROOT / "Elaborate" / "archive_manage.py").read_text(encoding="utf-8").split('"""', 2)[2]
check("archive_manage code never names --publish", "--publish" not in code_only)
local_code = (ROOT / "Special" / "_archive" / "manager.py").read_text(encoding="utf-8")
check("local manager imports neither Elaborate nor the scheduler",
      "from Elaborate" not in local_code and "import schedule" not in local_code
      and "launcher, schedule" not in local_code)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-ARCHIVE-MANAGE-TESTS-PASS")
