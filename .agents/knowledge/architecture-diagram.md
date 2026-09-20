# The architecture, as a picture

The canonical, diffable form of the flow chart. **Keep this in step with
[`architecture-layers.md`](architecture-layers.md)** — if the two disagree, the layers document is
the specification and this is the thing to fix.

Read it top to bottom: git is the raw material, and each layer below is built on the one above it.
*Take git operations, assume you are already authenticated, make repeating them easy.*

```text
                       ┌───────────────────────────┐   ┌──────────────────────┐
                       │ git                       │   │ gh, and its kind     │
                       │ your real git, on PATH    │   │ already logged in    │
                       └─────────────┬─────────────┘   └──────────┬───────────┘
                            wrapped with care               wrapped too
                                     v                            v
┌──────────────────┐   ┌───────────────────────────┐   ┌──────────────────────┐
│ TERMINAL         │──>│ Basic         ADDS CARE   │···│ plugins-remote/      │
│                  │   │ one git or remote op      │   │ github gitlab gitea  │
│ come in at any   │   │ git/    fetch pull push   │   │ plain-git            │
│ layer — every    │   │         clone status      │   │ chosen by remote URL │
│ operation is a   │   │ remote/ repo-list …       │   └──────────────────────┘
│ plain script     │   └─────────────┬─────────────┘
│ that runs alone  │       repeated, with judgment
│                  │                 v
│ pull.py <repo>   │   ┌───────────────────────────┐
│ archive-update…  │──>│ Special   ADDS JUDGMENT   │
│ catchup.py       │   │ archive-update  publish   │
│                  │   │ archive-sync duplicate-org│
│ nothing below    │   └─────────────┬─────────────┘
│ depends on the   │     widened — machines, time
│ App existing     │                 v
│                  │   ┌───────────────────────────┐   ┌──────────────────────┐
│                  │──>│ Elaborate   ADDS REACH    │···│ plugins-local/       │
└──────────────────┘   │ observe catchup at-risk   │   │ platform editors     │
                       │ capture restore retire    │   │ git-clients          │
                       │ materialize archive-manage│   │ chosen by detection  │
                       └─────────────┬─────────────┘   └──────────────────────┘
                          assembled for a human
                                     v
                       ┌───────────────────────────┐   ┌──────────────────────┐
                       │ App         OPTIONAL      │···│ App/skins/           │
                       │ tray dashboard peer       │   │ modern retro lcars   │
                       │ autostart cli             │   │ the one real choice  │
                       └───────────────────────────┘   └──────────────────────┘

   ──>   an entry point: come in at any layer, from the terminal
    v    built on what is above it
   ···   a contract, NOT a call — nothing in the stack imports a plugin
```

## What the picture is asserting

- **git is the foundation, not a detail.** Everything shells out to the user's real git. Nothing
  reimplements it, and `gh` sits beside it because **authentication is assumed** — already done by
  the user, never stored, configured or asked for here.
- **Each layer is built on the one above.** A layer uses only the layers above it: never sideways
  into a sibling, never what comes after. Enforced by a test that reads the imports.
- **The terminal enters anywhere.** The three arrows into Basic, Special and Elaborate are the
  point: every operation is a plain script that runs on its own, and the App adds presence, not
  capability.
- **The dashed lines carry no arrowhead on purpose.** A contract is not a call. `plugins-remote`,
  `plugins-local` and `App/skins` are implementations *behind* a contract; nothing in the stack
  imports one, and `import plugins-remote` is a syntax error besides.
- **`gh` is reached through a plugin, not from Basic.** That is what keeps `Basic` host-blind, and
  it is why a second host is a new folder rather than a rewrite.

## The rendered version

[`../diagrams/architecture-flow.dc.html`](../diagrams/architecture-flow.dc.html) is the source of
the shareable rendering — a single self-contained page, dark ground, one hue per layer (teal Basic,
brass Special, terracotta Elaborate, violet App), with the off-stack plugin boxes deliberately
colourless and dashed.

It is published as a private canvas for sharing; **the live URL is deliberately not tracked here**,
because this is a public repository and an artifact link is account-specific. A session that needs
to update the published copy should ask the user for the link, or look in its own local notes.

When the architecture changes: update `architecture-layers.md` first, then the ASCII above, then
the rendered page — in that order, so the specification never trails the picture.
