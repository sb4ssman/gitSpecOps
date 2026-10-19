"""Remove personal data from a repository's history: plan, apply in a mirror, verify.

    python Security/rewrite_history.py plan   [REPO] [--as "Name <email>"] [--online]
                                               [--replace VALUE=REPLACEMENT] [--keep VALUE]
    python Security/rewrite_history.py apply  PLAN_DIR [--yes]
    python Security/rewrite_history.py verify PLAN_DIR

**plan** scans everything the repository's history holds (see `scan_history.py`) and writes,
into a private folder *outside* the repository (`<per-user gitSpecOps folder>/security/...`):

- `mailmap.txt` -- every published author/committer identity that is personal data, mapped to
  one public identity (default: this repository's configured `user.name` / `user.email`, which
  should be your GitHub noreply address);
- `replacements.txt` -- every personal value found in files, file names and commit messages,
  mapped to a placeholder (`<tailnet-ip>`, `machine-a`, `<library-root>`, ...). Word-bounded
  regular expressions, so a value is replaced only where the scanner found it. **This file holds
  the real values, which is why it never lives in the repository.** Review it; add lines for
  what no scan can know (a private organization's name) with `--replace` or by hand;
- `expected.json` -- what verification checks: the values and addresses that must be gone, and
  every ref's commit count and tip tree before the rewrite;
- `mirror.git` -- a bare clone of the repository's branches and tags (remote-tracking refs are
  left out, so nothing can be confused with them). The rewrite happens there and only there.

The repository's own owner name is never rewritten: it is the public identity of the
repository (its clone URL), not a leak.

**apply** runs `git filter-repo` inside `mirror.git` after a typed confirmation, then verifies.
It never touches the working checkout. `git filter-repo` must be installed
(https://github.com/newren/git-filter-repo).

**verify** proves the mirror is clean (no planned value, no old identity) and that nothing else
changed: same commit count on every ref, and an identical tip tree wherever the current files
held no planned value. Then it prints the push and re-clone steps. **Pushing is yours.** It
replaces published history (a forced push, which gitSpecOps never performs itself), and every
existing clone must be re-cloned, not pulled.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._confirm import confirm_typed  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import run, run_git  # noqa: E402
from Security._history import scan_history, tip_matches  # noqa: E402
from Security._patterns import SECRETS, mask  # noqa: E402
from Security._seeds import identity_seeds  # noqa: E402
from Security._repo import (is_ignored, output_dir, owner as repository_owner,  # noqa: E402
                            patterns_for)

EFFECT = "local"  # writes a private plan folder and rewrites a mirror clone; never the checkout

CONFIRMATION = "REWRITE"
REWRITE_TIMEOUT_SECONDS = 3600

#: Placeholder per kind of finding. Machine names are numbered (machine-a, machine-b, ...).
PLACEHOLDERS = {
    "a Windows user path": r"C:\Users\<you>",
    "a Windows drive path": "<library-root>",
    "a POSIX home path": "/home/<you>",
    "a real Tailscale address": "<tailnet-ip>",
    "a tailnet address": "<tailnet-ip>",
    "your home folder's name": "<you>",
    "a value you listed as never to publish": "<private>",
}
MACHINE_KINDS = ("a tailnet machine name", "this machine's host name")
ORGANIZATION_KIND = "a GitHub organization you belong to"
EMAIL_KIND = "your git email"
OWNER_KINDS = ("your gh login", "your git name")


def _git_identity(repo: Path) -> tuple[str, str]:
    name = run_git(repo, ["config", "user.name"]).stdout.strip()
    email = run_git(repo, ["config", "user.email"]).stdout.strip()
    return name, email


def _bounded(value: str) -> str:
    """The replacement rule for one value: case-insensitive, whole value only."""
    # A scoped flag, so rules can also be joined into one pattern (verification does).
    return rf"(?i:(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9]))"


#: Generated files that should never have been published. Removing them from history is
#: preferable to editing them: bytecode embeds the paths it was compiled from, and replacing
#: text inside it corrupts it.
GENERATED_GLOBS = ("*.pyc", "*.pyo", "*/__pycache__/*", "__pycache__/*", "*.class",
                   "*/.DS_Store", ".DS_Store", "*/Thumbs.db", "Thumbs.db")
ARCHIVE_SUFFIXES = (".zip", ".gz", ".tgz", ".7z", ".rar", ".tar", ".jar", ".whl", ".xz", ".bz2")


def _is_mine(name: str, email: str, mine_emails: set, my_names: set) -> bool:
    """Only the runner's own identities are re-attributed; every other contributor stays."""
    bare_name = name.rsplit("\\", 1)[-1].strip().lower()   # HOST\user -> user
    return email.lower() in mine_emails or bare_name in my_names


def build_plan(report, *, target: tuple[str, str], owner: str | None, keep=(),
               extra: dict | None = None, mine_emails=(), my_names=()) -> dict:
    """Pure: decide every replacement from a scan. Returns the plan as data.

    An author/committer identity is mapped to `target` only when it is provably the runner's:
    its email is in `mine_emails`, or its name (ignoring a `HOST\\` prefix) is in `my_names`.
    Anyone else's identity is listed under `others` and left exactly as it is -- rewriting a
    collaborator's commits to your name would be a false attribution, not a cleanup.
    """
    mine_emails = {e.lower() for e in mine_emails if e}
    my_names = {n.lower() for n in (*my_names, target[0], owner or "") if n}
    keep = {value.lower() for value in keep}
    replacements: dict[str, tuple[str, str]] = {}   # value -> (placeholder, kind)
    machines = sorted({e.value for e in report.exposures.values() if e.kind in MACHINE_KINDS},
                      key=str.lower)
    machine_names = {value.lower(): f"machine-{chr(ord('a') + i)}" if i < 26 else f"machine-{i}"
                     for i, value in enumerate(machines)}
    organizations = sorted({e.value for e in report.exposures.values()
                            if e.kind == ORGANIZATION_KIND}, key=str.lower)
    secrets = []
    current = set()
    for exposure in report.exposures.values():
        value = exposure.value
        if value.lower() in keep or (owner and value.lower() == owner.lower()):
            continue
        if exposure.kind in OWNER_KINDS:
            # The account name itself only leaks where it is not the repository's owner.
            continue
        if exposure.kind in SECRETS:
            placeholder = "***REMOVED***"
            secrets.append(value)
        elif exposure.kind in MACHINE_KINDS:
            placeholder = machine_names[value.lower()]
        elif exposure.kind == ORGANIZATION_KIND:
            placeholder = f"example-org-{organizations.index(value) + 1}"
        elif exposure.kind == EMAIL_KIND:
            placeholder = target[1]
        else:
            placeholder = PLACEHOLDERS.get(exposure.kind, "<removed>")
        replacements.setdefault(value, (placeholder, exposure.kind))
        if exposure.current:
            current.add(value)
    for value, placeholder in (extra or {}).items():
        replacements[value] = (placeholder, "added by hand")
    personal = report.personal_identities()
    ours = [p for p in personal if _is_mine(p.name, p.email, mine_emails, my_names)]
    others = [p for p in personal if p not in ours]
    remove = sorted({glob for glob in GENERATED_GLOBS
                     for path in report.paths if fnmatch.fnmatch(path, glob)})
    archives = sorted(path for path in report.binary if path.lower().endswith(ARCHIVE_SUFFIXES))
    return {
        "target": {"name": target[0], "email": target[1]},
        "mailmap": [{"name": p.name, "email": p.email, "commits": p.commits} for p in ours],
        "others": [{"name": p.name, "email": p.email, "commits": p.commits} for p in others],
        "replacements": {value: {"with": placeholder, "kind": kind}
                         for value, (placeholder, kind) in sorted(replacements.items())},
        "remove_paths": remove,
        "secrets": secrets,
        "current": sorted(current),
        "signed_commits": report.signed,
        "binary_paths": len(report.binary),
        "archives_not_inspected": archives,
    }


def _mailmap_text(plan: dict) -> str:
    target = f"{plan['target']['name']} <{plan['target']['email']}>"
    return "".join(f"{target} {entry['name']} <{entry['email']}>\n" for entry in plan["mailmap"])


def _replacements_text(plan: dict) -> str:
    """Rules only, one per line. git filter-repo has **no comment syntax**: every line is a rule,
    and a line without `==>` means "replace this literal text with ***REMOVED***". A `#` header
    once did exactly that to every file quoting it -- verification caught it before any push
    (2026-10-19). What each rule is for lives in expected.json and the printed summary."""
    return "".join(f"regex:{_bounded(value)}==>{rule['with']}\n"
                   for value, rule in plan["replacements"].items())


def _planned_pattern(decided: dict):
    """Every planned value as one pattern (the same rules filter-repo applies), or None."""
    values = list(decided["replacements"])
    return re.compile("|".join(f"(?:{_bounded(v)})" for v in values)) if values else None


def _refs(repo: Path) -> dict[str, dict]:
    """Every ref's commit count and tip tree, for proving later that nothing else changed."""
    refs = {}
    listing = run_git(repo, ["for-each-ref", "--format=%(refname)"]).stdout.split()
    for ref in listing:
        if ref.endswith("/HEAD"):
            continue
        tree = run_git(repo, ["rev-parse", f"{ref}^{{tree}}"]).stdout.strip()
        count = run_git(repo, ["rev-list", "--count", ref]).stdout.strip()
        if tree and count.isdigit():
            # Every file at the tip, so a failed comparison can name what changed: the rewrite
            # repacks the clone and the original tree objects are gone afterwards.
            files = {}
            for line in run_git(repo, ["ls-tree", "-r", "-z", ref]).stdout.split("\0"):
                meta, _, path = line.partition("\t")
                if path and len(meta.split()) == 3:
                    files[path] = meta.split()[2]
            refs[ref] = {"tree": tree, "commits": int(count), "files": files}
    return refs


def default_plan_dir(repo: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir(repo) / f"rewrite-{stamp}"


def plan(repo: Path, into: Path, *, seeds: dict, target: tuple[str, str] | None = None,
         keep=(), extra: dict | None = None, public_repositories=(), mine=()) -> dict:
    """Scan, decide, write the private plan folder and the mirror. Returns the plan.

    `mine` adds email addresses that are yours but no longer configured anywhere (an old
    personal address): identities using them are re-attributed to `target`.
    """
    repo, into = repo.resolve(), into.resolve()
    if into == repo or (repo in into.parents and not is_ignored(repo, into / "x")):
        raise ValueError("the plan folder holds the real values; inside the repository it must "
                         "be a folder git ignores (such as .agents/output/)")
    if into.exists() and any(into.iterdir()):
        raise ValueError(f"plan folder is not empty: {into}")
    target = target or _git_identity(repo)
    if not all(target):
        raise ValueError("no public identity to rewrite to: set user.name and user.email, or "
                         "pass --as 'Name <email>'")
    report = scan_history(repo, ["--all"], patterns_for(repo, seeds, public_repositories))
    decided = build_plan(report, target=target, owner=repository_owner(repo), keep=keep, extra=extra,
                         mine_emails=[*seeds.get("your git email", []), *mine],
                         my_names=[*seeds.get("your git name", []),
                                   *seeds.get("your gh login", [])])
    origin = run_git(repo, ["remote", "get-url", "origin"]).stdout.strip()
    into.mkdir(parents=True, exist_ok=True)
    mirror = into / "mirror.git"
    cloned = run(["git", "clone", "--quiet", "--bare", str(repo), str(mirror)],
                 timeout=REWRITE_TIMEOUT_SECONDS)
    if cloned.returncode:
        raise RuntimeError(f"could not make the mirror: {cloned.stderr.strip()}")
    remote_branches = [ref.split("/", 3)[3] for ref in run_git(
        repo, ["for-each-ref", "--format=%(refname)", "refs/remotes/origin"]).stdout.split()
        if not ref.endswith("/HEAD")]
    refs = _refs(mirror)
    planned = _planned_pattern(decided)
    for ref, facts in refs.items():
        # Per ref: a tip holding no planned value must come out byte-identical. (The published
        # tip may still hold one that the local tip has already lost.)
        facts["clean_tip"] = planned is None or not tip_matches(mirror, ref, planned)
    decided.update({"repository": str(repo), "origin": origin, "refs": refs,
                    "remote_branches": remote_branches,
                    "planned_at": datetime.now().isoformat(timespec="seconds")})
    (into / "mailmap.txt").write_text(_mailmap_text(decided), encoding="utf-8")
    (into / "replacements.txt").write_text(_replacements_text(decided), encoding="utf-8")
    (into / "expected.json").write_text(json.dumps(decided, indent=2), encoding="utf-8")
    return decided


def verify(plan_dir: Path) -> tuple[bool, list[str]]:
    """(clean, report lines) for the mirror in `plan_dir` against its plan."""
    plan_dir = plan_dir.resolve()
    expected = json.loads((plan_dir / "expected.json").read_text(encoding="utf-8"))
    mirror = plan_dir / "mirror.git"
    planned = _planned_pattern(expected)
    report = scan_history(mirror, ["--all"], {"a planned value": planned} if planned else {})
    problems = []
    for exposure in report.exposures.values():
        problems.append(f"still present: {mask(exposure.value)} in "
                        f"{len(exposure.paths) + len(exposure.in_paths)} path(s), "
                        f"{len(exposure.commits)} message(s)")
    old = {entry["email"].lower() for entry in expected["mailmap"]}
    old_names = {entry["name"] for entry in expected["mailmap"] if "\\" in entry["name"]}
    for identity in report.identities.values():
        if identity.email.lower() in old or identity.name in old_names:
            problems.append(f"still published: {mask(identity.email)} / {mask(identity.name)} "
                            f"on {identity.commits} commit(s)")
    removed = expected.get("remove_paths") or []
    for path in sorted(report.paths):
        if any(fnmatch.fnmatch(path, glob) for glob in removed):
            problems.append(f"still published: {path} (planned for removal)")
    after = _refs(mirror)
    # Removing paths may change the current files and drop commits that only touched them.
    unchanged_files = not expected["current"] and not removed
    for ref, before in expected["refs"].items():
        now = after.get(ref)
        if now is None:
            if ref.startswith("refs/heads/") or ref.startswith("refs/tags/"):
                problems.append(f"{ref} is gone after the rewrite")
            continue
        if now["commits"] > before["commits"] or (now["commits"] < before["commits"]
                                                  and not removed):
            problems.append(f"{ref}: {before['commits']} commits before, {now['commits']} after")
        if (unchanged_files or (before.get("clean_tip") and not removed)) \
                and now["tree"] != before["tree"]:
            before_files, after_files = before.get("files") or {}, now.get("files") or {}
            changed = sorted(path for path in set(before_files) | set(after_files)
                             if before_files.get(path) != after_files.get(path))
            problems.append(f"{ref}: the current files changed, but they held no planned value: "
                            + (", ".join(changed[:10]) + (" ..." if len(changed) > 10 else "")
                               if changed else "(file list not recorded)"))
    lines = [f"Verified {report.commits} commit(s), {report.blobs} file version(s) in {mirror}"]
    lines += [f"  PROBLEM: {p}" for p in problems] or [
        "  clean: no planned value, no old identity; every ref has the same commit count"
        + ("; current files byte-identical on " + ", ".join(
            ref for ref, before in expected["refs"].items()
            if unchanged_files or (before.get("clean_tip") and not removed))
           if unchanged_files or any(b.get("clean_tip") for b in expected["refs"].values())
           else "")]
    return not problems, lines


def push_steps(plan_dir: Path) -> list[str]:
    expected = json.loads((plan_dir / "expected.json").read_text(encoding="utf-8"))
    mirror = plan_dir.resolve() / "mirror.git"
    remote = expected.get("origin") or "<your remote URL>"
    branches = sorted(expected.get("remote_branches") or [])
    heads = " ".join(f"refs/heads/{b}" for b in branches) or "refs/heads/main"
    tags = any(ref.startswith("refs/tags/") for ref in expected["refs"])
    return [
        "Next steps are yours (a forced push replaces published history):",
        "  1. Push the rewritten branches that exist on the remote:",
        f'     git -C "{mirror}" push --force {remote} {heads}'
        + (" 'refs/tags/*'" if tags else ""),
        "     (local-only branches in the mirror are not pushed; push any you want explicitly)",
        "  2. Re-clone this repository into a NEW folder; copy across ignored local files you keep",
        "     (for gitSpecOps: .agents/output and .agents/tools); retire the old checkout only",
        "     after comparing. Never pull old history into new: a pull merges it back.",
        "  3. Every other clone, on every machine: re-clone; do not pull.",
        "  4. The host may keep serving old commits by SHA from caches. With no forks or pull",
        "     requests, ask the host's support to purge them if that matters to you.",
        "  5. Short commit SHAs quoted inside files (work logs, notes) no longer resolve.",
    ]


def _summary(decided: dict, into: Path) -> list[str]:
    lines = [f"Plan written to {into} (private: it holds the real values)."]
    lines.append(f"Identities -> {decided['target']['name']} <{decided['target']['email']}>:")
    lines += [f"  {mask(e['email'])} / {mask(e['name'])} ({e['commits']} commit(s))"
              for e in decided["mailmap"]] or ["  none"]
    lines.append(f"Values replaced in files, file names and messages: "
                 f"{len(decided['replacements'])}")
    lines += [f"  {rule['kind']}: {mask(value)} -> {rule['with']}"
              for value, rule in decided["replacements"].items()]
    if decided["others"]:
        lines.append("Other people's identities, left exactly as they are (claim an address of "
                     "yours with --mine):")
        lines += [f"  {mask(e['email'])} / {mask(e['name'])} ({e['commits']} commit(s))"
                  for e in decided["others"]]
    if decided["remove_paths"]:
        lines.append("Generated files removed from all history (never edited -- bytecode embeds "
                     f"paths): {', '.join(decided['remove_paths'])}")
    if decided["signed_commits"]:
        lines.append(f"Note: {decided['signed_commits']} signed commit(s). Rewriting removes "
                     "their signatures (a host shows them unverified). Decide before applying.")
    if decided["archives_not_inspected"]:
        lines.append(f"Not inspected inside: {len(decided['archives_not_inspected'])} archive "
                     "path(s) -- unpack and scan them separately: "
                     + ", ".join(decided["archives_not_inspected"][:5]))
    if decided["binary_paths"]:
        lines.append(f"{decided['binary_paths']} binary path(s) were scanned as raw bytes only; "
                     "compressed formats (images, archives) can hide text this cannot see.")
    lines.append("This is a pattern scan, not a security clearance: run a dedicated secret "
                 "scanner (gitleaks, trufflehog) too.")
    if decided["secrets"]:
        lines.append(f"!! {len(decided['secrets'])} SECRET(S): rotate them first -- the rewrite "
                     "does not un-publish what was already read.")
    if decided["current"]:
        lines.append(f"Note: {len(decided['current'])} value(s) are still in the current files; "
                     "the rewrite changes those files too.")
    lines += ["Review replacements.txt; add what no scan can know (a private organization or",
              "repository name) with --replace or by hand. Then:",
              f'  python Security/rewrite_history.py apply "{into}"']
    return lines


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Remove personal data from history.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="scan and write the private plan and the mirror")
    p.add_argument("repo", nargs="?", type=Path, default=Path("."))
    p.add_argument("--into", type=Path, help="plan folder (default: per-user gitSpecOps folder)")
    p.add_argument("--as", dest="identity", metavar="'Name <email>'",
                   help="the public identity to rewrite to (default: user.name/user.email)")
    p.add_argument("--replace", action="append", default=[], metavar="VALUE=REPLACEMENT")
    p.add_argument("--keep", action="append", default=[], metavar="VALUE",
                   help="a found value to leave alone")
    p.add_argument("--public-repo", action="append", default=[], metavar="NAME")
    p.add_argument("--mine", action="append", default=[], metavar="EMAIL",
                   help="an address of yours (e.g. an old personal one) to re-attribute")
    p.add_argument("--online", action="store_true",
                   help="also look for the GitHub organizations your gh login belongs to")
    p.add_argument("--no-tailnet", action="store_true")
    a = sub.add_parser("apply", help="rewrite the plan's mirror with git filter-repo, then verify")
    a.add_argument("plan_dir", type=Path)
    a.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    v = sub.add_parser("verify", help="prove the mirror is clean; print the push steps")
    v.add_argument("plan_dir", type=Path)
    args = parser.parse_args(argv)

    if args.action == "plan":
        repo = args.repo.resolve()
        target = None
        if args.identity:
            match = re.fullmatch(r"\s*(.+?)\s*<([^>]+)>\s*", args.identity)
            if not match:
                parser.error("--as must look like: Name <email>")
            target = (match.group(1), match.group(2))
        extra = {}
        for item in args.replace:
            value, sep, replacement = item.partition("=")
            if not sep or not value:
                parser.error("--replace must look like: VALUE=REPLACEMENT")
            extra[value] = replacement
        into = args.into or default_plan_dir(repo)
        seeds = identity_seeds(tailnet=not args.no_tailnet, online=args.online, cwd=repo)
        decided = plan(repo, into, seeds=seeds, target=target, keep=args.keep, extra=extra,
                       public_repositories=args.public_repo, mine=args.mine)
        print("\n".join(_summary(decided, into.resolve())))
        return 0

    plan_dir = args.plan_dir.resolve()
    if not (plan_dir / "expected.json").is_file() or not (plan_dir / "mirror.git").is_dir():
        print(f"Not a plan folder (expected.json and mirror.git): {plan_dir}", file=sys.stderr)
        return 2
    if args.action == "apply":
        print(f"This rewrites every commit in {plan_dir / 'mirror.git'} (the mirror only; your "
              "checkout is not touched).")
        if not args.yes and not confirm_typed(CONFIRMATION, f"Type {CONFIRMATION} to proceed: "):
            print("Nothing was rewritten.")
            return 1
        expected = json.loads((plan_dir / "expected.json").read_text(encoding="utf-8"))
        removal = [arg for glob in expected.get("remove_paths") or []
                   for arg in ("--path-glob", glob)]
        rewritten = run(["git", "filter-repo", "--force",
                         "--mailmap", str(plan_dir / "mailmap.txt"),
                         "--replace-text", str(plan_dir / "replacements.txt"),
                         "--replace-message", str(plan_dir / "replacements.txt"),
                         *(removal + ["--invert-paths"] if removal else [])],
                        cwd=plan_dir / "mirror.git", timeout=REWRITE_TIMEOUT_SECONDS)
        sys.stdout.write(rewritten.stdout)
        sys.stderr.write(rewritten.stderr)
        if rewritten.returncode:
            print("git filter-repo failed; the mirror may be partly rewritten. Make a new plan.",
                  file=sys.stderr)
            return rewritten.returncode
    clean, lines = verify(plan_dir)
    print("\n".join(lines))
    if clean:
        print("\n".join(push_steps(plan_dir)))
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
