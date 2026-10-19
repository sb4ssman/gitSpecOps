"""Security and sanitization guard for a PUBLIC repository.

Every finding below is one this repository actually shipped, or came within one `git commit` of
shipping, on 2026-09-11:

- a generated launcher holding an absolute personal path was **staged**, because `.gitignore`
  covered the renamed tool folder but not the old-cased one;
- `archive_diff.py`'s self-test carried a real organization and real repository names, against
  the project's own written rule that fixtures never do;
- agent notes recorded live Tailscale addresses, machine names and archive paths.

Review caught those once. A test catches them every time, which is the difference between a
policy and a guarantee. It scans **tracked files only** — what the public can actually read —
and deliberately says nothing about git history, which no test can retroactively clean.

Offline: `git ls-files` plus local reads. No network.
"""
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

# --------------------------------------------------------------------------- what must never ship

SECRETS = {
    "a 64-hex value (the fleet-secret shape)": re.compile(r"\b[0-9a-f]{64}\b"),
    "a GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "an assigned credential": re.compile(
        r"(?i)\b(password|passwd|secret|api_?key|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
}

PERSONAL = {
    # The account segment must look like a name, so the documented shape `C:\Users\…` is not one.
    "a Windows user path": re.compile(r"(?i)[A-Z]:\\Users\\[\w.$-]{2,}"),
    "a Windows drive path": re.compile(r"(?i)\b[D-Z]:\\(?:Github|Users|Projects)\b"),
    "a POSIX home path": re.compile(r"/home/(?!u/|someone/)[a-z0-9._-]{2,}"),
    "a real Tailscale address": re.compile(
        r"\b100\.(?:6[5-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
}

#: Values that look like findings but are documentation or invented data. Every entry is an
#: explicit decision, not a convenience, and it is tested against **the matched text only**.
#: Until 2026-10-19 it was also tested against the whole line, so anything allowed anywhere on a
#: line -- including any HTML tag, via the placeholder entry -- excused a real path, address or
#: token beside it. Entries that only ever mattered at line level were dropped with that change.
ALLOWED = re.compile(
    r"""(?ix)
    example\.(com|test|org)     # reserved documentation domains
  | <[a-z-]+>                   # an intentional placeholder
    """)

#: Names that are the project's own public identity: the owner of these public repositories,
#: and the authorship files. Anywhere else, the owner's login is a disclosure (a private
#: repository name, an account in a fixture).
PUBLIC_REPOSITORIES = ("gitSpecOps", "PythonTools")
AUTHORSHIP_FILES = {"NOTICE", "pyproject.toml", "LICENSE"}

#: Identity values too generic to scan for without drowning in noise.
GENERIC_IDENTITIES = {"user", "admin", "root", "home", "test", "runner", "localhost", "owner"}

#: Files whose job is to describe these patterns. Excluding them is safe precisely because a
#: real leak would also have to appear somewhere else to matter.
SELF = {"tests/repo/test_repo_hygiene.py"}


def tracked_files():
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                          check=False, timeout=120)
    if proc.returncode:
        return None
    return [name for name in proc.stdout.split("\n") if name.strip()]


def scan(names, patterns, label, root=None, show=True):
    """Every match of every pattern in the named files, unless the *match itself* is allowed.

    Whole files are scanned (an earlier version stopped at column 500, so anything late in a
    long line -- minified JS, one-line JSON -- was never looked at). `show=False` reports where
    and what kind, never the value, for patterns built from the person's own identity.
    """
    root = ROOT if root is None else root
    findings = []
    for name in names:
        if name in SELF:
            continue
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for description, pattern in patterns.items():
            for match in pattern.finditer(text):
                if ALLOWED.search(match.group(0)):
                    continue
                number = text.count("\n", 0, match.start()) + 1
                findings.append(f"{name}:{number} contains {description}"
                                + (f": {match.group(0)!r}" if show else ""))
    return findings


def owner_identity():
    """The identity of the person running this, read now and held only in memory.

    No test can know a real name in advance, so a real account once sat in a fixture
    unnoticed. These are the values most likely to leak: the git identity, the `gh` login (read
    from gh's own config, offline), the host name and the home folder's name. Unavailable or
    generic values are skipped. Nothing here is written anywhere or printed.
    """
    def output(argv):
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    found = {
        "your git email": output(["git", "config", "user.email"]),
        "your git name": output(["git", "config", "user.name"]),
        "your gh login": output(["gh", "config", "get", "user", "-h", "github.com"]),
        "this machine's host name": socket.gethostname(),
        "your home folder's name": Path.home().name,
    }
    return {kind: value for kind, value in found.items()
            if len(value) >= 4 and value.lower() not in GENERIC_IDENTITIES}


def identity_patterns(identity):
    """One case-insensitive pattern per identity value, excusing only the public repositories."""
    public = "|".join(re.escape(name) for name in PUBLIC_REPOSITORIES)
    return {kind: re.compile(rf"(?i)(?<![\w.-]){re.escape(value)}(?![\w-])(?!/(?:{public})(?![\w-]))")
            for kind, value in identity.items()}


def test_no_secrets_in_tracked_files(names):
    found = scan(names, SECRETS, "secret")
    if found:
        raise AssertionError("secrets must never be committed:\n  " + "\n  ".join(found))


def test_no_personal_data_in_tracked_files(names):
    """Local paths, machine names and real addresses do not belong in a public repository."""
    found = scan(names, PERSONAL, "personal")
    if found:
        raise AssertionError(
            "personal information must not be committed (use a placeholder such as "
            "<library-root> or machine-a):\n  " + "\n  ".join(found))


def test_no_owner_identity_in_tracked_files(names):
    """The person's own login, email, host or folder name, outside the project's public identity."""
    patterns = identity_patterns(owner_identity())
    found = scan([n for n in names if n not in AUTHORSHIP_FILES], patterns, "identity", show=False)
    if found:
        raise AssertionError(
            "your own identity appears in a tracked file (values withheld here; use an invented "
            "name such as example/work):\n  " + "\n  ".join(found))


def test_the_guard_itself_catches_what_it_claims(_names):
    """The scanner, run on invented files: a finding beside an allowed value is still a finding.

    Pins the 2026-10-19 loophole. Every value below is invented, in a temporary folder.
    """
    cases = {
        "alone.txt": ("library at C:\\Users\\inventedperson\\code", True),
        "html.txt": ("<div>library at C:\\Users\\inventedperson\\code</div>", True),
        "placeholder.txt": ("use <library-root>, not C:\\Users\\inventedperson\\code", True),
        "domain.txt": ("see example.com; peer at <tailnet-ip>", True),
        "token.txt": ("token = 'ghp_" + "A" * 30 + "'  # example.com", True),
        "late.txt": ("x" * 600 + " ghp_" + "B" * 30, True),
        "documented-shape.txt": ("never commit C:\\Users\\… or /home/<you>", False),
        "reserved-domain.txt": ("password = 'example.test'", False),
    }
    identity = {"an invented login": "inventedlogin"}
    owner_cases = {
        "fixture.py": ("RepoTransport('inventedlogin/private-state')", True),
        "readme.md": ("git clone https://github.com/inventedlogin/gitSpecOps.git", False),
        "lookalike.py": ("RepoTransport('inventedlogin/gitSpecOps-state')", True),
        "other.md": ("the inventedloginx project", False),
    }
    with tempfile.TemporaryDirectory(prefix="hygiene-self-test-") as tmp:
        root = Path(tmp)
        for name, (line, _) in {**cases, **owner_cases}.items():
            (root / name).write_text(line + "\n", encoding="utf-8")
        wrong = []
        for name, (_, flagged) in cases.items():
            hits = scan([name], {**SECRETS, **PERSONAL}, "self-test", root=root)
            if bool(hits) != flagged:
                wrong.append(f"{name}: expected {'a finding' if flagged else 'none'}, got {hits}")
        for name, (_, flagged) in owner_cases.items():
            hits = scan([name], identity_patterns(identity), "self-test", root=root, show=False)
            if bool(hits) != flagged:
                wrong.append(f"{name}: expected {'a finding' if flagged else 'none'}, got {hits}")
    if wrong:
        raise AssertionError("the hygiene scanner misjudged invented cases:\n  "
                             + "\n  ".join(wrong))


def test_generated_local_artifacts_are_not_tracked(names):
    """A generated launcher bakes in absolute local paths; one was staged for commit once."""
    offenders = [n for n in names
                 if re.search(r"(refresh[-_]managed[-_]archives|update_archive)\.(bat|ps1|sh)$", n)
                 or n.endswith("managed_archives.json")
                 or "/runs/" in n
                 or n.startswith(".agents/output/") and not n.endswith("README.md")]
    if offenders:
        raise AssertionError("generated local state must stay untracked:\n  "
                             + "\n  ".join(offenders))


def test_license_is_present_and_declared(names):
    """A public repo with no LICENSE grants nobody any rights; this one shipped without one."""
    if "LICENSE" not in names:
        raise AssertionError("LICENSE is missing from the repository")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if "license" not in pyproject:
        raise AssertionError("pyproject.toml declares no license")
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in text:
        raise AssertionError("LICENSE does not contain the declared Apache License text")


def test_agent_workspace_stays_local(names):
    """`.agents/tools` and `.agents/output` hold machine-specific detail; only READMEs ship."""
    leaked = [n for n in names
              if (n.startswith(".agents/tools/") or n.startswith(".agents/output/"))
              and not n.endswith("README.md")]
    if leaked:
        raise AssertionError("only READMEs may be tracked under .agents/tools and "
                             ".agents/output:\n  " + "\n  ".join(leaked))


def main():
    names = tracked_files()
    if names is None:
        # A source tarball or an exported copy is not a git checkout; there is nothing to audit.
        print("SKIP-REPO-HYGIENE-TESTS (not a git checkout)")
        return 0
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = []
    for test in tests:
        try:
            test(names)
        except AssertionError as exc:
            failures.append(str(exc))
    if failures:
        print("REPO-HYGIENE-TESTS FAILED:")
        for failure in failures:
            print(f"\n- {failure}")
        return 1
    print(f"ALL-REPO-HYGIENE-TESTS-PASS ({len(tests)} checks over {len(names)} tracked files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
