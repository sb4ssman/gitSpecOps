"""The Security tools on a disposable repository holding invented personal data.

Pins: history is read whole (file content, file names, commit messages, author/committer
identities); identity values come from seeds, never from the code; the rewrite plan holds the
real values only outside the repository, never rewrites the repository's owner, and never
touches the checkout; verification refuses an unrewritten mirror.

Every value here is invented. Seeds are passed in, so the runner's real identity is never used.
The rewrite itself (`apply`, which runs `git filter-repo`) is exercised only when
GITSPECOPS_RUN_REWRITE_TEST=1 is set -- run it once by hand; it touches only a temporary folder.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

from Security import rewrite_history  # noqa: E402
from Security._history import scan_history  # noqa: E402
from Security._patterns import find, identity_patterns, mask  # noqa: E402
from Security._repo import patterns_for  # noqa: E402
from Security.scan_history import render  # noqa: E402

FAILS: list[str] = []
SEEDS = {
    "your gh login": ["example-owner"],
    "a tailnet machine name": ["invented-host", "other-invented-box"],
    "a tailnet address": ["100.64.9.9"],
    "your git email": ["someone.real@example-mail.invalid"],
}
TARGET = ("Example Owner", "12345+example-owner@users.noreply.github.com")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(f"{label}: {detail}")


def git(repo: Path, *args: str, name="Example Owner", email="someone.real@example-mail.invalid"):
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout


def commit(repo: Path, message: str, **who) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, **who)


# --- patterns: identity values are seeds, whole-value only, owner excused only where public ---
patterns = identity_patterns(SEEDS, public_repositories=("proj",))
check("a seeded machine name is found",
      [f.value for f in find("ran on invented-host today", patterns)] == ["invented-host"])
check("a longer word containing it is not",
      not find("invented-hostname-x", {"m": patterns["a tailnet machine name"]}))
check("punctuation does not shield a value (runs/__name.txt, x-name)",
      len(find("runs/__invented-host.txt and x-invented-host", patterns)) == 2)
check("the owner of a public repository is excused there",
      not find("https://example.test/example-owner/proj.git", patterns))
check("the owner beside any other repository is not",
      bool(find("example-owner/private-state", patterns)))
check("masking keeps a value recognizable but unreadable",
      mask("someone.real@example-mail.invalid") == "s***@e***.invalid"
      and "invented" not in mask("other-invented-box"))

with tempfile.TemporaryDirectory(prefix="security-") as temp:
    tmp = Path(temp)
    repo = tmp / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://example.test/example-owner/proj.git")
    (repo / "README.md").write_text("# proj\nclone https://example.test/example-owner/proj\n")
    commit(repo, "start")
    notes = repo / "notes.md"
    notes.write_text("peer invented-host at 100.64.9.9; also 100.64.9.90 is not it\n")
    (repo / "invented-host.log").write_text("x\n")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "tool.cpython-314.pyc").write_bytes(
        b"\x00\x0d\r\nC:\\Users\\inventedperson\\proj\\tool.py\x00")
    commit(repo, "notes from other-invented-box", name="HOSTBOX\\example-owner")
    (repo / "contrib.md").write_text("thanks\n")
    commit(repo, "a collaborator's commit", name="Collaborator",
           email="collab@example-mail.invalid")
    notes.write_text("peer machine-a at <tailnet-ip>\n")
    (repo / "invented-host.log").unlink()
    commit(repo, "sanitize", email=TARGET[1], name=TARGET[0])
    before_head = git(repo, "rev-parse", "HEAD")
    before_status = git(repo, "status", "--porcelain")

    report = scan_history(repo, ["--all"], patterns_for(repo, SEEDS))
    found = {(e.kind, e.value): e for e in report.exposures.values()}
    check("history finds a value no current file holds",
          ("a tailnet address", "100.64.9.9") in found
          and not found[("a tailnet address", "100.64.9.9")].current, sorted(found))
    check("a longer number containing the address is not taken for it",
          all(e.value != "100.64.9.90" for e in report.exposures.values()))
    check("a value in a file *name* is found",
          any(e.in_paths for e in report.exposures.values() if e.value == "invented-host"))
    check("a value in a commit message is found",
          any(e.commits for e in report.exposures.values() if e.value == "other-invented-box"))
    people = {p.email: p for p in report.personal_identities()}
    check("a real email address on commits is found",
          "someone.real@example-mail.invalid" in people, sorted(people))
    check("a HOST\\user author name is found",
          any("machine name" in p.concern for p in report.personal_identities()))
    check("a noreply identity is not personal data", TARGET[1] not in people)
    check("the repository's owner is not reported as a leak",
          all(e.value != "example-owner" for e in report.exposures.values()))
    text, count = render(report)
    check("the report masks values by default",
          "someone.real" not in text and "100.64.9.9" not in text and count > 0, text)

    # --- the plan: private, outside the repository, owner untouched, checkout untouched --------
    try:
        rewrite_history.plan(repo, repo / "plan", seeds=SEEDS, target=TARGET)
        check("a plan folder inside the repository is refused", False)
    except ValueError:
        check("a plan folder inside the repository is refused", True)

    plan_dir = tmp / "private-plan"
    decided = rewrite_history.plan(repo, plan_dir, seeds=SEEDS, target=TARGET,
                                   extra={"secret-org-name": "example-org"})
    replacements = (plan_dir / "replacements.txt").read_text(encoding="utf-8")
    mailmap = (plan_dir / "mailmap.txt").read_text(encoding="utf-8")
    check("every found value has a rule; machine names get numbered placeholders",
          decided["replacements"]["invented-host"]["with"] == "machine-a"
          and decided["replacements"]["other-invented-box"]["with"] == "machine-b"
          and decided["replacements"]["100.64.9.9"]["with"] == "<tailnet-ip>", decided)
    check("hand-added values are carried", "secret-org-name" in decided["replacements"])
    check("the owner is never rewritten", "example-owner" not in decided["replacements"])
    check("rules are word-bounded regular expressions",
          "regex:(?i:(?<![A-Za-z0-9])100\\.64\\.9\\.9(?![A-Za-z0-9]))==><tailnet-ip>"
          in replacements,
          replacements)
    check("every identity of yours maps to the public one",
          f"{TARGET[0]} <{TARGET[1]}> Example Owner <someone.real@example-mail.invalid>" in mailmap
          and "HOSTBOX\\example-owner" in mailmap, mailmap)
    check("a collaborator's identity is never re-attributed to you",
          "collab@example-mail.invalid" not in mailmap
          and any(e["email"] == "collab@example-mail.invalid" for e in decided["others"]),
          decided["others"])
    check("generated bytecode is removed from history, not edited",
          "*.pyc" in decided["remove_paths"] and "__pycache__/*" in decided["remove_paths"],
          decided["remove_paths"])
    check("binary content is reported as only partly inspectable", decided["binary_paths"] >= 1)
    check("each ref records whether its tip holds a planned value",
          decided["refs"]["refs/heads/main"].get("clean_tip") is False,
          decided["refs"])  # the tip still holds the planted .pyc with a user path
    check("the mirror is a bare clone of branches and tags",
          (plan_dir / "mirror.git" / "HEAD").is_file()
          and "refs/heads/main" in decided["refs"]
          and not any(ref.startswith("refs/remotes/") for ref in decided["refs"]))
    check("planning changed nothing in the checkout",
          git(repo, "rev-parse", "HEAD") == before_head
          and git(repo, "status", "--porcelain") == before_status)
    check("the repository holds none of the plan", not (repo / "plan").exists()
          and "invented-host" not in git(repo, "status", "--porcelain", "--ignored"))

    # --- verification refuses an unrewritten mirror -----------------------------------------
    clean, lines = rewrite_history.verify(plan_dir)
    check("an unrewritten mirror fails verification, naming what remains",
          not clean and any("still present" in line for line in lines)
          and any("still published" in line for line in lines), lines)
    out = io.StringIO()
    with redirect_stdout(out):
        code = rewrite_history.main(["verify", str(plan_dir)])
    check("the verify command exits non-zero and prints no push steps", code == 1
          and "push --force" not in out.getvalue())

    # --- the rewrite itself, only when asked for -----------------------------------------------
    if os.environ.get("GITSPECOPS_RUN_REWRITE_TEST") == "1" and shutil.which("git-filter-repo"):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rewrite_history.main(["apply", str(plan_dir), "--yes"])
        check("apply rewrites the mirror and verifies clean", code == 0, out.getvalue())
        check("then prints the push steps", "push --force" in out.getvalue())
        mirror = plan_dir / "mirror.git"
        old_note = subprocess.run(["git", "-C", str(mirror), "log", "-p", "--all"],
                                  capture_output=True, text=True).stdout
        check("old file versions now hold placeholders",
              "<tailnet-ip>" in old_note and "100.64.9.9;" not in old_note)
        check("the checkout is still untouched", git(repo, "rev-parse", "HEAD") == before_head)
    else:
        print("skip  the rewrite itself (set GITSPECOPS_RUN_REWRITE_TEST=1 with git-filter-repo "
              "installed to run it; it touches only a temporary folder)")

# --- where output goes: inside gitSpecOps, but only somewhere git will never publish ---------
from Security._repo import is_ignored, output_dir  # noqa: E402

where = output_dir(ROOT / "some-scanned-repo")
check("reports land in this checkout's git-ignored output folder",
      ROOT / ".agents" / "output" in where.parents and is_ignored(ROOT, where / "report.txt"),
      where)
check("a tracked path is not mistaken for an ignored one", not is_ignored(ROOT, ROOT / "README.md"))

# --- gitleaks: optional, summarized, never required -------------------------------------------
from Security import scan_secrets  # noqa: E402

lines = scan_secrets.summarize([
    {"RuleID": "github-pat", "Commit": "a" * 40, "File": "notes.md", "Secret": "REDACTED"},
    {"RuleID": "github-pat", "Commit": "b" * 40, "File": "notes.md", "Secret": "REDACTED"},
    {"RuleID": "aws-access-token", "Commit": "b" * 40, "File": "deploy.sh", "Secret": "REDACTED"}])
check("a gitleaks summary counts rules, commits and files",
      "3 candidate secret(s) in 2 commit(s), 2 file(s)" in lines[0]
      and any("github-pat: 2" in line for line in lines), lines)
check("an empty gitleaks report reads as nothing found",
      scan_secrets.summarize([]) == ["gitleaks found nothing."])
original_find = scan_secrets.find_gitleaks
scan_secrets.find_gitleaks = lambda: None
try:
    err = io.StringIO()
    from contextlib import redirect_stderr  # noqa: E402
    with redirect_stderr(err):
        code = scan_secrets.main([str(ROOT)])
    check("without gitleaks: exit 2 and say how to install it, nothing else",
          code == 2 and "winget install" in err.getvalue())
finally:
    scan_secrets.find_gitleaks = original_find

# The commands are importable and answer --help by path from anywhere.
for name in ("scan_tree.py", "scan_history.py", "scan_secrets.py", "rewrite_history.py"):
    done = subprocess.run([sys.executable, str(ROOT / "Security" / name), "--help"],
                          capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=60)
    check(f"Security/{name} --help works from another folder", done.returncode == 0, done.stderr)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    for failure in FAILS:
        print(" -", failure)
    raise SystemExit(1)
print("\nALL-SECURITY-TESTS-PASS")
