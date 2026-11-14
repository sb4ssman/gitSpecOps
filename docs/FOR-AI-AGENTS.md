# gitSpecOps for AI agents

`gitso` is built so an agent can work with your repositories as safely as you can:

```sh
gitso suggest-sync --json          # this machine: what needs attention
gitso suggest-fleet-sync           # every machine
gitso scan-tree <repo> --json      # findings, masked
gitso secure-commit <repo> <files> -m "…"   # a plan with an id; nothing happens yet
gitso secure-commit <repo> <files> -m "…" --apply --approve <plan id>
gitso docs <command>               # what a command reads, may change, and returns
```

- **Every command says what it does** before it does it: what it reads, what it may change,
  where results go.
- **Plans, then approval.** Anything that changes a repository first returns a plan with an id;
  applying requires that exact plan, and a changed repository invalidates it.
- **The same gates as you.** An agent using `secure-commit` and `secure-push` passes the same
  security checks, so it cannot publish what must not leave.
- **Machine-readable** results with `--json`, and no prompts when every choice is a flag.

[Back to the README](../README.md)
