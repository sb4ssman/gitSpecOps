"""The library inventory against disposable repositories. Offline: remotes are bare folders.

Pins: remotes and identity are recorded and credentials are not; a repository with no remote is
still recorded, with whatever it says about itself; what a clone cannot restore is flagged;
restore re-roots to any destination, never replaces, never escapes, and clones for real.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._inventory import (collect_inventory, plan_restore, sanitize_url,  # noqa: E402
                                validate_inventory)
from Special.inventory_restore import apply  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


def make_repo(path: Path, filename: str = "a.txt") -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    git(path, "config", "user.email", "t@example.test")
    git(path, "config", "user.name", "T")
    (path / filename).write_text("x", encoding="utf-8")
    git(path, "add", filename)
    git(path, "commit", "-q", "-m", "first")


# --- URL hygiene ------------------------------------------------------------------------------
check("https token is stripped", sanitize_url("https://ghp_abc123@example.test/o/r.git")
      == ("https://example.test/o/r.git", True))
check("https user:password is stripped", sanitize_url("https://u:pw@example.test/o/r")
      == ("https://example.test/o/r", True))
check("scp-style git@ is untouched", sanitize_url("git@example.test:o/r.git")
      == ("git@example.test:o/r.git", False))
check("ssh password dropped, user kept", sanitize_url("ssh://git:pw@example.test/o/r")
      == ("ssh://git@example.test/o/r", True))

with tempfile.TemporaryDirectory(prefix="inventory-") as tmp:
    tmp = Path(tmp)
    bare = tmp / "remote" / "example-org" / "tool.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)

    library = tmp / "src" / "Lib"
    # 1. a normal repository with a remote, a sub-folder layout and a folder name with a space
    make_repo(library / "work stuff" / "tool")
    git(library / "work stuff" / "tool", "remote", "add", "origin", bare.as_uri())
    git(library / "work stuff" / "tool", "push", "-q", "origin", "main")
    git(library / "work stuff" / "tool", "branch", "--set-upstream-to=origin/main", "main")
    # 2. unpushed commit + uncommitted work + a stash on top of it
    tool = library / "work stuff" / "tool"
    (tool / "b.txt").write_text("b", encoding="utf-8")
    git(tool, "add", "b.txt")
    git(tool, "commit", "-q", "-m", "local only")
    (tool / "scratch.txt").write_text("untracked", encoding="utf-8")
    # 3. no remote at all, but a README and project metadata that name a likely origin
    orphan = library / "orphan"
    make_repo(orphan)
    (orphan / "README.md").write_text(
        "# Orphan Tool\n\nDoes a thing. Source: https://github.com/example-org/orphan-tool\n", encoding="utf-8")
    (orphan / "pyproject.toml").write_text(
        '[project]\nname = "orphan-tool"\nversion = "1.2"\n'
        '[project.urls]\nSource = "https://github.com/example-org/orphan.git"\n', encoding="utf-8")
    # 4. a remote carrying a credential
    leaky = library / "leaky"
    make_repo(leaky)
    git(leaky, "remote", "add", "origin", "https://ghp_secret@example.test/example-org/leaky.git")
    # 5. a repository nested inside another
    make_repo(library / "orphan" / "vendor" / "inner")

    inventory = collect_inventory([("lib", library)])
    repos = {r["path"]: r for r in inventory["repositories"]}
    check("every repository found, including nested", sorted(repos) == [
        "leaky", "orphan", "orphan/vendor/inner", "work stuff/tool"])
    check("schema validates", len(validate_inventory(inventory)) == 4)

    t = repos["work stuff/tool"]
    check("origin url recorded", t["origin_url"] == bare.as_uri())
    check("branch and upstream recorded", t["branch"] == "main" and t["upstream"] == "origin/main")
    check("unpushed commit flagged", "unpushed-commits" in t["flags"] and t["ahead"] == 1)
    check("uncommitted work flagged", "uncommitted-work" in t["flags"] and t["status"]["untracked"] == 1)
    check("head and root commit recorded", len(t["head"]) == 40 and len(t["root_commits"]) == 1)
    check("space in folder name kept in the relative path", t["path"].startswith("work stuff/"))
    check("no drive letter or absolute path in a repository entry", ":" not in t["path"] and not t["path"].startswith("/"))

    o = repos["orphan"]
    check("no-remote repository is recorded and flagged", o["remotes"] == [] and "no-remote" in o["flags"])
    check("readme gathered", o["metadata"]["readme"]["title"] == "Orphan Tool")
    check("project metadata gathered", o["metadata"]["python"]["name"] == "orphan-tool")
    cands = o["metadata"]["candidate_urls"]
    check("origin candidates found, one per distinct repo", len(cands) == 2 and "has-origin-candidates" in o["flags"])
    check("candidate from project file carries identity", cands[0]["identity"]["owner"] == "example-org")

    check("credential is not in the inventory at all", "ghp_secret" not in json.dumps(inventory))
    check("credential removal is flagged", "credentials-removed" in repos["leaky"]["flags"])
    check("nesting recorded", repos["orphan/vendor/inner"]["nested_in"] == "orphan")

    # --- restore: a different 'drive', different folder name ---------------------------------
    new_lib = tmp / "other-drive" / "Repos"
    rows = plan_restore(inventory["repositories"], {"lib": new_lib})
    by_path = {r["path"]: r for r in rows}
    check("restore re-roots under the mapped destination",
          by_path["work stuff/tool"]["target"] == new_lib / "work stuff" / "tool")
    check("clone row names what a clone cannot bring back",
          "unpushed" in by_path["work stuff/tool"]["detail"] and "uncommitted" in by_path["work stuff/tool"]["detail"])
    check("no-remote repo needs review and points at candidates",
          by_path["orphan"]["action"] == "needs_review" and "--use-candidates" in by_path["orphan"]["detail"])
    check("unmapped root needs review", plan_restore(inventory["repositories"], {})[0]["action"] == "needs_review")

    canon = plan_restore(inventory["repositories"], {"lib": new_lib}, layout="canonical")
    check("canonical layout uses host/owner/name where known",
          any(str(r.get("target", "")).endswith("example.test\\example-org\\leaky") or
              str(r.get("target", "")).endswith("example.test/example-org/leaky") for r in canon))

    with_leads = plan_restore(inventory["repositories"], {"lib": new_lib}, use_candidates=True)
    check("--use-candidates makes a lead cloneable",
          {r["path"]: r for r in with_leads}["orphan"]["url_source"].startswith("candidate:"))

    # actually clone one for real (the offline bare remote), from a hand-picked plan
    sample = [r for r in inventory["repositories"] if r["path"] == "work stuff/tool"]
    real = plan_restore(sample, {"lib": new_lib})
    done = apply(real)
    check("clone really happened", done[0]["action"] == "cloned" and (new_lib / "work stuff" / "tool" / "a.txt").exists())
    check("what was unpushed is genuinely absent from the clone",
          not (new_lib / "work stuff" / "tool" / "b.txt").exists())
    again = plan_restore(sample, {"lib": new_lib})
    check("re-running leaves an existing destination alone", again[0]["action"] == "exists")

    # --- safety --------------------------------------------------------------------------------
    hostile = [{"root": "lib", "path": "../escape", "name": "x", "origin_url": "https://example.test/o/x",
                "flags": []},
               {"root": "lib", "path": "ok/CON", "name": "y", "origin_url": "https://example.test/o/y", "flags": []},
               {"root": "lib", "path": "Same", "name": "a", "origin_url": "https://example.test/o/a", "flags": []},
               {"root": "lib", "path": "same", "name": "b", "origin_url": "https://example.test/o/b", "flags": []}]
    hrows = plan_restore(hostile, {"lib": tmp / "safe"})
    actions = {r["path"]: r["action"] for r in hrows}
    check("parent traversal refused", actions["../escape"] == "needs_review")
    check("windows device name refused", actions["ok/CON"] == "needs_review")
    check("case-insensitive collision refused", sorted([actions["Same"], actions["same"]]) == ["clone", "needs_review"])

    # --- a haphazard library: repos in unrelated places ----------------------------------------
    from Special._inventory import LOOSE, build_roots  # noqa: E402

    drive_a, drive_b = tmp / "driveA" / "projects", tmp / "driveB" / "projects"
    make_repo(drive_a / "alpha")
    make_repo(drive_b / "alpha")           # same folder name, different "drive"
    make_repo(tmp / "desktop" / "one-off")  # a repo on its own
    make_repo(tmp / "desktop" / "one-off" / "sub" / "deep")  # nested inside the loose one
    for where, url in ((drive_a / "alpha", "https://example.test/owner-a/alpha"),
                       (drive_b / "alpha", "https://example.test/owner-b/alpha"),
                       (tmp / "desktop" / "one-off", "https://example.test/owner-a/one-off"),
                       (tmp / "desktop" / "one-off" / "sub" / "deep", "https://example.test/owner-a/deep")):
        git(where, "remote", "add", "origin", url)
    labelled = build_roots([str(drive_a), str(drive_b), f"mine={tmp / 'desktop'}"])
    check("bare roots get unique labels, explicit ones are kept",
          [label for label, _ in labelled] == ["projects", "projects-2", "mine"])
    check("the same folder given twice counts once", len(build_roots([str(drive_a), str(drive_a)])) == 1)
    for bad_spec in ([f"{LOOSE}={drive_a}"], [f"Bad Label={drive_a}"], [f"x={drive_a}", f"x={drive_b}"]):
        try:
            build_roots(bad_spec)
            check(f"bad label rejected: {bad_spec[0][:12]}", False)
        except ValueError:
            check(f"bad label rejected: {bad_spec[0][:12]}", True)

    scattered = collect_inventory(build_roots([str(drive_a), str(drive_b)]),
                                  loose=[tmp / "desktop" / "one-off", drive_a / "alpha"])
    pairs = sorted((r["root"], r["path"]) for r in scattered["repositories"])
    check("two same-named repos on different drives both recorded under their own labels",
          ("projects", "alpha") in pairs and ("projects-2", "alpha") in pairs)
    check("a loose repo is recorded once, and remembers where it was",
          [r for r in scattered["repositories"] if r["root"] == LOOSE][0]["source_path"].endswith("one-off"))
    check("a loose path already inside a root is not recorded twice",
          sum(1 for r in scattered["repositories"] if r["name"] == "alpha") == 2)
    check("loose label is listed among the roots", {"label": LOOSE, "source_path": None} in scattered["roots"])
    try:
        collect_inventory([], loose=[tmp / "desktop"])
        check("a non-repository --repo is refused", False)
    except ValueError:
        check("a non-repository --repo is refused", True)
    itself = collect_inventory([("self", tmp / "desktop" / "one-off")])
    check("a root that is itself a repository is not lost",
          any(r["root"] == LOOSE and r["name"] == "one-off" for r in itself["repositories"]))

    one_dest = plan_restore(scattered["repositories"],
                            {"projects": tmp / "new", "projects-2": tmp / "new", LOOSE: tmp / "new"},
                            layout="canonical")
    check("canonical files a scattered library into one tree without collisions",
          not any(r["action"] == "needs_review" and "same destination" in r["detail"] for r in one_dest))
    preserved = plan_restore(scattered["repositories"], {"projects": tmp / "new", "projects-2": tmp / "new"})
    check("preserve into one destination reports the collision instead of clobbering",
          any("same destination" in r["detail"] for r in preserved if r["action"] == "needs_review"))

    # --- the commands themselves: no dialog without a person -----------------------------------
    import os as _os

    env = {**_os.environ, "GITSPECOPS_NO_GUI": "1"}
    script = Path(__file__).resolve().parents[2] / "Special"

    def run_cmd(name: str, *cli: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(script / name), *cli], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, env=env, timeout=120)

    nope = run_cmd("inventory_export.py")
    check("export with nothing to record and no terminal fails instead of opening a dialog",
          nope.returncode == 2 and "no terminal" in nope.stderr)
    nope = run_cmd("inventory_restore.py")
    check("restore with no file and no terminal fails instead of opening a dialog",
          nope.returncode == 2 and "no terminal" in nope.stderr)

    out_file = tmp / "asked" / "inv.json"
    answers = tmp / "export-answers.txt"
    answers.write_text(f"{drive_a}\ny\n{drive_b}\nn\n{out_file}\n", encoding="utf-8")
    asked = run_cmd("inventory_export.py", "--answers", str(answers))
    check("export asks for folders (twice) and a save location, from scripted answers",
          asked.returncode == 0 and out_file.is_file() and "2 label(s)" in asked.stdout)

    dest_a, dest_b = tmp / "restored" / "a", tmp / "restored" / "b"
    answers.write_text(f"{out_file}\n{dest_a}\n{dest_b}\n", encoding="utf-8")
    planned = run_cmd("inventory_restore.py", "--answers", str(answers))
    check("restore asks for the file and a destination per label",
          planned.returncode == 0 and str(dest_a) in planned.stdout and str(dest_b) in planned.stdout
          and not dest_a.exists())
    flagged = run_cmd("inventory_restore.py", str(out_file), "--dest", str(tmp / "one"), "--layout", "canonical",
                      "--no-prompt")
    check("one --dest with canonical layout plans a single tree", flagged.returncode == 0
          and "needs_review" not in flagged.stdout)

    for bad in ({}, {"schema": "gitspecops.inventory", "schema_version": 99, "repositories": []}):
        try:
            validate_inventory(bad)
            check("bad inventory rejected", False)
        except ValueError:
            check("bad inventory rejected", True)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nall passed")
