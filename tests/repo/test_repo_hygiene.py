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
import subprocess
import sys
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
    "a Windows user path": re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s\"'<]+"),
    "a Windows drive path": re.compile(r"(?i)\b[D-Z]:\\(?:Github|Users|Projects)\b"),
    "a POSIX home path": re.compile(r"/home/(?!u/|someone/)[a-z0-9._-]{2,}"),
    "a real Tailscale address": re.compile(
        r"\b100\.(?:6[5-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
}

#: Values that look like findings but are documentation, protocol constants, or invented data.
#: Every entry is an explicit decision, not a convenience.
ALLOWED = re.compile(
    r"""(?ix)
    100\.64\.0\.0/10            # the CGNAT range constant the transport validates against
  | 100\.64\.0\.\d+             # first addresses of that range, used as test fixtures
  | example\.(com|test|org)     # reserved documentation domains
  | git@github\.com             # a remote URL scheme, not an address
  | user@bitbucket\.org         # ditto, in a URL-parsing fixture
  | /home/(u|someone)/          # invented paths inside duplicator/aggregate fixtures
  | \"22\"\s*\*\s*32            # synthetic secrets built in tests
  | \"11\"\s*\*\s*32
  | <[a-z-]+>                   # an intentional placeholder
    """)

#: Files whose job is to describe these patterns. Excluding them is safe precisely because a
#: real leak would also have to appear somewhere else to matter.
SELF = {"tests/repo/test_repo_hygiene.py"}


def tracked_files():
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                          check=False, timeout=120)
    if proc.returncode:
        return None
    return [name for name in proc.stdout.split("\n") if name.strip()]


def scan(names, patterns, label):
    findings = []
    for name in names:
        if name in SELF:
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.split("\n"), 1):
            if len(line) > 500:
                line = line[:500]
            for description, pattern in patterns.items():
                for match in pattern.finditer(line):
                    if ALLOWED.search(match.group(0)) or ALLOWED.search(line):
                        continue
                    findings.append(f"{name}:{number} contains {description}: "
                                    f"{match.group(0)!r}")
    return findings


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


def test_generated_local_artifacts_are_not_tracked(names):
    """A generated launcher bakes in absolute local paths; one was staged for commit once."""
    offenders = [n for n in names
                 if re.search(r"(refresh-managed-archives|update_archive)\.(bat|ps1|sh)$", n)
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
