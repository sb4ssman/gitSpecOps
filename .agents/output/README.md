# `.agents/output/` — generated artifacts

**Everything in this folder except this README is gitignored**, and that is deliberate: this is
where tools from [`../tools/`](../tools/README.md) write machine-specific output — folder maps,
inventories, scratch reports. It describes *one machine at one moment*.

Two reasons it is never committed:

- It goes stale immediately, and a stale tree map is worse than none — a future session will
  believe it.
- It is full of local detail (absolute paths, sibling checkouts, private repository names) that
  must not enter a public repository. See the privacy directive in
  [`../README.md`](../README.md).

Regenerate rather than read an old copy:

```bash
python .agents/tools/generate_folder_structure.py --path . --out .agents/output/folder_structure.md
```
