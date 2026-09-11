# Manual probes

Tracked, repeatable experiments for behavior that depends on an installed application, a real
OS feature, or a user's environment. Keep probe code, synthetic fixtures, and instructions
here. Keep regression tests in the normal area folders under `tests/`.

Probes are **never run by `tests/run_all.py`**. Each probe must explain its prerequisites,
side effects, output location, and what a result does and does not establish. Launching an
application, accessing a real account, or changing external state remains an explicit action.

Generated profiles, logs, and raw results belong in temporary storage or `.agents/output/`,
not in this tracked directory. Only sanitized conclusions should enter the work log or
knowledge records. Use invented fixture names and never copy real source content into probes.

| Probe | Question | Prerequisite |
|---|---|---|
| [VS Code hot exit](vscode_hot_exit/README.md) | Does a dirty buffer reach backup storage before exit? | Installed VS Code |
