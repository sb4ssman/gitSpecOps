"""Scan a repository's whole history for secrets with gitleaks, if it is installed. Read-only.

    python _archive/security_v1/Security/scan_secrets.py [REPO] [--unredacted]

`scan_tree` and `scan_history` look for *you* -- your names, addresses, machines -- plus a few
secret shapes. gitleaks is a dedicated secret scanner: hundreds of rules for specific
providers' keys and tokens, plus entropy checks, across every commit. The two complement
each other; neither is a security clearance on its own.

gitleaks is optional, like the tray app: an external program gitSpecOps calls when it is
there (as it calls `git` and `gh`), never installs by itself, and never requires. Install it
with `winget install Gitleaks.Gitleaks` (Windows), `brew install gitleaks` (macOS), or your
package manager / the release binary from https://github.com/gitleaks/gitleaks (Linux).

Findings are written, redacted unless `--unredacted`, as gitleaks' JSON report into the
git-ignored output folder (see `_repo.output_dir`); a summary is printed. A real secret must be
**revoked and rotated** -- removing it from history does not un-publish it. Exit status 1 when
anything is found, 2 when gitleaks is not installed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import run  # noqa: E402
from Security._repo import output_dir  # noqa: E402

EFFECT = "none"
TIMEOUT_SECONDS = 3600
INSTALL_HINT = ("gitleaks is not installed (it is optional). Install it with "
                "`winget install Gitleaks.Gitleaks` on Windows, `brew install gitleaks` on macOS, "
                "or your package manager / the release binary from "
                "https://github.com/gitleaks/gitleaks on Linux, then run this again.")


def find_gitleaks() -> str | None:
    return shutil.which("gitleaks")


def summarize(findings: list[dict]) -> list[str]:
    """Readable lines from gitleaks' JSON findings. Pure."""
    if not findings:
        return ["gitleaks found nothing."]
    rules = Counter(item.get("RuleID", "?") for item in findings)
    commits = {item.get("Commit") for item in findings if item.get("Commit")}
    files = sorted({item.get("File", "?") for item in findings})
    lines = [f"gitleaks found {len(findings)} candidate secret(s) in {len(commits)} commit(s), "
             f"{len(files)} file(s):"]
    lines += [f"  {rule}: {count}" for rule, count in rules.most_common()]
    lines.append("  files: " + ", ".join(files[:10]) + (" ..." if len(files) > 10 else ""))
    lines.append("Classify each: a real credential must be revoked and rotated first; removing it "
                 "from history does not un-publish it.")
    return lines


def scan(repo: Path, binary: str, report: Path, redact: bool = True):
    """Run gitleaks over every commit. Returns (exit code, findings or None, stderr)."""
    report.parent.mkdir(parents=True, exist_ok=True)
    common = ["--report-format", "json", "--report-path", str(report), "--no-banner",
              "--exit-code", "1", *(["--redact"] if redact else [])]
    result = run([binary, "git", str(repo), *common], timeout=TIMEOUT_SECONDS)
    if result.returncode not in (0, 1) and "unknown command" in (result.stderr or "").lower():
        # gitleaks before 8.19 spelled it `detect --source`.
        result = run([binary, "detect", "--source", str(repo), *common], timeout=TIMEOUT_SECONDS)
    if result.returncode not in (0, 1):
        return result.returncode, None, (result.stderr or result.stdout).strip()
    try:
        findings = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else []
    except ValueError:
        findings = None
    return result.returncode, findings, ""


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Scan history for secrets with gitleaks.")
    parser.add_argument("repo", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--unredacted", action="store_true",
                        help="keep secret values in the (git-ignored) report")
    args = parser.parse_args(argv)
    binary = find_gitleaks()
    if not binary:
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    report = output_dir(repo) / f"gitleaks-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    code, findings, error = scan(repo, binary, report, redact=not args.unredacted)
    if findings is None:
        print(f"gitleaks did not finish: {error or 'unreadable report'}", file=sys.stderr)
        return 2
    print("\n".join(summarize(findings)))
    if findings:
        print(f"\nReport ({'unredacted' if args.unredacted else 'redacted'}, git-ignored): {report}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
