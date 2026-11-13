# Station script design

Settled 2026-10-21, screens matched 2026-10-22; one banner on every screen 2026-11-13. How
Sb4ssport terminal scripts (install, check, setup, cleanup, maintenance launchers) look and
behave, so every station script is recognizable. DCG-Taskforce is the reference; PowerCycler
is the first adoption. Both draw the same two screens.

**This document is the whole standard.** Each script carries its own small
implementation of it (a few print helpers) in its own repository. There is no shared
runtime code and no livery for terminal scripts: a product must install and run from
its own folder alone. Copy the pattern, not a file. Liveries are for pages. If this
contract gets enough polish it can graduate to Structural-Engineering as a shape; for now
it is a directive for us writing scripts for the station.

## Two kinds of screen

Every launcher draws **menu screens** (choices) and **run screens** (doing the work). Text
is indented two spaces; bars are 72 characters wide, from column 0. A narrower console
shrinks them to the window.

**Every screen opens with the same banner:** a double bar; the title (`Product  /  Page`);
on a menu screen an optional tagline; the publisher line; the context lines; a double bar.
The first context line is always when, computer, user and shell version. A run screen adds
what is being changed and where its files or log are; a menu screen may add where the
product keeps its files.

**Menu screen:** the banner, then the answer first (a notice), rows and options.

```text

========================================================================
  Sb4ssport PowerCycler  /  Setup
  Cycle Efficiency Profiles Efficiently
  Sb4ssport-Alpha | https://sb4ssport-alpha.github.io
  2026-10-22 10:48:40 on <computer>  |  user <user>  |  PowerShell 5.1
========================================================================

  Ready to install
  Your power controls are compatible.

  Computer            Lenovo PC
  Power controls      Lenovo Fn+Q

  [1] Review setup
  [2] Customize
  [D] Detection details
  [0] Exit without installing
  Choose [1]:
```

**Run screen:** the banner (title, publisher, context lines: when, computer, user and shell
version; then what is being changed and where its files or log are), then numbered steps, a
summary and one result notice.

```text

========================================================================
  Sb4ssport PowerCycler  /  Installing
  Sb4ssport-Alpha | https://sb4ssport-alpha.github.io
  2026-10-22 10:49:12 on <computer>  |  user <user>  |  PowerShell 5.1
  Lenovo Fn+Q  |  app: %LOCALAPPDATA%\PowerCycler\app
========================================================================

  [1/5] Stop running PowerCycler       changed   0.1s  stopped the running copy
  [2/5] Application files              changed   0.8s  version 0.1.0, 74 files
  [3/5] Your settings                  ok        0.4s  Lenovo power button / Vivid Lenovo
  [4/5] Shortcuts and startup          ok        0.1s  Start menu and sign-in
  [5/5] Start PowerCycler              ok        4.0s  running in the tray

  Summary
  . Lenovo Fn+Q, tray only
```

- **Header lines:** title in accent; tagline in text; publisher in muted; context lines in
  detail, printed whole (never wrapped). Bars in muted.
- **Steps:** `[n/total] label` padded to 30, then a status word, seconds and a short
  detail. Status words: `ok`, `changed`, `skipped`, `FAILED`. A step that starts something
  checks it is still running before it says ok.
- **Rows:** label padded to 20 columns, then the value; continuation lines align under the
  value. Wrap text at spaces, and paths after a `\` or `/`.
- **Options:** `[key] Label`, with an optional one-line explanation indented under it.
  Numbers for choices; letters for actions, matching the word (D details, B back, I install,
  A apply, R remove, U uninstall); `0` to exit or go back. Show the default in the prompt:
  `Choose [1]:`. Enter takes the default; Q also exits. A one-line menu such as DCG's
  `1 Install/update updater  2 Change options ...  0 Exit` is fine for a short menu.
- **Notices:** a title line in its status color, then one plain sentence.

## Colors

| Role | Console color | Used for |
|---|---|---|
| accent | Cyan | Titles, section titles, option keys |
| muted | DarkCyan | Publisher line, bars, explanations |
| text | Gray | Everything else |
| detail | DarkGray | Run-screen context, step timings and details, raw diagnostics |
| strong | White | Step labels |
| success | Green | ok, finished, ready |
| warning | Yellow | changed, needs attention, blocked |
| error | Red | FAILED, stopped |

Use the standard console color names, so the user's terminal theme decides the exact
shade. Every status also has words; color is never the only signal. Strip control
characters from anything printed that came from outside the script.

## Behavior

1. **Lead with the answer.** Readiness and a recommendation first. Paths, internal IDs,
   raw errors and unused integrations go behind **D** (details).
2. **Unused is not missing.** Hardware or options a computer does not have are listed
   as optional, with one plain sentence on what they are for. Never as failures.
3. **Nothing changes until review.** Edits are held in memory; Back or Cancel discards
   them. A final review screen lists what will happen and needs an explicit key.
4. **Keep choices separate.** For example tray, hotkey, appearance and startup are
   independent; offer only what the hardware can actually do.
5. **Show the run:** the run screen above, then where to change things later.
6. **Fail honestly.** Say whether anything changed ("Nothing has been installed" or
   "Some steps may have completed"). Keep the technical error behind D; no stack trace
   on the main screen. A desktop app logs unexpected errors to a file and keeps running.
7. **Cleanup states its scope** (what is removed, what is kept) before removing, and
   only removes what the script itself created.
8. **One front door.** The install launcher also changes, repairs and uninstalls an
   existing installation. Scripted use (`-Unattended`, `-Json`) stays separate from
   the human screens.

## Launchers on Windows

A `.cmd` launcher calls
`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File ...`,
so it runs from a fresh clone or downloaded ZIP. It checks that its folder is complete
and tells the user to extract the ZIP first if not. `.cmd` files are pinned to CRLF in
`.gitattributes`.

This document does not authorize installation, guard changes or publication.
