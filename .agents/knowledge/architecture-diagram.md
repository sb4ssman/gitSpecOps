# The architecture, as a picture

The canonical, diffable form of the flow chart. **Keep this in step with
[`architecture-layers.md`](architecture-layers.md)**: if the two disagree, the layers document is
the specification and this is the thing to fix.

Read it top to bottom: git is the raw material, and each layer below is built on the one above it.
*Take git operations, assume you are already authenticated, make repeating them easy.*

```text
                       ┌───────────────────────────┐   ┌──────────────────────┐
                       │ git                       │   │ gh, and its kind     │
                       │ your real git, on PATH    │   │ already logged in    │
                       └─────────────┬─────────────┘   └───────────┬──────────┘
                            wrapped with care                 wrapped too
                                     v                             v
┌──────────────────┐   ┌──────────────────────────────────────────────────────┐
│ TERMINAL         │──>│ Basic                                      ADDS CARE │
│                  │   │ one git or host operation, wrapped                   │
│ come in at any   │   │ git/   fetch pull push         providers/  github    │
│ layer — every    │   │        clone status            one module per host   │
│ operation is a   │   │        ff-only, never --force  chosen by remote URL  │
│ plain script     │   └─────────────┬────────────────────────────────────────┘
│ that runs alone  │      repeated, with judgment
│                  │                 v
│ pull.py <repo>   │   ┌───────────────────────────┐
│ archive_update…  │──>│ Special   ADDS JUDGMENT   │
│ catchup.py       │   │ archive_update            │
│                  │   │ archive_sync duplicate_org│
│ nothing depends  │   └─────────────┬─────────────┘
│ on the App       │     widened — machines, time
│ existing         │                 v
│                  │   ┌───────────────────────────┐
│                  │──>│ Elaborate   ADDS REACH    │
└──────────────────┘   │ check peer catchup audit  │
                       │ recovery materialize      │
                       │ archive_manage converge … │
                       └─────────────┬─────────────┘
                          assembled for a human
                                     v
                       ┌───────────────────────────┐   ┌──────────────────────┐
                       │ App         OPTIONAL      │···│ App/skins/           │
                       │ tray dashboard autostart  │   │ lcars modern retro   │
                       │ setup_fleet version       │   │ all three ship       │
                       └───────────────────────────┘   └──────────────────────┘

   ──>   an entry point: come in at any layer, from the terminal
    v    built on what is above it
   ···   a contract, not a call: every skin consumes the versioned display contract
```

## What the picture is asserting

- **git is the foundation, not a detail.** Everything shells out to the user's real git; nothing
  reimplements it. `gh` sits beside it because **authentication is assumed**: done by the user,
  never stored, configured or asked for here.
- **Basic wraps both.** `git/` holds one careful wrapper per git operation. `providers/` holds the
  host seam, one module per host, chosen by the remote's URL. Adding a host is one file and one
  register line.
- **Each layer is built on the one above.** A layer uses only the layers above it, never sideways
  and never what comes after. A test reads the imports and enforces it.
- **The terminal enters anywhere.** Every operation is a plain script that runs on its own, and
  the App adds presence, not capability.
- **`check` and `peer` are one job run two ways**: observe, publish, show. Once, or continuously.
- **The skins hang off the App on a dashed line with no arrowhead**, because a contract is not a
  call. All three ship.

## The rendered version

[`../diagrams/architecture-flow.dc.html`](../diagrams/architecture-flow.dc.html) is the source of
the shareable rendering: a single self-contained page, dark ground, one hue per layer (teal Basic,
brass Special, terracotta Elaborate, violet App).

It is published as a private canvas for sharing. **The live URL is deliberately not tracked here**,
because this is a public repository and an artifact link is account-specific. A session that needs
to update the published copy should ask the user for the link, or look in its own local notes.

When the architecture changes, update `architecture-layers.md` first, then the ASCII above, then
the rendered page, in that order, so the specification never trails the picture.
