# Handoff — design pass (not yet implemented)

_Written 2026-09-03. `handoff` has been a reserved, non-functional subcommand since the Sync
Suggester scaffold. This is the design pass it was reserved for. Nothing here is built._

## The problem it solves

Sync Suggester can already tell you *that* you left uncommitted work on the desktop. Handoff is
the question that follows: **can I have it here?**

That is a different kind of operation from everything else in gitSpecOps, and the difference is
worth stating before any design:

| | Everything so far | Handoff |
|---|---|---|
| Direction | reads local state, publishes facts | moves *content* between machines |
| Failure cost | a stale or missing report | lost or overwritten work |
| Transport carries | hashes and counts | your actual source |
| Reversibility | trivially re-run | may not be undoable |

That last row is the whole reason this gets its own document.

## The privacy boundary changes completely

Today the state folder is a set of manifests with hashed identities, no names, no paths, no
content. Someone who obtains it learns very little (see
[`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md)).

**Handoff would put real source code in that folder.** A patch of your working tree is your
working tree. Whatever the cloud provider, the shared drive, or an old backup can see, they would
now see your unfinished work.

This is not an argument against building it — it is an argument that the state folder must stop
being one undifferentiated place. Minimum:

- Content lives in a **separate, explicitly configured directory** from manifests, so a user can
  point manifests at a convenient sync folder and content somewhere stricter (or nowhere).
- The tool states, at the moment of transfer, that it is writing source into that location.
- Handoff content is **expiring by design**: it is a courier, not a backup. Old bundles are
  listed and removable, and the tool should refuse to accumulate silently.
- If content transfer is ever enabled by default, this design has failed.

## What can actually be handed off

Not one thing — five, with sharply different risk:

1. **Committed but unpushed commits.** The easy case, and it is not really handoff at all: the
   answer is *publish*, i.e. a non-force push. Git already refuses a non-fast-forward. This
   should be the first and possibly only thing built, and it belongs with the archive tools'
   push direction (see the "publish" notes in [`README.md`](README.md)), not here.
2. **Staged and unstaged changes to tracked files.** A `git diff` / `git diff --cached` pair, or
   one `git stash create` object. Self-describing, reviewable, and applies cleanly or refuses.
3. **Untracked files.** The dangerous one. Untracked means git was never told what these are, so
   the set routinely includes `.env` files, credentials, large binaries, build output that
   happened to escape `.gitignore`, and editor scratch. Transferring untracked files by default
   would be the single most likely way this tool leaks a secret.
4. **Ignored files.** Never. There is no reading of "the user ignored this" that means "please
   copy it to another machine".
5. **Stashes.** Explicit, named, and easy to enumerate — but a long-lived stash is often
   deliberate local state, not work in flight. Opt-in per stash, never wholesale.

## Three candidate mechanisms

### A. Publish to a WIP branch (recommended for committed work)

Commit (or `git stash create`) on the source machine, push to a per-machine branch such as
`wip/<machine-id>`, fetch it on the target. Uses git for what git is for; content never touches
the state folder; history is preserved; nothing is destroyed.

Costs: requires write access to the remote, and pushes work-in-progress to a server — which for a
**public** repository means publishing it to the world. The fork-visibility constraint already
recorded in [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md) applies directly: there is
no such thing as a private branch in a public repository. The tool must check repository
visibility and refuse, loudly, rather than assume a WIP branch is private.

### B. Patch through the content directory

`git diff` + `git diff --cached` (+ an explicit list of chosen untracked files) written as one
file into the content directory; the target machine reviews and applies. No remote, no server, no
visibility problem, works for a repository with no push access.

Costs: source in the sync folder (see above), and patches fail against a different base commit —
so the base SHA must be recorded and checked, and a mismatch must stop rather than force.

### C. `git bundle`

A real, verifiable git object transfer. Strictly better than a patch for committed work and
carries its own integrity checking. Worth preferring over B whenever what is being moved is
commits rather than a dirty tree.

**Recommendation:** A for committed work, C for anything else that is committable, B only for a
genuinely dirty tree, and 3/4/5 above behind individual explicit opt-ins.

## Rules any implementation must keep

These follow from what the rest of the repo already got right; breaking them would make handoff
the weak point in an otherwise careful toolset.

- **Never inside `watch`, never in a scheduled launcher, never in `check`.** Same rule that keeps
  `--reconcile`/`--rename-folders` interactive-only in the archive tools. A background process
  must never move source code.
- **Its own apply class**, never bundled into an existing verb.
- **Never auto-commit.** Committing on the user's behalf rewrites the meaning of their working
  tree. If a commit is required to transfer, say so and make them ask for it.
- **The receiving side never destroys.** Apply into a clean tree, or refuse. No `--force`, no
  `reset --hard`, no stash-and-hope. A refusal is a correct outcome.
- **Base-commit checked.** Record the base SHA and refuse to apply against a different one.
- **Untracked files are individually listed and individually confirmed**, with size and a
  secret-shaped-name warning (`.env`, `*.pem`, `id_rsa`, `*.key`, credentials). Never a glob,
  never "everything untracked".
- **Dry run first**, showing exactly what would move and how big it is.
- **Idempotent and resumable**, like every other operation here.

## Open questions for the user

1. Is handoff wanted for *dirty trees* at all, or is "publish my unpushed commits" (mechanism A)
   the actual need? A is far smaller, far safer, and may be the whole feature.
2. Is a content directory separate from the manifest directory acceptable, or should content
   transfer stay entirely on git remotes (A/C only, never B)?
3. For public repositories, is pushing WIP branches acceptable at all, given they are world-
   readable? If not, private repositories get A and public ones get C-into-a-private-remote or
   nothing.

## Suggested first slice, if it proceeds

Do not build handoff. Build **publish** — the ahead-only, non-force push already designed in
[`README.md`](README.md#future-direction-the-push-direction-publish) — and see whether the
remaining need is real. Most of "I left work on the other machine" is unpushed commits, and that
case needs no new transport, no new privacy boundary, and no patch machinery.
