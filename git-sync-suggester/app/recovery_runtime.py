"""Event-driven medium-tier recovery work for a running peer.

This is intentionally small: filesystem events already debounce before it is called, so there is
no second scan or polling loop.  It only captures repositories selected by the separate capture
basket and only after the user confirmed a private recovery location.
"""
from __future__ import annotations

from pathlib import Path

import baskets
from capture import CaptureRefused, capture, untracked_candidates
from fleet_config import recovery_policy
from snapshot_store import SnapshotStore, StoreRefused, content_digest


class RecoveryRuntime:
    def __init__(self, config: dict, observer, log=print):
        self.config, self.observer, self.log = config, observer, log
        recovery = config.get("recovery") or {}
        self.location = recovery.get("location") if recovery.get("confirmed") else None
        self.store = (SnapshotStore(self.location, config["machine_id"])
                      if self.location else None)
        self.acknowledged: set[tuple[str, str, str]] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.store and self.config["baskets"]["capture"]["mode"] != "none")

    def capture_paths(self, paths) -> int:
        """Capture affected, enrolled repositories.  Refusal is visible and never fatal."""
        if not self.enabled:
            return 0
        local, namespaces, written = self.observer.local_repositories(), self.observer.namespaces(), 0
        by_path = {path.resolve(): repo_id for repo_id, path in local.items()}
        for raw_path in paths:
            repo_id = by_path.get(Path(raw_path).resolve())
            if not repo_id or not baskets.selects(self.config["baskets"]["capture"],
                                                   namespaces.get(repo_id, "")):
                continue
            path = local[repo_id]
            try:
                body = capture(path, repo_id, self.config["machine_id"],
                               untracked=untracked_candidates(path),
                               policy=recovery_policy(self.config, repo_id)).to_dict()
                result = self.store.write(body)
            except (CaptureRefused, StoreRefused, OSError) as exc:
                self.log(f"Recovery snapshot deferred for {path.name}: {exc}")
                continue
            if result["written"]:
                written += 1
                self.log(f"Recovery snapshot written for {path.name}; it becomes durable after "
                         "another peer verifies it.")
        return written

    def acknowledge_available(self) -> int:
        """Verify peer bundles visible in the shared folder and record one local acknowledgement."""
        if self.store is None:
            return 0
        count = 0
        for source in self.store.machines():
            if source == self.config["machine_id"]:
                continue
            for version in self.store.versions(machine_id=source):
                key = (source, version.repo_id, version.version)
                if key in self.acknowledged:
                    continue
                try:
                    self.store.acknowledge(*key)
                except StoreRefused as exc:
                    self.log(f"Recovery snapshot from peer could not be verified: {exc}")
                    continue
                self.acknowledged.add(key)
                count += 1
        if count:
            self.log(f"Verified {count} recovery snapshot(s) from another peer.")
        return count

    def current_snapshot_state(self, path) -> str | None:
        """Whether this checkout's *present* saved work is verified on another machine.

        A prior snapshot is not enough: recapture the current state in memory and compare the
        content digest.  This keeps safe-to-wipe from treating an older save as coverage for a
        later edit.  Capture remains read-only and refuses anything it cannot represent.
        """
        if self.store is None:
            return None
        wanted = Path(path).resolve()
        repo_id = next((key for key, value in self.observer.local_repositories().items()
                        if value.resolve() == wanted), None)
        if not repo_id:
            return None
        try:
            current = capture(wanted, repo_id, self.config["machine_id"],
                              untracked=untracked_candidates(wanted),
                              policy=recovery_policy(self.config, repo_id)).to_dict()
        except (CaptureRefused, OSError):
            return None
        for version in reversed(self.store.versions(repo_id=repo_id)):
            try:
                saved = self.store.read(self.config["machine_id"], repo_id, version.version)
            except StoreRefused:
                continue
            if content_digest(saved) == content_digest(current):
                return self.store.status(repo_id, version.version)
        return None
