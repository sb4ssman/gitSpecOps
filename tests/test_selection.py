"""
test_selection
==============

Self-contained tests for the duplicator's selection grammar (`gh_common.parse_selection`)
and the interactive namespace chooser (`batch.choose_orgs`). No network, no filesystem
writes, and SYNTHETIC names only (org-a/org-b/..., alpha-repo/...) — never real repos.

Run directly (exit 0 = pass, 1 = fail):

    python3 tests/test_selection.py
"""

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "github-org-duplicator"
sys.path.insert(0, str(TOOL_DIR))

import batch  # noqa: E402
from gh_common import parse_selection  # noqa: E402

FAILS = []

# ---- parse_selection: pure parser (items are plain names; key = lowercase) ----
ITEMS = ["alpha-repo", "beta-repo", "gamma-repo", "delta-repo"]
CASES = [
    ("", ITEMS),                                    # empty = all
    ("1-3", ITEMS[:3]),                             # print-style range
    ("2-4, 1", ITEMS),                              # range + single, display order
    ("3-2", ITEMS[1:3]),                            # reversed range normalizes
    ("all except 2", ["alpha-repo", "gamma-repo", "delta-repo"]),
    ("!2", ["alpha-repo", "gamma-repo", "delta-repo"]),
    ("alpha-repo, delta-repo", ["alpha-repo", "delta-repo"]),   # by name
    ("ALPHA-REPO", ["alpha-repo"]),                 # case-insensitive
    ("all,!1,!4", ["beta-repo", "gamma-repo"]),
    ("1 except 1", []),                             # excluded everything
    ("1,1", ["alpha-repo"]),                        # duplicates collapse
    ("a", ITEMS),                                   # 'a' = all shorthand
    ("zzz", None),                                  # bad token -> rejected line
    ("9", None),                                    # out of range
    ("1-99", None),                                 # out of range range
    ("all except zzz", None),                       # bad token inside except tail
]
for raw, want in CASES:
    got, bad = parse_selection(raw, ITEMS)
    if want is None:
        ok = bool(bad)
    else:
        ok = (got == want and not bad)
    if not ok:
        FAILS.append(f"parse_selection({raw!r}) -> {got}, bad={bad}")

# ---- choose_orgs regression (prompt monkeypatched; scripted answers) ----
ORGS = [{"login": f"org-{c}", "role": "admin", "state": "active"} for c in "abcd"]
ROUNDS = [
    ("2-4", ["org-b", "org-c", "org-d"]),                    # range on namespaces
    ("all except org-a", ["org-b", "org-c", "org-d"]),
    ("org-d, 1", ["org-a", "org-d"]),                        # name + number
    ("bogus", None),                                         # re-prompt path...
    ("1-2", ["org-a", "org-b"]),                             # ...then valid
]
answers = iter(raw for raw, _ in ROUNDS)
got_all = []
for _ in range(4):  # last round consumes two answers (re-prompt)
    batch.prompt_input = lambda *a, **k: next(answers)
    got_all.append([o["login"] for o in batch.choose_orgs(ORGS)])
WANT = [want for _, want in ROUNDS if want is not None]
if got_all != WANT:
    FAILS.append(f"choose_orgs: {got_all}")

# ---- module wiring ----
import github_org_duplicator as dup  # noqa: E402,F401

for obj, name in ((batch, "run_batch_download"), (batch, "run_single_repo"),
                  (dup, "choose_repo_subset")):
    if not hasattr(obj, name):
        FAILS.append(f"missing: {obj.__name__}.{name}")

repos = [{"name": "alpha-repo"}, {"name": "beta-repo"}, {"name": "gamma-repo"}]
pending = batch.pending_repos(repos, {"ALPHA-REPO"}, {"Beta-Repo"})
if pending != [{"name": "gamma-repo"}]:
    FAILS.append(f"case-insensitive pending repos: {pending}")

if FAILS:
    print("SELECTION-TESTS FAILED:")
    for f in FAILS:
        print(" -", f)
    sys.exit(1)
print("ALL-SELECTION-TESTS-PASS "
      f"({len(CASES)} parser cases, {len(WANT)} chooser rounds)")
