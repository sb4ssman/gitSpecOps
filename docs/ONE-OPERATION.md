# One operation, end to end: commit two files from the page

Every operation in gitSpecOps is a plain Python function. A `gitso` command is one face on it;
a button on the page is another. This page follows one click all the way down, so you can see
where each rule lives and how it is tested. The other operations have the same shape.

The situation: a repository has two changed files on this machine. You open it on the page,
press **Show changes**, tick both files, write a message, press **Check this commit**, read
what comes back, and press **Commit**.

## 1. The page asks; it decides nothing

`App/_web/skins/standard/fleet_resolve.js` sends one action, `repo-action`, with the operation
(`commit-plan`), the repository's id, which copy on this machine, the file names and the message.
The page never sends a folder path. It cannot: it was never given one.

## 2. The web server checks who is asking

`App/_web/server.py` answers on `127.0.0.1` only. It refuses the action unless the request
comes from this computer, names the right Host and Origin, carries the token this page was
handed, is JSON, and is small. The view your phone sees has no such actions at all.

## 3. The peer routes it, with its own settings profile

`Elaborate/_fleet/page_actions.py` (`PageActions.repository`) reads the settings profile the app
is running with, takes the one lock that keeps two changing actions apart, and calls the
operation.

## 4. The repository is chosen from what this machine observed

`Special/_sync/resolve.py` (`repo_action`) turns the repository id into this machine's own
folders for it and picks the copy by its number. An id it does not know, or a copy number out
of range, is refused. Then it calls the real operation:

```python
commit_checked(path, files, message, settings_home=home, apply=False, approve=None)
```

That is the same function `gitso secure-commit` calls. Nothing is rebuilt as a command line, so
the profile and the target cannot be lost between the page and the operation.

## 5. The operation plans, and changes nothing

`Special/_security/_commit/operation.py` (`commit_checked`) works out exactly what the commit
would be: only the named files, the message, the identity Git would record. It runs the security
checks on that material with the policy from the profile (`Special/_security/_me.py`), and
answers with a status and a **plan id**, a digest of everything it looked at. A preview leaves
the index and the files as they were.

The page shows the answer in words: ready, or blocked with the findings (values masked).

## 6. Commit applies exactly the plan you saw

Pressing **Commit** sends `commit-apply` with that plan id. `resolve._planned` runs the
operation again for real and compares: if what would be committed is no longer what you were
shown (a file changed, the policy changed, a hook rewrote something), the ids differ and
nothing is committed. The terminal follows the same rule with `--apply PLAN_ID`.

Nothing is pushed. Push is its own operation with its own plan (`push_checked`), which checks
the history that would leave this machine.

## 7. The map catches up

The peer leaves itself a note to read this repository again; the observer does, the status
report changes, and every machine's page shows the new commit as "1 to push".

## Where the rules live

| Rule | Where |
|---|---|
| Only this computer's own page may act | `App/_web/server.py` |
| Which folder an id means | the observer, `Special/_sync/inventory.py` |
| Only the named files; identity; hooks; a preview changes nothing | `Special/_security/_commit/operation.py` |
| What counts as a finding, and its severity | `Special/_security/_material.py` and the policy in your settings |
| Apply only the plan that was shown | `Special/_sync/resolve.py` for the page, `Basic/_cli.py` for the terminal |

## How it is tested

- `tests/security/test_commit_gate.py`: the operation itself: unrelated staged work, hooks that
  change the commit, a stale approval, identity.
- `tests/special/test_resolve.py`, `PageJourneyTests`: this page's journey with a settings
  profile that is not the default and holds its own prohibition, two copies with one chosen, a
  made-up plan id refused, and the other copy left untouched.
- `tests/elaborate/test_page_actions.py`: the routing, and that the profile is passed.
- `tests/elaborate/test_fleet_app.py`: the web server's refusals.

## What is not covered

The page's own scripts have no browser tests: a button wired to the wrong action would not be
caught automatically. A person's pass over the buttons is still the check for that.
