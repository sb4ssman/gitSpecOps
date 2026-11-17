# Three problems, and how they were solved

Each of these started from an assumption that turned out to be wrong. Each has the test that
now pins the fix, and what is still not covered.

## 1. Work on a machine that is switched off must not disappear

**The problem.** You have several machines. You leave unfinished work on one and turn it off.
From another machine you want to know that the work exists, and where.

**The assumption that failed.** "A machine's status is whatever it last said, while it is
fresh." Two things broke. A fixed two-minute freshness window marked every quiet machine stale,
and with it every repository on it. Worse, in the other direction: an old report that said
"clean" read as an all-clear, although nobody could know what had happened since. Later a third
gap appeared: a machine that joined after another had been turned off never heard of it at all.

**The design.**
- Freshness follows how reports actually arrive: twice the slowest chosen route, plus a minute
  (`stale_after` in `Elaborate/_fleet/peer.py`).
- An old report keeps its evidence of unfinished work, and never counts as proof of being clean
  (`Elaborate/_fleet/aggregate.py`): "last known: 3 uncommitted files", not "in sync".
- Each machine keeps the last report it saw from every other and passes it on, so a newcomer
  learns about a machine that is off (`/v1/known`). An older report never replaces a newer one.
- A machine shows its own previous report while it rereads its libraries, so it never vanishes
  from its own page.

**The tests.** `tests/elaborate/test_sync_aggregate.py`, `tests/elaborate/test_core_path.py`,
`tests/elaborate/test_known_reports.py`.

**Still open.** File names never travel in a report, only counts. To see *which* files are
uncommitted on a machine that is off, you have to turn it on, or have enrolled recovery
snapshots beforehand.

## 2. Checking what is about to be published

**The problem.** Before a branch is pushed, or a repository is made public, nothing in it
should be a credential or one of your own private values.

**The assumption that failed.** "Scan the files." A value committed once and deleted in the
next commit is gone from the files and still in the history that gets pushed. A second
assumption failed too: that a check made a moment ago still describes what is pushed now.

**The design.**
- The push check reads the **outgoing history**: every commit that would leave this machine
  (`Special/_security/_push.py`).
- A plan is bound to one exact commit and one exact destination. Applying it rechecks the
  source, the destination and the policy; if any moved, the plan is refused and nothing is sent.
- `gitso push` itself names its remote and one refspec, so no Git configuration can widen it
  or overwrite the remote branch (`Basic/push.py`).
- What could not be read (a PDF, an archive format, a Git LFS payload) is reported as a gap,
  and a check with gaps does not call itself a pass.

**The tests.** `tests/security/test_push_gate.py` (a secret introduced, then removed, in
outgoing history; a moved branch; a changed policy), `tests/basic/test_pinned_push_pull.py`
(a force refspec, a mirror remote, `push.default`), `tests/security/test_audit.py`.

**Still open.** Binary content is screened as raw strings only. Org copy pushes an exact copy
unless you answer yes to its security question; that is your choice, stated in its setup.

## 3. Restoring unfinished work, and proving a snapshot is no longer needed

**The problem.** A machine dies, or is far away, with uncommitted work on it. You want that
work on another machine, and later you want to delete the snapshot knowing nothing is lost.

**The assumption that failed.** "Snapshots must be encrypted." The first design required an
encryption tool. It would have meant carrying a key to every machine that might restore, and
losing the key would destroy exactly the work the feature exists to save. A key stored beside
what it encrypts protects nothing.

**The design** (`Elaborate/_recovery/`, `docs/RECOVERY-DESIGN.md`).
- A snapshot is two exact patches (staged, and unstaged) against a named commit, written where
  you separately enrolled capture: never silently into the folder used for status.
- Another machine acknowledges that it holds the snapshot before the first machine may count on it.
- A restore is previewed, then applied in a disposable checkout, never over existing work.
- A snapshot may be retired only on proof that its content is on a remote.
- Secret screening before capture is load-bearing, because nothing is encrypted.

**The tests.** `tests/elaborate/test_recovery_runtime.py`, `tests/elaborate/test_safe_to_wipe.py`.

**Still open.** It has not been used across two real machines. Its secret screen uses its own
rules, not the shared security rules, and cannot screen binary patches. Treat it as built and
tested, not yet proven.
