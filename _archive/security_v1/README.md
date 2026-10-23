# Security suite, v1 -- preserved

The history-cleanup suite that cleaned this repository and the Sb4ssport-Alpha repositories
(2026-10-19) and another public repository (2026-10-22), with AI assistance each time. Preserved
here at the user's request, **frozen and runnable**: it carries its own copies of exactly the
`Basic/` and `_os/` files it imports, so it keeps working however the live layers change.

Run it from the gitSpecOps checkout, as before -- only the folder is new:

```
python _archive/security_v1/Security/scan_history.py <repo> [--online]
python _archive/security_v1/Security/scan_tree.py <repo>
python _archive/security_v1/Security/scan_folder.py <folder> [--online] [--plan]
python _archive/security_v1/Security/scan_secrets.py <repo>
python _archive/security_v1/Security/rewrite_history.py plan|apply|verify|finish|follow|relink ...
```

Reports and plans still land in this checkout's git-ignored `.agents/output/security/`, and the
never-publish list is still read from `<per-user gitSpecOps folder>/security/never_publish.txt`.

Its own test: `python _archive/security_v1/tests/test_security.py` (disposable repositories
only; not part of `tests/run_all.py`).

**What changed from the live copy, and nothing else:** `_repo.TOOL_ROOT` points three folders
up, so output lands where it always did; the commands it prints name this folder; the test
imports this folder first and drops one block that tested the live Sync Suggester observer.

**Rules:** do not edit it (fixes and new features go into the rebuild,
`.agents/knowledge/security-design.md`); do not import it from live code. The live
`Security/` folder is retired at the rebuild's cut-over; this archive stays.
