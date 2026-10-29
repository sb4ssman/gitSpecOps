"""Explicit plan -> new private mirror -> native rewrite -> exact proof, never publication.

Headless plumbing only: execute requires typed REWRITE and an exact plan id. It never edits
the source checkout, follows rewritten refs, commits or pushes. A failed private workspace is
retained for inspection; no retry, --force, original-history deletion or automatic cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from Basic._history_read import OID, integrity
from Basic._history_mirror import finish, restore_symbols
from Basic._run import run
from Basic.clone import clone
from Special._history.native import snapshot
from Special._history.plan import Plan, save
from Special._history.proof import compare
from Special._history.rules import Rules
from Special.security._private_files import private_path, write_private_json

ROOT = Path(__file__).resolve().parents[2]


def command(*, preserve_remote_refs=False):
    """Fixed reviewed callbacks; input values live only in private JSON, never Python code."""
    module = "Special._history.callbacks"
    return ["git", "filter-repo", *(["--partial"] if preserve_remote_refs else []),
            "--prune-empty", "never", "--prune-degenerate", "never",
            "--preserve-commit-hashes", "--preserve-commit-encoding", "--replace-refs", "delete-no-add",
            "--file-info-callback", f"from {module} import file_info; return file_info(filename, mode, blob_id, value)",
            "--message-callback", f"from {module} import message as transform; return transform(message)",
            "--commit-callback", f"from {module} import commit as transform; transform(commit)",
            "--tag-callback", f"from {module} import tag as transform; transform(tag)"]


def _mapping(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("commit map exceeds its limit")
    lines = path.read_text(encoding="ascii").splitlines()
    if not lines or lines[0].split() != ["old", "new"]:
        raise ValueError("unsupported commit map")
    result = {}
    for line in lines[1:]:
        pair = line.split()
        if len(pair) != 2 or any(not OID.fullmatch(item) or set(item) == {"0"} for item in pair) or pair[0] in result:
            raise ValueError("incomplete or ambiguous commit map")
        result[pair[0]] = pair[1]
    return result


@dataclass
class Outcome:
    proof: object
    mirror: Path = field(repr=False)
    artifacts: tuple = field(repr=False)

    def record(self):
        result = self.proof.record()
        result.update(operation="history-mirror-rewrite", status="rewritten-and-verified",
                      source_refs_unchanged=True, artifact_count=len(self.artifacts), publication_clearance=False)
        return result


def execute(plan, workspace, *, confirmation, approved_plan, artifacts=None):
    """Create one new mirror only. Reject stale choices/source before any rewrite."""
    if not isinstance(plan, Plan) or confirmation != "REWRITE" or approved_plan != plan.plan_id:
        raise ValueError("typed REWRITE and approval of this exact plan are required")
    plan.current()
    before, before_reader = snapshot(plan.source, include_remote_refs=plan.include_remote_refs)
    plan.current()
    rules = Rules.from_record(plan.choices)
    workspace = private_path(Path(workspace) / "plan.json").parent
    source = Path(plan.source)
    if workspace.is_relative_to(source) or source.is_relative_to(workspace):
        raise ValueError("source and private output must not overlap")
    integrity(source)
    created = [] if artifacts is None else artifacts
    workspace.mkdir(mode=0o700)
    created.append(workspace)
    plan_path, mirror = workspace / "plan.json", workspace / "mirror.git"
    save(plan, plan_path)
    created.append(plan_path)
    try:
        cloned = clone(plan.source, mirror, mirror=True, no_local=True)
    finally:
        if mirror.is_dir():
            created.append(mirror)
    if cloned.returncode:
        created.append(write_private_json(workspace / "clone-failure.json", {"stdout": cloned.stdout, "stderr": cloned.stderr}))
        raise ValueError("private mirror clone failed; private diagnostic retained")
    if plan.include_remote_refs:
        restore_symbols(mirror, plan.symbolic_refs, {name: plan.refs[name] for name in plan.symbolic_refs})
    mirrored, mirror_reader = snapshot(mirror, include_remote_refs=plan.include_remote_refs)
    if mirrored != before:
        raise ValueError("private mirror does not match exact planned source")
    # Preload/cache the independent source and clone reads before the child can prune objects.
    del mirror_reader
    plan.current()
    result = run(command(preserve_remote_refs=plan.include_remote_refs), cwd=mirror, timeout=300,
                 env={"GITSPECOPS_HISTORY_PLAN": str(plan_path), "PYTHONPATH": str(ROOT),
                      "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"})
    run_path = write_private_json(workspace / "native-run.json",
                                 {"returncode": result.returncode, "timed_out": result.timed_out,
                                  "missing": result.missing, "stdout": result.stdout, "stderr": result.stderr})
    created.append(run_path)
    if result.returncode:
        raise ValueError("native rewrite failed; private diagnostic retained")
    mapping = _mapping(mirror / "filter-repo" / "commit-map")
    if plan.include_remote_refs:
        restore_symbols(mirror, plan.symbolic_refs, {name: mapping[plan.refs[name]] for name in plan.symbolic_refs})
    integrity(mirror)
    after, after_reader = snapshot(mirror, include_remote_refs=plan.include_remote_refs)
    proof = compare(before, after, mapping, rules, before_reader.blob, after_reader.blob)
    proof_path = write_private_json(workspace / "proof.json", proof.record())
    created.append(proof_path)
    if proof.status != "matched-model":
        raise ValueError("native history does not match the declared transformations")
    if plan.include_remote_refs:
        plan.current()
        finish(mirror)
        integrity(mirror)
        if snapshot(mirror, include_remote_refs=True)[0] != after:
            raise ValueError("mirror refs or history changed during object cleanup")
    plan.current()
    final_source, unused = snapshot(plan.source, include_remote_refs=plan.include_remote_refs)
    if final_source != before:
        raise ValueError("source history changed during the operation")
    return Outcome(proof, mirror, (plan_path, run_path, proof_path))
