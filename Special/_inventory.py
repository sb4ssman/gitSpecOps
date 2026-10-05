"""The library inventory: everything needed to recreate a set of repositories on another machine.

A folder map says what is *called* what. An inventory says where each repository *came from*
(its remote URLs), where it *lived* (a path relative to a labelled root, never a drive letter),
what it *is* (host/owner/name, branch, head, last commit, readme, project metadata) and what a
clone *cannot* bring back (uncommitted work, unpushed commits, stashes, no remote at all). It is
the content-bearing opposite of the hashed fleet manifests: readable on purpose, carried by the
user, and therefore never written into the repository (`.agents/output/` is the default).

Two halves, both pure of policy a command should own:

- `collect_inventory` observes (git reads only; `GIT_OPTIONAL_LOCKS=0` so even `status` does not
  refresh an index) -- `EFFECT = "none"` for `inventory_export.py`.
- `plan_restore` is a pure planner from an inventory plus a label -> destination mapping to a
  list of rows; `inventory_restore.py` shows it, confirms it, and clones with `Basic/clone.py`.

A recorded URL is the source of truth for cloning. `host/owner/name` is derived from it, for
layout and identity. Credentials are never recorded: userinfo is stripped from http(s) URLs.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from Basic._discovery import classify, find_repos
from Basic._facts import ahead_behind
from Basic._identity import parse_remote_url
from Basic._run import run_git

SCHEMA = "gitspecops.inventory"
SCHEMA_VERSION = 1

OBSERVE_ENV = {"GIT_OPTIONAL_LOCKS": "0"}
STATUS_TIMEOUT_SECONDS = 120

# Files whose own metadata may name where a repository came from.
README_BYTES = 4000
README_EXCERPT_CHARS = 400
MAX_CANDIDATES = 10
_FORGE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "git.sr.ht")
_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::\d+)?/[^\s<>()\[\]\"'`]+")

# Names an unusual remote could smuggle into a *derived* destination: strict. A recorded
# relative path is the user's own layout (spaces and unicode are normal), so it gets the looser
# check below -- but both end in the same resolve() containment test at plan time.
_STRICT_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_BAD_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')
_WINDOWS_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL",
                              *(f"COM{n}" for n in range(1, 10)),
                              *(f"LPT{n}" for n in range(1, 10))})


# --- URLs -------------------------------------------------------------------------------------

def sanitize_url(url: str) -> tuple[str, bool]:
    """(url, credentials_removed). http(s) userinfo is dropped entirely: a token or password
    can sit in either half. ssh:// keeps a bare username (`git`) but never a password; scp-style
    `git@host:path` has no secret slot and passes through untouched."""
    text = url.strip()
    if "://" not in text:
        return text, False
    try:
        parts = urlsplit(text)
    except ValueError:
        return text, False
    if "@" not in parts.netloc:
        return text, False
    userinfo, _, hostport = parts.netloc.rpartition("@")
    if parts.scheme in ("http", "https"):
        return urlunsplit(parts._replace(netloc=hostport)), True
    if ":" in userinfo:
        return urlunsplit(parts._replace(netloc=f"{userinfo.split(':', 1)[0]}@{hostport}")), True
    return text, False


def _clean_candidate(raw: str) -> str:
    text = raw.rstrip(".,;:!?)]}>'\"")
    return text[:-4] if text.endswith(".git") else text


def _identity_fields(url: str | None) -> dict | None:
    parsed = parse_remote_url(url)
    if not parsed:
        return None
    host, owner, name = parsed
    return {"host": host, "owner": owner, "name": name}


# --- observation ------------------------------------------------------------------------------

def _git(path: Path, *args: str, timeout: float | None = None) -> str | None:
    result = run_git(path, args, timeout=timeout, env=OBSERVE_ENV)
    return result.stdout.strip() if result.returncode == 0 else None


def _remotes(path: Path) -> list[dict]:
    raw = _git(path, "config", "--get-regexp", r"^remote\..*\.url$") or ""
    remotes = []
    for line in raw.splitlines():
        key, _, value = line.partition(" ")
        if not value.strip() or not key.startswith("remote.") or not key.endswith(".url"):
            continue
        url, stripped = sanitize_url(value)
        item = {"name": key[len("remote."):-len(".url")], "url": url,
                "identity": _identity_fields(url)}
        if stripped:
            item["credentials_removed"] = True
        remotes.append(item)
    remotes.sort(key=lambda r: (r["name"] != "origin", r["name"]))
    return remotes


def _submodules(path: Path) -> list[dict]:
    raw = _git(path, "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$")
    modules: dict[str, dict] = {}
    for line in (raw or "").splitlines():
        key, _, value = line.partition(" ")
        body = key[len("submodule."):]
        name, _, field = body.rpartition(".")
        if field == "url":
            value = sanitize_url(value)[0]
        modules.setdefault(name, {})[field] = value
    return [modules[name] for name in sorted(modules)]


def _read_text(path: Path, limit: int = README_BYTES) -> str | None:
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return None


def _find_file(folder: Path, prefix: str) -> Path | None:
    try:
        for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.name.lower().startswith(prefix):
                return entry
    except OSError:
        pass
    return None


def _readme(folder: Path) -> dict | None:
    path = _find_file(folder, "readme")
    text = _read_text(path) if path else None
    if not path or not text or not text.strip():
        return None
    lines = [ln.strip() for ln in text.splitlines()]
    nonblank = [ln for ln in lines if ln]
    title = nonblank[0].lstrip("#= ").strip() if nonblank else ""
    body = " ".join(nonblank[1:])
    return {"file": path.name, "title": title[:200], "excerpt": body[:README_EXCERPT_CHARS]}


def _toml(path: Path) -> dict:
    text = _read_text(path, 200_000)
    try:
        return tomllib.loads(text) if text else {}
    except tomllib.TOMLDecodeError:
        return {}


def _project_metadata(folder: Path) -> tuple[dict, list[dict]]:
    """Self-declared identity from common project files: (facts, [candidate url dicts])."""
    facts: dict = {}
    urls: list[tuple[str, str]] = []

    def take(value, source):
        if isinstance(value, str) and value.strip():
            urls.append((value.strip(), source))
        elif isinstance(value, dict):
            for item in value.values():
                take(item, source)

    pyproject = _toml(folder / "pyproject.toml")
    project = pyproject.get("project") or {}
    if project:
        facts["python"] = {k: project[k] for k in ("name", "version", "description") if k in project}
        take(project.get("urls"), "pyproject.toml")
    cargo = (_toml(folder / "Cargo.toml").get("package")) or {}
    if cargo:
        facts["rust"] = {k: cargo[k] for k in ("name", "version", "description") if k in cargo}
        take(cargo.get("repository"), "Cargo.toml")
        take(cargo.get("homepage"), "Cargo.toml")
    package = _read_text(folder / "package.json", 200_000)
    if package:
        try:
            data = json.loads(package)
        except ValueError:
            data = {}
        if isinstance(data, dict):
            facts["node"] = {k: data[k] for k in ("name", "version", "description")
                             if isinstance(data.get(k), str)}
            repository = data.get("repository")
            take(repository.get("url") if isinstance(repository, dict) else repository, "package.json")
            take(data.get("homepage"), "package.json")
    gomod = _read_text(folder / "go.mod", 2000)
    if gomod:
        match = re.match(r"\s*module\s+(\S+)", gomod)
        if match:
            facts["go"] = {"module": match.group(1)}
            urls.append(("https://" + match.group(1), "go.mod"))
    candidates = [{"url": u, "source": s} for u, s in urls]
    return {k: v for k, v in facts.items() if v}, candidates


def _candidate_urls(name: str, declared: list[dict], readme_text: str | None,
                    known: set[str]) -> list[dict]:
    """Where this repository *might* have come from. Never used to clone on its own: a README
    link is a lead, and `inventory_restore.py` only offers it with an explicit flag."""
    found: list[dict] = []
    seen = set(known)

    def add(raw: str, source: str) -> None:
        url, _ = sanitize_url(_clean_candidate(raw))
        identity = _identity_fields(url.rstrip("/"))
        key = (identity and f"{identity['host']}/{identity['owner']}/{identity['name']}".lower()) or url.lower()
        if not identity or key in seen:
            return
        seen.add(key)
        found.append({"url": url, "source": source, "identity": identity,
                      "name_matches_folder": identity["name"].lower() == name.lower()})

    for item in declared:
        add(item["url"], item["source"])
    for match in _URL.finditer(readme_text or ""):
        host = urlsplit(match.group(0)).netloc.lower()
        if host in _FORGE_HOSTS:
            add(match.group(0), "readme")
    found.sort(key=lambda c: (not c["name_matches_folder"], c["source"] == "readme"))
    return found[:MAX_CANDIDATES]


def _status(path: Path) -> dict:
    out = run_git(path, ["status", "--porcelain=v1", "--untracked-files=normal"],
                  timeout=STATUS_TIMEOUT_SECONDS, env=OBSERVE_ENV)
    if out.returncode:
        return {"readable": False}
    lines = [ln for ln in out.stdout.splitlines() if ln]
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    return {"readable": True, "tracked_changes": len(lines) - untracked, "untracked": untracked}


def _gitdir_kind(hit) -> str:
    """worktree | bare | submodule | linked_worktree | gitfile -- from where `.git` points."""
    if hit.kind != "gitfile":
        return hit.kind
    pointer = (hit.gitdir or "").replace("\\", "/")
    if "/worktrees/" in pointer:
        return "linked_worktree"
    if "/modules/" in pointer:
        return "submodule"
    return "gitfile"


def collect_entry(hit, root_label: str, relative: str) -> dict:
    """Everything observable about one repository. Never raises for an unreadable repo."""
    path = Path(hit.path)
    kind = _gitdir_kind(hit)
    entry: dict = {"root": root_label, "path": relative, "name": path.name, "kind": kind}
    bare = hit.kind == "bare"
    remotes = _remotes(path)
    origin = next((r for r in remotes if r["name"] == "origin"), remotes[0] if remotes else None)
    entry["remotes"] = remotes
    entry["origin_url"] = origin["url"] if origin else None
    entry["identity"] = origin["identity"] if origin else None
    entry["canonical_path"] = (
        "/".join(entry["identity"][k] for k in ("host", "owner", "name"))
        if entry["identity"] else None)
    flags: list[str] = []
    if not remotes:
        flags.append("no-remote")
    elif not any(r["name"] == "origin" for r in remotes):
        flags.append("no-origin")
    if any(r.get("credentials_removed") for r in remotes):
        flags.append("credentials-removed")
    if kind in ("submodule", "linked_worktree"):
        flags.append(kind.replace("_", "-"))

    head = _git(path, "rev-parse", "HEAD")
    entry["head"] = head
    if head is None:
        flags.append("no-commits" if _git(path, "rev-parse", "--git-dir") else "git-unreadable")
    entry["branch"] = None if bare else _git(path, "branch", "--show-current")
    if not bare and head and not entry["branch"]:
        flags.append("detached")
    upstream = None if bare else _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    entry["upstream"] = upstream
    default = _git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    entry["default_branch"] = default.split("/", 1)[1] if default and "/" in default else None
    if head:
        entry["root_commits"] = (_git(path, "rev-list", "--max-parents=0", "HEAD") or "").split()[:3]
        last = _git(path, "log", "-1", "--format=%cI%x1f%s") or ""
        date, _, subject = last.partition("\x1f")
        entry["last_commit"] = {"date": date, "subject": subject[:200]}

    counts = ahead_behind(path) if upstream else None
    unpushed = _git(path, "rev-list", "--branches", "--not", "--remotes", "--count")
    entry["unpushed_commits"] = int(unpushed) if unpushed and unpushed.isdigit() else None
    if remotes and (entry["unpushed_commits"] or (counts and counts["ahead"])):
        flags.append("unpushed-commits")
    if counts is not None:
        entry["ahead"], entry["behind"] = counts["ahead"], counts["behind"]

    if not bare:
        status = _status(path)
        entry["status"] = status
        if status.get("tracked_changes") or status.get("untracked"):
            flags.append("uncommitted-work")
        stashes = _git(path, "stash", "list")
        entry["stashes"] = len(stashes.splitlines()) if stashes else 0
        if entry["stashes"]:
            flags.append("stashed")
        if (path / ".gitattributes").is_file() and "filter=lfs" in (_read_text(path / ".gitattributes") or ""):
            flags.append("lfs")
        submodules = _submodules(path) if (path / ".gitmodules").is_file() else []
        if submodules:
            entry["submodules"] = submodules
            flags.append("has-submodules")

    meta: dict = {}
    description = _read_text(Path(hit.gitdir) / "description", 400) if hit.gitdir and kind in ("worktree", "bare") else None
    if description and description.strip() and not description.startswith("Unnamed repository"):
        meta["git_description"] = description.strip()
    readme_text = None
    if not bare:
        readme = _readme(path)
        if readme:
            meta["readme"] = readme
            readme_text = _read_text(_find_file(path, "readme"))
        facts, declared = _project_metadata(path)
        meta.update(facts)
    else:
        declared = []
    known = {f"{r['identity']['host']}/{r['identity']['owner']}/{r['identity']['name']}".lower()
             for r in remotes if r["identity"]}
    candidates = _candidate_urls(path.name, declared, readme_text, known)
    if candidates:
        meta["candidate_urls"] = candidates
        if not remotes:
            flags.append("has-origin-candidates")
    if meta:
        entry["metadata"] = meta
    entry["flags"] = flags
    return entry


LOOSE = "loose"  # reserved label: single repositories that sit in no common root
_LABEL = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


def build_roots(specs: list[str]) -> list[tuple[str, Path]]:
    """`label=path` or a bare path, into unique (label, path) pairs.

    A bare path is labelled by its own folder name; two folders called `projects` on different
    drives become `projects` and `projects-2`, so a haphazard library never has to be named by
    hand. An explicit label that is invalid, reserved or repeated is an error (the person chose
    it, so guessing a different one would be wrong). The same folder given twice counts once.
    """
    parsed: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()
    for spec in specs:
        label, sep, raw = spec.partition("=")
        if not sep:  # a Windows drive letter has no '=', so a bare path never splits wrongly
            raw, label = spec, ""
        path = Path(raw).expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen_paths:
            continue
        seen_paths.add(key)
        parsed.append((label.strip().lower(), path))
    explicit = [label for label, _ in parsed if label]
    for label in explicit:
        if not _LABEL.fullmatch(label) or label == LOOSE:
            raise ValueError(f"root label {label!r} must be lowercase letters, digits, '.', '_' or '-'"
                             f" (and not {LOOSE!r}, which is reserved)")
    if len(set(explicit)) != len(explicit):
        raise ValueError(f"duplicate root labels: {sorted(explicit)}")
    taken = set(explicit) | {LOOSE}
    roots = []
    for label, path in parsed:
        if not label:
            base = re.sub(r"[^a-z0-9._-]+", "-", path.name.lower()).strip("-.") or "root"
            label, n = base, 2
            while label in taken:
                label, n = f"{base}-{n}", n + 1
            taken.add(label)
        roots.append((label, path))
    return roots


def collect_inventory(roots: list[tuple[str, Path]], *, loose: list[Path] | None = None,
                      max_depth: int | None = None, include_hidden: bool = False,
                      progress=None) -> dict:
    """Record every repository under `roots` plus each single repository in `loose`.

    A repository reachable more than one way (a loose path that is also inside a root, two
    overlapping roots) is recorded once, under the first root that reaches it, because the root
    carries the layout. A root that is itself a repository is recorded as a loose one.
    """
    labels = [label for label, _ in roots]
    if len(set(labels)) != len(labels) or LOOSE in labels:
        raise ValueError(f"duplicate or reserved root labels: {sorted(labels)}")
    entries: list[dict] = []
    seen: set[str] = set()

    def fresh(hit) -> bool:
        key = os.path.normcase(str(Path(hit.path).resolve()))
        if key in seen:
            return False
        seen.add(key)
        return True

    loose_paths = [Path(p).expanduser().resolve() for p in (loose or [])]
    for label, root in roots:
        for hit in find_repos(root, max_depth=max_depth, include_hidden=include_hidden):
            if fresh(hit):
                if progress:
                    progress(label, hit.path)
                relative = PurePosixPath(*Path(hit.path).relative_to(root).parts).as_posix()
                entries.append(collect_entry(hit, label, relative))
        if classify(root):
            loose_paths.append(root)
    used: set[str] = set()
    for path in loose_paths:
        hit = classify(path)
        if hit is None:
            raise ValueError(f"not a git repository: {path}")
        if not fresh(hit):
            continue
        base = re.sub(r'[<>:"|?*\\/\x00-\x1f]+', "-", path.name).strip(". ") or "repo"
        name, n = base, 2
        while name.casefold() in used:
            name, n = f"{base}-{n}", n + 1
        used.add(name.casefold())
        if progress:
            progress(LOOSE, hit.path)
        entry = collect_entry(hit, LOOSE, name)
        entry["source_path"] = str(path)  # where it lived; for the human, never read by restore
        entries.append(entry)
    # Nesting is recorded so restore can order parents first and explain a collision.
    by_key = {(e["root"], e["path"]): e for e in entries}
    for entry in entries:
        parts = entry["path"].split("/")
        for depth in range(len(parts) - 1, 0, -1):
            parent = by_key.get((entry["root"], "/".join(parts[:depth])))
            if parent:
                entry["nested_in"] = parent["path"]
                break
    recorded = [{"label": label, "source_path": str(root)} for label, root in roots]
    if any(e["root"] == LOOSE for e in entries):
        recorded.append({"label": LOOSE, "source_path": None})
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": sys.platform,
        "roots": recorded,
        "repositories": entries,
    }


def validate_inventory(data: object) -> list[dict]:
    """The repository list, or ValueError saying why this is not an inventory we can read."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("not a gitSpecOps inventory file")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported inventory schema_version {data.get('schema_version')!r}"
                         f" (this tool reads {SCHEMA_VERSION}); re-export on a matching version")
    repos = data.get("repositories")
    if not isinstance(repos, list) or not all(isinstance(r, dict) for r in repos):
        raise ValueError("inventory has no repository list")
    return repos


# --- restore planning (pure) ------------------------------------------------------------------

def _safe_relative(path: object, *, strict: bool) -> tuple[str, ...] | None:
    if not isinstance(path, str) or not path:
        return None
    parts = tuple(path.split("/"))
    for part in parts:
        if part in ("", ".", "..") or part != part.rstrip(". ") or _BAD_CHARS.search(part):
            return None
        if strict and not _STRICT_COMPONENT.fullmatch(part):
            return None
        if part.split(".")[0].upper() in _WINDOWS_DEVICES:
            return None
    return parts


def _contained(library: Path, target: Path) -> bool:
    try:
        return target.resolve().is_relative_to(library.resolve())
    except OSError:
        return False


def plan_restore(inventory_repos: list[dict], destinations: dict[str, Path], *,
                 layout: str = "preserve", use_candidates: bool = False,
                 selected_roots: set[str] | None = None) -> list[dict]:
    """One row per repository: action in clone | exists | skip | needs_review, with a reason.

    layout `preserve` recreates each recorded relative path under its root's destination;
    `canonical` puts a repository with a known identity at <dest>/<host>/<owner>/<name>
    (anything without one keeps its recorded path). The URL cloned is always a recorded
    remote; `use_candidates` additionally allows a README/metadata lead when there is none.
    """
    rows: list[dict] = []
    claimed: dict[str, str] = {}
    ordered = sorted(inventory_repos, key=lambda r: (r.get("path", "").count("/"), r.get("root", ""), r.get("path", "")))
    for repo in ordered:
        label = repo.get("root")
        row = {"root": label, "path": repo.get("path"), "name": repo.get("name") or repo.get("path"),
               "flags": list(repo.get("flags") or [])}
        if selected_roots is not None and label not in selected_roots:
            continue
        dest = destinations.get(label)
        if dest is None:
            rows.append({**row, "action": "needs_review", "detail": f"no destination mapped for root {label!r}"})
            continue
        kind = repo.get("kind")
        if kind in ("submodule", "linked_worktree"):
            rows.append({**row, "action": "skip", "detail":
                         "a submodule comes with its parent" if kind == "submodule"
                         else "a linked worktree belongs to its main repository"})
            continue
        url, source = repo.get("origin_url"), "origin"
        if not url and repo.get("remotes"):
            url, source = repo["remotes"][0]["url"], repo["remotes"][0]["name"]
        if not url and use_candidates:
            candidates = (repo.get("metadata") or {}).get("candidate_urls") or []
            if candidates:
                url, source = candidates[0]["url"], f"candidate:{candidates[0]['source']}"
        if not url:
            lead = bool((repo.get("metadata") or {}).get("candidate_urls"))
            rows.append({**row, "action": "needs_review", "detail":
                         "no remote recorded; " + ("origin candidates were found in its files (--use-candidates)"
                                                   if lead else "this repository exists only on the source machine")})
            continue
        canonical = repo.get("canonical_path") if layout == "canonical" else None
        relative = _safe_relative(canonical, strict=True) if canonical else _safe_relative(repo.get("path"), strict=False)
        if relative is None:
            rows.append({**row, "action": "needs_review", "detail": "recorded path is not a safe destination"})
            continue
        target = dest.joinpath(*relative)
        if not _contained(dest, target):
            rows.append({**row, "action": "needs_review", "detail": "destination would escape the library"})
            continue
        key = str(target).casefold()
        if key in claimed:
            rows.append({**row, "action": "needs_review", "target": target,
                         "detail": f"same destination as {claimed[key]} (case-insensitive match)"})
            continue
        claimed[key] = str(repo.get("path"))
        row.update(target=target, url=url, url_source=source,
                   branch=repo.get("branch") or repo.get("default_branch"))
        if target.exists():
            rows.append({**row, "action": "exists", "detail": "already present; never replaced"})
            continue
        notes = [n for n, f in (("uncommitted work on the source is not in the remote", "uncommitted-work"),
                                ("unpushed commits on the source are not in the remote", "unpushed-commits"),
                                ("stashes are not in the remote", "stashed"),
                                ("has submodules (cloned without them)", "has-submodules"),
                                ("uses LFS; git-lfs must be installed", "lfs"))
                 if f in row["flags"]]
        rows.append({**row, "action": "clone", "detail": "; ".join(["clone from " + source, *notes])})
    return rows
