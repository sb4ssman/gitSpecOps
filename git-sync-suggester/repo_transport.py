"""Manifest transport backed by a private GitHub repository — without cloning it.

The obvious way to use a repo as a state store is to clone it, commit, pull, push, and
resolve conflicts. That is the tedious way, and none of it is necessary for what this
stores: a handful of small JSON files, each written by exactly one machine.

Instead this uses the Contents API through the already-authenticated `gh` CLI:

    read   GET  /repos/{owner}/{repo}/contents/{path}   -> content + blob sha
    write  PUT  /repos/{owner}/{repo}/contents/{path}   -> requires that sha to replace

No clone, no working copy, no local git state, no merge logic. The blob `sha` returned by
the read is exactly what the write needs, which gives optimistic concurrency for free: if
another machine wrote between our read and our write, GitHub rejects it with 409 and we
re-read rather than clobber.

Auth is the user's own `gh` login, consistent with the rest of gitSpecOps — nothing here
stores or manages a credential.

**Never call this from a git hook.** A network round trip inside `git commit` is
unacceptable; the hook writes local state and something else uploads it later.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.gh_cli import GhError, run_gh  # noqa: E402

from folder_transport import SAFE_MACHINE_ID  # noqa: E402
from manifest import decode_manifest, encode_manifest  # noqa: E402

MANIFEST_DIR = "machines"
# owner/name, each segment restricted to what GitHub actually allows.
SAFE_REPO_SPEC = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


class RepoTransport:
    """One private repository holding one manifest per machine, addressed by the API."""

    def __init__(self, spec: str, branch: str | None = None):
        if not SAFE_REPO_SPEC.fullmatch(spec or ""):
            raise ValueError(f"state repo must look like owner/name, got {spec!r}")
        self.spec = spec
        self.branch = branch

    # -- plumbing ---------------------------------------------------------------------

    def _api(self, path: str, method: str = "GET", fields: dict | None = None,
             allow_missing: bool = False) -> object | None:
        endpoint = f"repos/{self.spec}/{path}" if path else f"repos/{self.spec}"
        args = ["api", endpoint, "--method", method]
        for key, value in (fields or {}).items():
            args += ["-f", f"{key}={value}"]
        if method == "GET" and self.branch:
            args += ["-f", f"ref={self.branch}"]
        try:
            proc = run_gh(args)
        except GhError as exc:
            if allow_missing and ("404" in str(exc) or "Not Found" in str(exc)):
                return None
            raise
        text = (proc.stdout or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GhError(f"gh returned unreadable JSON for {path}: {exc}") from exc

    def _contents(self, path: str, allow_missing: bool = True):
        return self._api(f"contents/{path}", allow_missing=allow_missing)

    # -- the transport interface (mirrors FolderTransport) ------------------------------

    def list_manifests(self) -> list[str]:
        """Manifest filenames in the repo. A missing repo or folder reads as empty."""
        listing = self._contents(MANIFEST_DIR)
        if not isinstance(listing, list):
            return []
        return sorted(item["name"] for item in listing
                      if isinstance(item, dict) and item.get("type") == "file"
                      and str(item.get("name", "")).endswith(".json"))

    def read_manifest(self, name: str) -> dict:
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("manifest name must be a plain .json filename")
        payload, _sha = self._read_raw(f"{MANIFEST_DIR}/{name}")
        if payload is None:
            raise ValueError(f"no such manifest: {name}")
        return decode_manifest(payload)

    def _read_raw(self, path: str) -> tuple[bytes | None, str | None]:
        """Returns (decoded bytes, blob sha). The sha is what makes a safe write possible."""
        record = self._contents(path)
        if not isinstance(record, dict) or "content" not in record:
            return None, None
        try:
            raw = base64.b64decode(record["content"])
        except (ValueError, TypeError) as exc:
            raise GhError(f"could not decode {path}: {exc}") from exc
        return raw, record.get("sha")

    def write_own_manifest(self, machine_id: str, manifest: dict) -> str:
        """Replace this machine's manifest. Retries once if another writer got in first."""
        if not SAFE_MACHINE_ID.fullmatch(machine_id):
            raise ValueError("machine_id may contain only letters, digits, dot, underscore, "
                             "and dash")
        if manifest.get("machine_id") != machine_id:
            raise ValueError("manifest machine_id does not match the destination")
        payload = encode_manifest(manifest)
        path = f"{MANIFEST_DIR}/{machine_id}.json"

        for attempt in range(2):
            _existing, sha = self._read_raw(path)
            fields = {
                "message": f"sync-suggester: {machine_id}",
                "content": base64.b64encode(payload).decode("ascii"),
            }
            if sha:
                fields["sha"] = sha
            if self.branch:
                fields["branch"] = self.branch
            try:
                self._api(f"contents/{path}", method="PUT", fields=fields)
                return f"{self.spec}:{path}"
            except GhError as exc:
                # 409/422 here means the blob moved under us — another machine wrote, or our
                # cached sha is stale. Re-reading and retrying is correct; forcing is not.
                if attempt == 0 and ("409" in str(exc) or "422" in str(exc)):
                    continue
                raise
        raise GhError(f"could not write {path}: the remote kept changing under us")

    def doctor(self) -> dict:
        report: dict = {"kind": "repo", "spec": self.spec, "branch": self.branch}
        try:
            info = self._api("", allow_missing=True)
        except GhError as exc:
            report["error"] = str(exc)
            return report
        if not isinstance(info, dict):
            report["exists"] = False
            return report
        report["exists"] = True
        report["private"] = bool(info.get("private"))
        report["permissions"] = (info.get("permissions") or {}).get("push")
        report["manifest_count"] = len(self.list_manifests())
        if not report["private"]:
            report["warning"] = ("this repository is PUBLIC — machine status would be visible "
                                 "to anyone; use a private repository")
        return report


def repo_exists(spec: str) -> bool:
    try:
        return RepoTransport(spec).doctor().get("exists", False)
    except (GhError, ValueError):
        return False


def create_state_repo(spec: str, description: str | None = None) -> str:
    """Create the private state repository. The caller must have confirmed this first.

    Kept as a separate, explicit function — creating a repository on someone's account is an
    outward-facing act and must never be a side effect of a status command.
    """
    if not SAFE_REPO_SPEC.fullmatch(spec or ""):
        raise ValueError(f"state repo must look like owner/name, got {spec!r}")
    args = ["repo", "create", spec, "--private",
            "--description", description or "gitSpecOps Sync Suggester machine state"]
    run_gh(args)
    return spec
