"""How a history rewrite is planned, verified and followed: the logic behind
`rewrite_history.py` (and `scan_folder.py --plan`), which only parse arguments and print.

See `rewrite_history.py` for what each step does and why. Nothing here pushes: a forced push
replaces published history, and that step is always the person's own.
"""
from __future__ import annotations

import bisect
import fnmatch
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from Basic._confirm import prompt_yes_no
from Basic._discovery import find_repos
from Basic._run import run, run_git
from Security._history import NOREPLY_SUFFIX, scan_history, tip_matching_files
from Security._patterns import SECRETS, mask
from Security._repo import (is_ignored, output_dir, owner as repository_owner, patterns_for,
                            tracked_files)

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
#: filter-repo's `--replace-text` skips any blob with a NUL byte in its first 8 KiB, and cannot
#: see into a compressed one. A planned value there survives the rewrite: say so at plan time.
UNREACHABLE_BINARY = "a binary file (text replacement skips binary files)"
UNREACHABLE_ARCHIVE = "inside an archive (text replacement cannot reach it)"


def _is_mine(name: str, email: str, mine_emails: set, my_names: set) -> bool:
    """Only the runner's own identities are re-attributed; every other contributor stays."""
    bare_name = name.rsplit("\\", 1)[-1].strip().lower()   # HOST\user -> user
    return email.lower() in mine_emails or bare_name in my_names


def _outer(path: str) -> str:
    """The file in history: `archive.zip!member` lives in `archive.zip`."""
    return path.split("!", 1)[0]


def widen_seeds(report, seeds: dict, mine=()) -> dict | None:
    """`seeds` plus every real address your own commits used, or None when there is none new.

    The configured address is usually the noreply one; the address history actually holds --
    an old personal one -- is then known to no seed, so file contents were never searched for
    it. Found 2026-10-19: a personal address on 136 commits, under two names, in one repository.
    """
    names = {n.lower() for n in [*seeds.get("your git name", []),
                                 *seeds.get("your gh login", [])] if n}
    known = {e.lower() for e in [*seeds.get("your git email", []), *mine] if e}
    claimed = {p.email for p in report.personal_identities()
               if _is_mine(p.name, p.email, known, names)}
    new = sorted(e for e in claimed if e.lower() not in known and "@" in e
                 and not e.lower().endswith(NOREPLY_SUFFIX))
    if not new:
        return None
    return {**seeds, EMAIL_KIND: [*seeds.get(EMAIL_KIND, []), *new]}


def build_plan(report, *, target: tuple[str, str], owner: str | None, keep=(),
               extra: dict | None = None, mine_emails=(), my_names=(), remove=(),
               claim=()) -> dict:
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
    # An address one of your identities used is yours under every name it appears with (an
    # old account name, a HOST\user): one email, one person.
    mine_emails |= {p.email.lower() for p in ours}
    ours = [p for p in personal if _is_mine(p.name, p.email, mine_emails, my_names)]
    # An address claimed with --mine is re-attributed even where it is no personal data -- the
    # noreply address of another account of yours still names that account on every commit.
    claim = {email.lower() for email in claim if email}
    ours += [identity for identity in report.identities.values()
             if identity.email.lower() in claim and identity not in ours
             and (identity.name, identity.email.lower()) != (target[0], target[1].lower())]
    others = [p for p in personal if p not in ours]
    remove = sorted({glob for glob in GENERATED_GLOBS
                     for path in report.paths if fnmatch.fnmatch(path, glob)} | set(remove))

    def removed(path: str) -> bool:
        return any(fnmatch.fnmatch(_outer(path), glob) for glob in remove)

    unreachable: dict[str, str] = {}
    for exposure in report.exposures.values():
        if exposure.value not in replacements:
            continue
        for path in exposure.paths:
            if removed(path):
                continue
            if "!" in path:
                unreachable.setdefault(_outer(path), UNREACHABLE_ARCHIVE)
            elif path in report.binary:
                unreachable.setdefault(path, UNREACHABLE_BINARY)
    located = sorted(path for path in report.located_images
                     if not removed(path) and _outer(path).lower() not in keep)
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
        "archives_opened": len(report.archives),
        "not_inspected": dict(sorted(report.uninspected.items())),
        "unreachable": dict(sorted(unreachable.items())),
        "images_with_location": located,
        "kept": sorted(keep),
    }


def _mailmap_text(plan: dict) -> str:
    target = f"{plan['target']['name']} <{plan['target']['email']}>"
    return "".join(f"{target} {entry['name']} <{entry['email']}>\n" for entry in plan["mailmap"])


def _replacements_text(plan: dict) -> str:
    """Rules only, one per line. git filter-repo has **no comment syntax**: every line is a rule,
    and a line without `==>` means "replace this literal text with ***REMOVED***". A `#` header
    once did exactly that to every file quoting it -- verification caught it before any push
    (2026-10-19). What each rule is for lives in expected.json and the printed summary.

    A regex rule's replacement is a `re.sub` template, so a backslash in it is an escape:
    `C:\\Users\\<you>` crashed filter-repo with "bad escape \\U" (found 2026-10-19 by the gated
    end-to-end test, before any real repository needed it). Backslashes are doubled."""
    return "".join(f"regex:{_bounded(value)}==>{rule['with'].replace(chr(92), chr(92) * 2)}\n"
                   for value, rule in plan["replacements"].items())


def _filename_callback(rules: Path) -> str:
    """A `--filename-callback` body applying the rules file to every path in history.

    `--replace-text` edits file *contents* only, so `notes-from-<machine>.log` kept the machine
    name (found 2026-10-19 by the gated end-to-end test). The body reads the same rules file,
    once, so no real value is ever placed on a command line.
    """
    return (
        "import re\n"
        "if filename is None:\n"   # already removed by --invert-paths
        "    return None\n"
        "cache = globals().setdefault('_gitspecops_filename_rules', [])\n"
        "if not cache:\n"
        f"    for line in open({str(rules)!r}, 'rb').read().splitlines():\n"
        "        pattern, _, replacement = line[len(b'regex:'):].partition(b'==>')\n"
        "        cache.append((re.compile(pattern), replacement))\n"
        "for pattern, replacement in cache:\n"
        "    filename = pattern.sub(replacement, filename)\n"
        "return filename\n"
    )


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
         keep=(), extra: dict | None = None, public_repositories=(), mine=(),
         remove=(), report=None) -> dict:
    """Scan, decide, write the private plan folder and the mirror. Returns the plan.

    `mine` adds email addresses that are yours but no longer configured anywhere (an old
    personal address): identities using them are re-attributed to `target`. `remove` names
    paths (or globs) to drop from all history -- the only fix for a value text replacement
    cannot reach (a binary file, an archive, a photo's GPS position).
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
    if report is None:   # a caller that already scanned (scan_folder) passes its report
        report = scan_history(repo, ["--all"], patterns_for(repo, seeds, public_repositories))
        wider = widen_seeds(report, seeds, mine)
        if wider:   # your own old address: search the contents for it too
            seeds = wider
            report = scan_history(repo, ["--all"], patterns_for(repo, seeds, public_repositories))
    decided = build_plan(report, target=target, owner=repository_owner(repo), keep=keep,
                         extra=extra, remove=remove, claim=mine,
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
        facts["planned_files"] = sorted(tip_matching_files(mirror, ref, planned)) \
            if planned else []
        facts["clean_tip"] = not facts["planned_files"]
    decided.update({"repository": str(repo), "origin": origin, "refs": refs,
                    "remote_branches": remote_branches,
                    "planned_at": datetime.now().isoformat(timespec="seconds")})
    (into / "mailmap.txt").write_text(_mailmap_text(decided), encoding="utf-8")
    (into / "replacements.txt").write_text(_replacements_text(decided), encoding="utf-8")
    (into / "expected.json").write_text(json.dumps(decided, indent=2), encoding="utf-8")
    # Masked, like the screen: safe to read anywhere, and what `apply` asks you to review.
    (into / "summary.txt").write_text("\n".join(_summary(decided, into)) + "\n",
                                      encoding="utf-8")
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
        stuck = sorted({_outer(path) for path in exposure.paths
                        if "!" in path or path in report.binary})
        problems.append(f"still present: {mask(exposure.value)} in "
                        f"{len(exposure.paths) + len(exposure.in_paths)} path(s), "
                        f"{len(exposure.commits)} message(s)"
                        + (f" -- binary or archived, so text replacement cannot reach it: "
                           f"{', '.join(stuck[:5])} (plan again with --remove-path)"
                           if stuck else ""))
    kept = set(expected.get("kept") or [])
    for path in sorted(report.located_images):
        if _outer(path).lower() not in kept:
            problems.append(f"still published: GPS position in {path} (plan again with "
                            f"--remove-path, or --keep the path to accept it)")
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
    rules = [(re.compile(_bounded(value)), rule["with"].replace("\\", "\\\\"))
             for value, rule in expected["replacements"].items()]

    def renamed(path: str) -> str:
        for pattern, replacement in rules:
            path = pattern.sub(replacement, path)
        return path

    def accounted(path: str, before_files: dict, after_files: dict, planned_files: set) -> bool:
        """A tip file may differ only for a reason the plan gave."""
        if path in planned_files or any(fnmatch.fnmatch(path, glob) for glob in removed):
            return True
        if path in before_files and path not in after_files:     # renamed by a rule
            return renamed(path) != path and renamed(path) in after_files
        if path in after_files and path not in before_files:     # the new name
            return any(renamed(old) == path for old in before_files if old not in after_files)
        return False

    for ref, before in expected["refs"].items():
        now = after.get(ref)
        if now is None:
            if ref.startswith("refs/heads/") or ref.startswith("refs/tags/"):
                problems.append(f"{ref} is gone after the rewrite")
            continue
        if now["commits"] > before["commits"] or (now["commits"] < before["commits"]
                                                  and not removed):
            problems.append(f"{ref}: {before['commits']} commits before, {now['commits']} after")
        if now["tree"] == before["tree"]:
            continue
        before_files, after_files = before.get("files") or {}, now.get("files") or {}
        planned_files = set(before.get("planned_files") or [])
        changed = sorted(path for path in set(before_files) | set(after_files)
                         if before_files.get(path) != after_files.get(path)
                         and not accounted(path, before_files, after_files, planned_files))
        if changed or not before_files:
            problems.append(f"{ref}: the current files changed, but they held no planned value: "
                            + (", ".join(changed[:10]) + (" ..." if len(changed) > 10 else "")
                               if changed else "(file list not recorded)"))
    lines = [f"Verified {report.commits} commit(s), {report.blobs} file version(s) in {mirror}"]
    lines += [f"  PROBLEM: {p}" for p in problems] or [
        "  clean: no planned value, no old identity; no ref gained a commit; every current file "
        "is byte-identical except those that held a planned value, were removed or renamed"]
    return not problems, lines


def push_command(plan_dir: Path) -> str:
    """The forced push that publishes one plan's rewritten mirror."""
    expected = json.loads((plan_dir / "expected.json").read_text(encoding="utf-8"))
    mirror = plan_dir.resolve() / "mirror.git"
    remote = expected.get("origin") or "<your remote URL>"
    branches = sorted(expected.get("remote_branches") or [])
    heads = " ".join(f"refs/heads/{b}" for b in branches) or "refs/heads/main"
    tags = any(ref.startswith("refs/tags/") for ref in expected["refs"])
    return f'git -C "{mirror}" push --force {remote} {heads}' + (" 'refs/tags/*'" if tags else "")


def push_steps(plan_dirs) -> list[str]:
    """What to do after a clean `apply`, for one plan or a set rewritten together."""
    plan_dirs = [Path(plan_dirs)] if isinstance(plan_dirs, (str, Path)) else list(plan_dirs)
    quoted = " ".join(f'"{path.resolve()}"' for path in plan_dirs)
    return [
        "Next steps are yours (a forced push replaces published history):",
        "  1. Publish: one forced push per repository (pause any ruleset that blocks force",
        "     pushes for this push only):",
        *(f"       {push_command(path)}" for path in plan_dirs),
        "  2. Then, once, for this machine's checkouts -- moves each onto its new history and",
        "     updates the commit ids quoted in its files (never commits; review, commit, push):",
        f"       python Security/rewrite_history.py finish {quoted}",
        "  3. Every other machine's clone: `python Security/rewrite_history.py follow <repo>`",
        "     (or re-clone). A plain `git pull` there refuses -- the histories share no commit;",
        "     never force it with --allow-unrelated-histories.",
        "  4. The host may keep serving old commits by SHA from caches. With no forks or pull",
        "     requests, ask the host's support to purge them if that matters to you.",
    ]


# --- relink: commit ids quoted inside files -------------------------------------------------

#: A commit id as people quote one: 7 to 40 lowercase hex digits standing alone.
SHA_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")


def commit_map(plan_dir: Path) -> dict[str, str]:
    """`{old commit: new commit}` from an applied plan (filter-repo's own record)."""
    path = Path(plan_dir) / "mirror.git" / "filter-repo" / "commit-map"
    if not path.is_file():
        raise ValueError(f"no commit map in {plan_dir}: apply this plan first")
    mapping = {}
    for line in path.read_text(encoding="ascii").splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[0] != parts[1] and set(parts[1]) != {"0"}:
            mapping[parts[0]] = parts[1]
    return mapping


def references(text: str, mapping: dict[str, str], olds: list[str] | None = None) -> list:
    """`(offset, old token, new token)` for every quoted id naming exactly one old commit."""
    olds = olds if olds is not None else sorted(mapping)
    found = []
    for match in SHA_TOKEN.finditer(text):
        token = match.group(0)
        index = bisect.bisect_left(olds, token)
        hits = [old for old in olds[index:index + 2] if old.startswith(token)]
        if len(hits) == 1:
            found.append((match.start(), token, mapping[hits[0]][:len(token)]))
    return found


def relink(plan_dirs, checkout: Path, *, write: bool = False,
           edited: list | None = None) -> tuple[list[str], int]:
    """(report lines, references found) in `checkout`'s tracked text files; edits when `write`.

    `plan_dirs` is one applied plan or several: their commit maps are merged, because
    repositories rewritten together quote each other's commits. Never commits: the edits are
    left in the work tree for the person to review and commit.
    """
    plan_dirs = [plan_dirs] if isinstance(plan_dirs, (str, Path)) else list(plan_dirs)
    mapping = {old: new for plan_dir in plan_dirs for old, new in commit_map(plan_dir).items()}
    olds = sorted(mapping)
    history = set(run_git(checkout, ["rev-list", "HEAD"]).stdout.split())
    if history & set(mapping):
        raise ValueError(f"{checkout} is still on the old history: run `follow` first")
    lines, total = [], 0
    for name in tracked_files(checkout) or []:
        path = checkout / name
        try:
            raw = path.read_bytes()
            if b"\0" in raw[:8192]:
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = references(text, mapping, olds)
        if not found:
            continue
        total += len(found)
        for offset, old, new in found:
            lines.append(f"  {name}:{text.count(chr(10), 0, offset) + 1}: {old} -> {new}")
        if write:
            for offset, old, new in reversed(found):
                text = text[:offset] + new + text[offset + len(old):]
            path.write_bytes(text.encode("utf-8"))
            if edited is not None:
                edited.append(name)
    return lines, total


# --- follow: move a clone made before the rewrite -------------------------------------------

def published_before(repo: Path, new_tip: str) -> list[str]:
    """Every value a remote-tracking ref held that is not part of the new history.

    A remote-tracking ref's reflog records each commit the remote was seen to hold; the values
    unrelated to `new_tip` are the old history as published. Commits reachable from none of
    them were never pushed. (Matching rewritten commits by their author and committer times was
    tried first and is wrong: commits made within one second share both.)

    The reflog files are read directly, old and new value of every line: a fresh clone keeps
    no `origin/main` log of its own, so the value it was cloned at survives only as the *old*
    value of the first fetch (and in `origin/HEAD`'s clone entry), which `git reflog show`
    does not print.
    """
    logs = run_git(repo, ["rev-parse", "--git-path", "logs/refs/remotes"]).stdout.strip()
    folder = Path(logs) if Path(logs).is_absolute() else repo / logs
    values = []
    for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            values += [value for value in line.split()[:2]
                       if len(value) >= 40 and set(value) != {"0"} and value not in values]
    current = run_git(repo, ["for-each-ref", "--format=%(objectname)", "refs/remotes"]).stdout
    values += [value for value in current.split() if value not in values]
    return [value for value in values
            if run_git(repo, ["merge-base", value, new_tip]).returncode == 1]


def assess(repo: Path, *, fetch: bool = True) -> dict:
    """What `follow` would do for one checkout. Changes nothing but a fetch.

    `action` is "move" (the branch predates a rewrite and nothing would be lost), "current"
    (nothing to follow), "skip" (no upstream) or "refuse" (with `why`: something could be lost,
    or nothing proves it could not).
    """
    repo = Path(repo).resolve()
    found = {"repo": repo, "action": "refuse", "why": "", "hint": "", "stale": []}
    branch = run_git(repo, ["branch", "--show-current"]).stdout.strip()
    found["branch"] = branch
    if not branch:
        found["why"] = "detached HEAD: check out the branch to move first"
        return found
    if fetch:
        fetched = run_git(repo, ["fetch", "--prune"], timeout=REWRITE_TIMEOUT_SECONDS)
        if fetched.returncode:
            found["why"] = f"fetch failed: {fetched.stderr.strip()}"
            return found
    upstream = run_git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name",
                              "@{upstream}"]).stdout.strip()
    found["upstream"] = upstream
    if not upstream:
        found.update(action="skip", why=f"{branch} has no upstream")
        return found
    if run_git(repo, ["merge-base", "HEAD", upstream]).returncode == 0:
        found.update(action="current", why=f"{branch} shares history with {upstream}")
        return found
    if run_git(repo, ["status", "--porcelain", "--untracked-files=no"]).stdout.strip():
        found["why"] = ("uncommitted changes to tracked files: commit or stash them first (or "
                        "re-clone into a new folder and carry them over)")
        return found
    new_tip = run_git(repo, ["rev-parse", upstream]).stdout.strip()
    published = published_before(repo, new_tip)
    if not published:
        found["why"] = ("no record of what the remote held before the rewrite (no "
                        "remote-tracking reflog entry from the old history), so unpushed work "
                        "cannot be ruled out: re-clone into a new folder and compare instead")
        return found
    alone = run_git(repo, ["rev-list", "HEAD", "--not", *published]).stdout.split()
    if alone:
        subjects = [run_git(repo, ["log", "-1", "--format=%h %s", sha]).stdout.strip()
                    for sha in alone[:20]]
        found["why"] = (f"{len(alone)} commit(s) on {branch} were never on the remote; moving "
                        "would hide them:\n" + "\n".join(f"    {s}" for s in subjects))
        # The newest commit of this branch that the remote held: where the local work starts.
        base = run_git(repo, ["merge-base", "HEAD", *published]).stdout.strip()
        if base:
            found["hint"] = ("check their author identity, then replay them onto the new "
                             f"history with: git rebase --onto {upstream} {base[:12]} {branch}")
        return found
    # Old history = related to this branch's old tip and not to the new upstream (an unrelated
    # orphan branch such as gh-pages is neither, and is left out).
    found["stale"] = [other for other in run_git(repo, ["for-each-ref", "--format=%(refname:short)",
                                                        "refs/heads", "refs/tags"]).stdout.split()
                      if other != branch
                      and run_git(repo, ["merge-base", other, "HEAD"]).returncode == 0
                      and run_git(repo, ["merge-base", other, upstream]).returncode]
    found.update(action="move", old_tip=run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout
                 .strip(), new_tip=new_tip[:7])
    return found


def _move(found: dict) -> bool:
    """`git reset --keep` onto the upstream, for an assessment that said "move"."""
    moved = run_git(found["repo"], ["reset", "--keep", found["upstream"]])
    if moved.returncode:
        print(f"  git reset --keep refused: {moved.stderr.strip()}", file=sys.stderr)
        return False
    if found["stale"]:
        print("  still pointing into the old history (pushing any of these would publish it "
              "again) -- delete or move each: " + ", ".join(found["stale"]))
    return True


def follow(repo: Path, *, fetch: bool = True, assume_yes: bool = False) -> int:
    """Move the checked-out branch of a pre-rewrite clone onto its rewritten upstream.

    Refuses when anything would be lost: uncommitted changes to tracked files, or a commit on
    the branch that the remote never held before the rewrite (work made only in this clone, as
    the remote-tracking reflogs show), or no record of the old history at all. Other local
    branches and tags still pointing into the old history are named, not moved.
    """
    found = assess(repo, fetch=fetch)
    if found["action"] in ("current", "skip"):
        print(f"{found['why']}: nothing to follow"
              + (" (a normal pull handles it)." if found["action"] == "current" else "."))
        return 0 if found["action"] == "current" else 2
    if found["action"] == "refuse":
        print(f"Nothing was changed: {found['why']}", file=sys.stderr)
        if found["hint"]:
            print(found["hint"], file=sys.stderr)
        return 1
    print(f"Every commit on {found['branch']} was on the remote before the rewrite.")
    print(f"Move {found['branch']}: {found['old_tip']} (old history) -> {found['new_tip']} with "
          "`git reset --keep`.")
    if not assume_yes and not prompt_yes_no("Move it now?", default=False):
        print("Nothing was changed.")
        return 1
    if not _move(found):
        return 1
    print(f"Moved {found['branch']} onto {found['upstream']}. The old commits stay in this "
          "clone's reflog, on no branch, until git expires them; nothing pushes them.")
    return 0


def repositories_under(paths, *, match=(), depth: int = 3) -> list[Path]:
    """Every checkout at or under `paths` whose origin URL contains one of `match` (any, when
    none is given)."""
    found = []
    for path in (Path(p).resolve() for p in paths):
        if (path / ".git").exists():
            found.append(path)
        else:
            found += [Path(hit.path) for hit in find_repos(path, max_depth=depth)
                      if hit.kind != "bare"]
    match = [text.lower() for text in match]
    return [repo for repo in dict.fromkeys(found)
            if not match or any(text in run_git(repo, ["remote", "get-url", "origin"])
                                .stdout.lower() for text in match)]


def follow_many(paths, *, match=(), depth: int = 3, fetch: bool = True,
                assume_yes: bool = False) -> int:
    """`follow` for every checkout under `paths`: assess all, show all, ask once, move.

    One line on another machine handles everything it holds: current checkouts are left
    alone, refusals are listed with the reason, and nothing moves before the one answer.
    """
    repos = repositories_under(paths, match=match, depth=depth)
    if not repos:
        print("No matching repositories found.", file=sys.stderr)
        return 2
    print(f"Checking {len(repos)} repositor{'y' if len(repos) == 1 else 'ies'} (fetching each)...")
    results = [assess(repo, fetch=fetch) for repo in repos]
    moves = [r for r in results if r["action"] == "move"]
    refused = [r for r in results if r["action"] == "refuse"]
    current = [r for r in results if r["action"] in ("current", "skip")]
    print(f"\nAlready current or nothing to follow: {len(current)}")
    if refused:
        print(f"Refused -- nothing will change in these ({len(refused)}):")
        for r in refused:
            print(f"  {r['repo']}: {r['why']}")
            if r["hint"]:
                print(f"    {r['hint']}")
    if not moves:
        print("Nothing to move.")
        return 1 if refused else 0
    print(f"To move onto the rewritten history ({len(moves)}):")
    print("\n".join(f"  {r['repo']}  {r['branch']}: {r['old_tip']} -> {r['new_tip']}"
                    for r in moves))
    if not assume_yes and not prompt_yes_no(f"Move these {len(moves)} now?", default=False):
        print("Nothing was changed.")
        return 1
    failed = 0
    for r in moves:
        print(f"== {r['repo'].name}")
        failed += not _move(r)
    print(f"\nMoved {len(moves) - failed}; refused {len(refused)}; failed {failed}. The old "
          "commits stay in each clone's reflog, on no branch; nothing pushes them.")
    return 1 if failed or refused else 0


RELINK_MESSAGE = "Update quoted commit ids after the history rewrite"


def finish(plan_dirs, *, assume_yes: bool = False, fetch: bool = True,
           publish: bool = True) -> int:
    """After the forced pushes: move every plan's checkout onto its new history (`follow`),
    update the commit ids quoted in each with every plan's map (`relink`), then commit exactly
    those files and push them -- an ordinary fast-forward push (`publish=False` stops before
    committing). Nothing else in a checkout is staged or committed."""
    plan_dirs = [Path(path).resolve() for path in plan_dirs]
    repos = [Path(json.loads((path / "expected.json").read_text(encoding="utf-8"))["repository"])
             for path in plan_dirs]
    print("For each checkout: fetch, prove nothing unpushed would be hidden, `git reset --keep`")
    print("onto the rewritten history, update the commit ids quoted in its files"
          + (", then commit those files and push them (an ordinary push):" if publish else ":"))
    print("\n".join(f"  {repo}" for repo in repos))
    if not assume_yes and not prompt_yes_no("Go ahead?", default=False):
        print("Nothing was changed.")
        return 1
    status, moved = 0, []
    for repo in repos:
        print(f"\n== {repo.name}")
        if follow(repo, fetch=fetch, assume_yes=True):
            status = 1
        else:
            moved.append(repo)
    print()
    for repo in moved:
        edited: list[str] = []
        try:
            _lines, total = relink(plan_dirs, repo, write=True, edited=edited)
        except ValueError:
            print(f"{repo.name}: still on the old history -- was its forced push made?")
            status = 1
            continue
        if not total:
            print(f"{repo.name}: no quoted commit ids")
            continue
        if not publish:
            print(f"{repo.name}: {total} quoted commit id(s) updated (not committed)")
            continue
        committed = run_git(repo, ["commit", "-q", "-m", RELINK_MESSAGE, "--", *edited])
        if committed.returncode == 0:
            # `commit -- <paths>` commits exactly those files; anything else stays as it was.
            pushed = run_git(repo, ["push", "-q"], timeout=REWRITE_TIMEOUT_SECONDS)
        if committed.returncode or pushed.returncode:
            print(f"{repo.name}: {total} id(s) updated, but "
                  + ("the commit" if committed.returncode else "the push") + " failed: "
                  + (committed if committed.returncode else pushed).stderr.strip())
            status = 1
            continue
        print(f"{repo.name}: {total} quoted commit id(s) updated, committed and pushed")
    if not publish:
        print("\nNothing was committed. In each checkout: review `git diff`, commit, push.")
    return status


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
        lines.append("Removed from all history (generated files are never edited -- bytecode "
                     f"embeds paths): {', '.join(decided['remove_paths'])}")
    if decided["signed_commits"]:
        lines.append(f"Note: {decided['signed_commits']} signed commit(s). Rewriting removes "
                     "their signatures (a host shows them unverified). Decide before applying.")
    if decided["unreachable"]:
        lines.append("!! Text replacement cannot reach these, so verification will refuse until "
                     "they are removed from history (plan again with --remove-path PATH):")
        lines += [f"  {path}: {why}" for path, why in decided["unreachable"].items()]
    if decided["images_with_location"]:
        lines.append("!! Images whose metadata holds a GPS position: --remove-path each, or "
                     "--keep PATH to accept it (a stripped copy can be committed afterwards):")
        lines += [f"  {path}" for path in decided["images_with_location"]]
    if decided["archives_opened"]:
        lines.append(f"Opened {decided['archives_opened']} archive(s) and scanned every member.")
    if decided["not_inspected"]:
        lines.append(f"Not inspected ({len(decided['not_inspected'])}) -- unpack and scan "
                     "them yourself:")
        lines += [f"  {path}: {why}" for path, why in list(decided["not_inspected"].items())[:10]]
    if decided["binary_paths"]:
        lines.append(f"{decided['binary_paths']} binary path(s) were scanned as raw bytes, "
                     "archives and Office files opened, image metadata read; other encoded formats "
                     "(PDF streams, fonts) can still hide text.")
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
