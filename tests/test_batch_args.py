"""
test_batch_args
===============

Offline tests for the duplicator's non-interactive layer: the CLI parser
(`github_org_duplicator.parse_args`), the scripted-answer queue and activation-noise
filter (`gh_common`), and filter resolution (`batch.ask_filters`).

No network, no GitHub, SYNTHETIC values only.

Run directly (exit 0 = pass, 1 = fail):

    python3 tests/test_batch_args.py
"""

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "github-org-duplicator"
sys.path.insert(0, str(TOOL_DIR))

import gh_common  # noqa: E402
import batch  # noqa: E402
from github_org_duplicator import parse_args  # noqa: E402

FAILS = []


def check(label, cond):
    print(f"{'ok  ' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILS.append(label)


def expect_parse_error(argv):
    """parse_args should exit(2) for a bad flag combination."""
    err = io.StringIO()
    try:
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            parse_args(argv)
    except SystemExit as exc:
        return exc.code == 2
    return False


def expect_ok(argv):
    try:
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            return parse_args(argv)
    except SystemExit:
        return None


# ---- parser: rejected combinations ----
check("--batch + --single rejected", expect_parse_error(["--batch", "--single", "a/b"]))
check("--parallel 0 rejected", expect_parse_error(["--batch", "--parallel", "0"]))
check("--parallel 9 rejected", expect_parse_error(["--batch", "--parallel", "9"]))
check("--yes --batch without --namespaces rejected",
      expect_parse_error(["--batch", "--yes", "--dest", "/tmp/x"]))
check("--yes --batch without --dest rejected",
      expect_parse_error(["--batch", "--yes", "--namespaces", "all"]))
check("--yes --single without --dest rejected",
      expect_parse_error(["--single", "a/b", "--yes"]))
check("--yes with no batch/single flag rejected", expect_parse_error(["--yes"]))

# ---- parser: accepted ----
a = expect_ok(["--batch", "--namespaces", "all", "--dest", "/tmp/x", "--yes"])
check("full batch line parses", a is not None and a.yes and a.namespaces == "all")
check("no flags -> nothing set", (lambda n: not n.batch and n.namespaces is None
                                  and n.dest is None and not n.yes)(expect_ok([])))
b = expect_ok(["--batch", "--no-private", "--forks", "--format", "mirror", "--parallel", "5"])
check("--no-private -> False", b is not None and b.private is False)
check("--forks -> True", b is not None and b.forks is True)
check("--format mirror kept", b is not None and b.format == "mirror")
check("--archived unset -> None", b is not None and b.archived is None)

# ---- scripted answers: queue, echo, fallthrough, strict ----
gh_common.use_scripted_answers(["4", "all", "", "y"], strict=True)
out = io.StringIO()
with redirect_stdout(out):
    got = [gh_common.prompt_input(f"q{i}: ") for i in range(4)]
check("scripted answers served in order", got == ["4", "all", "", "y"])
check("scripted prompt is echoed", "q0: 4" in out.getvalue())
try:
    with redirect_stdout(io.StringIO()):
        gh_common.prompt_input("overflow: ")
    check("strict overflow raises", False)
except SystemExit:
    check("strict overflow raises", True)

gh_common.use_scripted_answers([], strict=False)  # reset

# ---- activation-noise filter ----
gh_common.use_scripted_answers(
    ["source /home/u/.venv/bin/activate", "  & C:\\proj\\.venv\\Scripts\\Activate.ps1  ", "4"],
    strict=True,
)
with redirect_stdout(io.StringIO()):
    kept = gh_common.prompt_input("mode: ")
check("activation lines skipped, real answer kept", kept == "4")
gh_common.use_scripted_answers([], strict=False)


# ---- batch.ask_filters: flag > --yes default > (no prompt when resolvable) ----
class Args:
    def __init__(self, **kw):
        for key in ("private", "archived", "forks", "format", "parallel"):
            setattr(self, key, kw.get(key))


with redirect_stdout(io.StringIO()):
    res = batch.ask_filters(Args(), assume_yes=True)
check("ask_filters --yes defaults", res == (True, False, False, False, 3))

with redirect_stdout(io.StringIO()):
    res = batch.ask_filters(
        Args(private=False, archived=True, forks=True, format="mirror", parallel=2),
        assume_yes=False,
    )
check("ask_filters honors flags without prompting", res == (False, True, True, True, 2))

# ---- single-repo spec handling ----
check("owner/name has an owner", batch._spec_has_owner("alice/dotfiles"))
check("URL has an owner", batch._spec_has_owner("https://github.com/alice/dotfiles"))
check("bare name has no owner", not batch._spec_has_owner("alice"))
check("bare name with spaces still has no owner", not batch._spec_has_owner("  alice  "))

# _resolve_one_repo: bare name that fails should explain the owner assumption (no network:
# monkeypatch the gh call to raise).
def _boom(_spec):
    raise RuntimeError("boom")


def _explode(_spec):
    raise AssertionError("gh must not be called for a rejected spec")


_orig = batch.resolve_repo_details
try:
    batch.resolve_repo_details = _boom
    data, msg = batch._resolve_one_repo("somefriend")
    check("bare-name failure explains the owner assumption",
          data is None and "has no owner" in msg and "somefriend/their-repo" in msg)
    data, msg = batch._resolve_one_repo("alice/nope")
    check("owner/name failure is a plain message",
          data is None and "could not resolve 'alice/nope'" in msg and "has no owner" not in msg)

    batch.resolve_repo_details = _explode  # these must be rejected before any gh call
    data, msg = batch._resolve_one_repo("--upload-pack=evil")
    check("leading-dash spec rejected without calling gh", data is None and "not a repo" in msg)
    data, msg = batch._resolve_one_repo("   ")
    check("empty spec rejected without calling gh", data is None and "no repo" in msg)
finally:
    batch.resolve_repo_details = _orig

# format_size tolerates junk (used on gh diskUsage which can be null)
check("format_size(None)", gh_common.format_size(None) == "size unknown")
check("format_size(-1)", gh_common.format_size(-1) == "size unknown")
check("format_size('nope')", gh_common.format_size("nope") == "size unknown")
check("format_size(2048) still works", gh_common.format_size(2048) == "2.0 MB")

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    sys.exit(1)
print("\nALL-BATCH-ARGS-TESTS-PASS")
