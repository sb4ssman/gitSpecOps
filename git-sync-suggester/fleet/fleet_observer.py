"""Cached fleet inventory with event-targeted Git status refreshes."""
from __future__ import annotations

from pathlib import Path

from manifest import build_manifest, fleet_id_for
from observer import RootSpec, observe_paths, observe_roots


class IncrementalObserver:
    """Discover once, then inspect only repositories named by filesystem events."""
    def __init__(self, config: dict):
        self.config = config
        self._repos: dict[Path, dict] = {}
        self._catalog: dict[Path, dict] = {}
        self._issues: list[str] = []

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._repos)

    def inventory(self) -> int:
        roots = [RootSpec(Path(root), True) for root in self.config["roots"]]
        observation = observe_roots(roots, self.config["fleet_secret"])
        self._repos.clear()
        self._catalog.clear()
        self._issues = list(observation.issues)
        for repo in observation.repositories:
            catalog = observation.catalog[repo["repo_id"]]
            path = Path(catalog["path"]).resolve()
            self._repos[path] = repo
            self._catalog[path] = catalog
        return len(self._repos)

    def affected_repositories(self, changed: set[Path]) -> set[Path]:
        """Map noisy file events to the deepest known containing checkout."""
        affected: set[Path] = set()
        known = sorted(self._repos, key=lambda path: len(path.parts), reverse=True)
        for item in changed:
            path = Path(item).resolve(strict=False)
            for repo in known:
                try:
                    path.relative_to(repo)
                except ValueError:
                    continue
                affected.add(repo)
                break
        return affected

    def detect_new_checkouts(self, changed: set[Path]) -> set[Path]:
        """Checkouts that appeared under a watched root since the last inventory.

        Filesystem events already fire when a repository is cloned into the library — they were
        simply discarded, because `affected_repositories` maps an event only to a *known*
        checkout. So a newly cloned repository stayed invisible until someone remembered to run
        `fleet rescan`, which is exactly the kind of silent gap this project treats as a defect.

        This only *detects*. Adding a repository to what this machine observes stays an explicit
        act, in keeping with detect -> alert -> approve; the point is that the alert now exists.
        """
        roots = [Path(root).resolve() for root in self.config["roots"]]
        known = set(self._repos)
        found: set[Path] = set()
        for item in changed:
            path = Path(item).resolve(strict=False)
            if not any(self._within(path, root) for root in roots):
                continue
            if any(self._within(path, repo) for repo in known):
                continue
            # Walk up from the event to the shallowest enclosing checkout still inside a root.
            candidate = path if path.is_dir() else path.parent
            while candidate and any(self._within(candidate, root) for root in roots):
                if (candidate / ".git").exists() and candidate not in known:
                    found.add(candidate)
                    break
                if candidate == candidate.parent:
                    break
                candidate = candidate.parent
        return found

    @staticmethod
    def _within(path: Path, ancestor: Path) -> bool:
        try:
            path.relative_to(ancestor)
        except ValueError:
            return False
        return True

    def refresh(self, changed: set[Path]) -> int:
        affected = self.affected_repositories(changed)
        for path in affected:
            previous = self._repos.pop(path, None)
            previous_catalog = self._catalog.pop(path, None)
            observation = observe_paths([path], self.config["fleet_secret"])
            if observation.repositories:
                repo = observation.repositories[0]
                self._repos[path] = repo
                self._catalog[path] = observation.catalog[repo["repo_id"]]
            elif previous is not None and path.is_dir():
                # A transient read error should not erase the last-known warning. A removed
                # origin is retained until the next explicit inventory scan can report it.
                self._repos[path] = previous
                self._catalog[path] = previous_catalog
            if observation.issues:
                self._issues = observation.issues
        return len(affected)

    def report(self) -> dict:
        repositories = sorted(self._repos.values(), key=lambda repo: repo["repo_id"])
        names = {}
        for path, catalog in self._catalog.items():
            repo = self._repos.get(path)
            if repo is None:
                continue
            names[repo["repo_id"]] = {key: catalog[key] for key in ("host", "owner", "name")}
        return {
            "manifest": build_manifest(
                fleet_id_for(self.config["fleet_secret"]), self.config["machine_id"],
                self.config["label"], repositories),
            "names": names,
            "issues": sorted(set(issue.split(": ", 1)[0] for issue in self._issues)),
        }
