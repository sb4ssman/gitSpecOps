# gitSpecOps for AI agents

`gitso` is built so an agent can work with your repositories as safely as you can:

```sh
gitso machine check                 # this machine: what needs attention
gitso machine map                   # this machine's libraries as a tree, each repository's state
gitso fleet suggest           # every machine
gitso scan <repo>             # findings, masked
gitso secure-commit <repo> <files> -m "…"                   # a plan with an id; nothing happens yet
gitso secure-commit <repo> <files> -m "…" --apply <plan id>  # exactly that plan
gitso docs <command>               # what a command reads, may change, and returns
```

## What an agent gets back

An agent runs without a terminal, so every command answers with **one JSON record** on stdout,
with no option needed. The record always starts the same way:

```json
{"command": "secure-commit", "ok": true, "...": "the command's own fields"}
```

A failure is `{"command": …, "ok": false, "error": "one plain sentence"}` and a nonzero exit.
There are no colours, no banner and no prompts. A person at a terminal sees a screen instead;
`--json` asks for the record there too.

## Plans, then approval

A command that changes things first works out its plan and changes nothing. Its record holds:

- `plan`: what it would do;
- `plan_id`: an id for exactly that plan (a digest of its content);
- `apply`: the exact command that carries it out.

Run that command (the same one, with `--apply <plan id>`) to apply it. If anything changed in
between, the plan worked out now has a different id: nothing is done, the new plan comes back,
and the exit code is 3. Commands that ask about several folders (`archive update`,
`archive sync`) give each folder's plan its own id; repeat `--apply` for each.

Exit codes: 0 done (or planned), 1 something needs attention, 2 a usage or settings error, 3 the
plan changed.

## What stays a person's

- **History rewrites** (`history clean rewrite`) need a person at a terminal who types REWRITE,
  as well as the plan id. There is no unattended form.
- **The fleet key** is shown only by `gitso fleet key --show`; any agent reading that
  output receives it.
- **The same gates as a person.** `secure-commit`, `secure-push` and archive publication pass
  the same security checks for an agent, so an approved plan still cannot publish what must not
  leave.

Basic commands (`commit`, `push`, `pull`, ...) act at once, like `git`. So do single explicit
settings, such as naming a repository or turning start-at-sign-in on.

[Back to the README](../README.md)
