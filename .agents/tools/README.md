# `.agents/tools/` — agent-owned helper scripts

**Everything in this folder except this README is gitignored.** Tools are fetched per-machine,
never vendored: they live in their own repositories under their own licenses, and copying them
here would fork them silently and put someone else's code under this repo's license.

Output goes to [`../output/`](../output/README.md), which is also untracked.

## Get the folder-structure mapper

This is the first thing to run in an unfamiliar checkout — it answers "what is actually here?"
in one pass, with caches, virtualenvs and build outputs already excluded.

```bash
curl -sSfL -o .agents/tools/generate_folder_structure.py \
  https://raw.githubusercontent.com/sb4ssman/PythonTools/main/LLM_Tools/generate_folder_structure.py
```

PowerShell:

```powershell
curl.exe -sSfL -o .agents\tools\generate_folder_structure.py `
  https://raw.githubusercontent.com/sb4ssman/PythonTools/main/LLM_Tools/generate_folder_structure.py
```

Source: <https://github.com/sb4ssman/PythonTools> (`LLM_Tools/generate_folder_structure.py`).

## Use it

```bash
python .agents/tools/generate_folder_structure.py --path . --out .agents/output/folder_structure.md
```

`--path` picks the tree to scan and `--out` the Markdown file to write; `--org` scans one level
above the repository, which is how you see sibling checkouts on a machine.

Then **read the output file** before reasoning about layout. Do not reconstruct the tree from
memory or from a handful of `ls` calls — that is how a session ends up describing folders that
were renamed three commits ago.

## Adding another tool

Add the fetch command and a one-line "what it answers" to this README. Do not commit the script
itself. If a tool has no upstream home, it does not belong here — put it in the repository
proper, with tests.
