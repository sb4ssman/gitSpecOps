# Protect: scans, secure-commit, secure-push, reviews, history cleanup

Publishing a repository publishes its whole history, not just today's files. gitSpecOps checks
before anything leaves:

- **Scans** of the working files, the staged bytes, or the full history, with built-in checks
  and, if you have them, Gitleaks, Betterleaks (version 1) or TruffleHog.
- **`secure-commit` and `secure-push`.** A commit carries exactly the files you named; a push
  sends exactly the planned commits. Both are held by a secret, a value on your never-publish
  list, or an unreviewed binary. (Basic `commit` and `push` do the same Git work without the
  checks, as `git` itself would.)
- **Reviews.** Accept one finding at one exact place, once; it is not a blanket exception.
- **History cleanup.** Rewrite history into a new private copy, prove what changed, rescan, and
  only then publish; afterwards your clones follow the new history, and the commit ids quoted in
  your files are updated.

## Security in detail

Scans use your saved security policy and print masked results without writing reports or logs
(a screen at a terminal, one JSON record otherwise):

```sh
gitso scan /path/to/repo
gitso history scan /path/to/repo
```

- **Engines.** Built-in checks need no extra packages. Choose optional engines with repeatable
  `--engine gitleaks`, `--engine betterleaks` or `--engine trufflehog`; `--engine none` overrides
  the saved choice. A selected engine that is missing or unsupported makes the scan
  *incomplete*, never a pass. Nothing is installed automatically.
- **Protected values.** Saved never-publish values always apply; `--never-publish` files add to
  them, `--safe-file` and `--safe` add allowances, and conflicting values are an error.
  `security.repository_exceptions` lets one repository contain named protected values on purpose
  (a personal site that names a project); every other repository still blocks them.
- **Reports.** `--out` writes a full private JSON report, only where you say: outside Git, storage
  you control; inside Git, an ignored and untracked path. Existing files and links are refused.

**Reviews.** For a documented example or a test fixture, review that exact finding:

```sh
gitso scan /path/to/repo --out /private/reports/scan.json
gitso review /private/reports/scan.json finding-000001 --reason "Reviewed example"
```

The plan writes nothing; at a terminal you are asked, and a script reruns it with
`--apply <plan id>`. Changed bytes, location or
repository need review again. Protected values, strong credentials, unsupported engine findings
and coverage gaps cannot be waived. A binary file (a font, an executable) is a "binary content"
finding: its readable strings are checked, and a review accepts that exact file at that place.
PDFs and 7z/RAR archives remain coverage gaps. Revoke with `--revoke <review id>`. Reviews stay
on this machine.

**Staged bytes.** If Git's line-ending conversion or a clean filter changes a reviewed file when
staged, `scan --staged --out FILE` inspects exactly what would be committed. It never stages
or commits anything.

**`secure-commit`.** Check the files, message and author, then apply that exact plan (at a
terminal you are asked; a script uses the plan id):

```sh
gitso secure-commit /path/to/repo file.py docs/usage.md -m 'Describe the change'
gitso secure-commit /path/to/repo file.py docs/usage.md -m 'Describe the change' --apply '<plan-id>'
```

Only the named files are committed, with their whole working contents; other staged work is
kept. Existing hooks run in their usual order through a temporary relay; no hooks or Git
settings are installed. Requires Git 2.36 or later. Directories, linked files, merge or rebase
states need compatibility work. If Git created a commit but final verification fails, the result
says `partial`; nothing is pushed or undone automatically.

**`secure-push`.** `gitso secure-push /path/to/repo` plans the branch, tip and destination
without network access; approving it (or `--apply '<plan-id>'`) fetches, checks the actual outgoing
history through the same gate as archive publishing, then pushes that fixed snapshot. There is
no force, extra-tag or bypass option.

**Status with security.** `gitso fleet publish check --root /path/to/library --local-only
--no-publish --no-catalog` reports Git status together with local findings. Only the
status manifest is ever shared; findings stay on this machine. The map's **Check local
security** runs the same checks on observed repositories, in memory only.

**History cleanup** is dangerous maintenance and is built to be hard to misuse. It rewrites only
a new private mirror, never the source, and never publishes:

```sh
gitso history scan /path/to/repo --out /private/history.json
gitso history clean plan /private/history.json --choices /private/choices.json --include-remote-refs --plan-out /private/plan.json
gitso history clean rewrite /private/plan.json --workspace /private/new-run --apply PLAN_ID
```

`gitso docs history clean` gives the choices format. Rewriting always needs a person: an
attended terminal, the plan id and the typed word `REWRITE`; it has no unattended form. Remaining findings or gaps hold the result for review. A verified
mirror does not rotate credentials, erase other copies or update other clones: publishing it is
your step, and `gitso history follow` then moves your clones onto it.

[Back to the README](../README.md)
