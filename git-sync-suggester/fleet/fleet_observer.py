"""Cached fleet inventory with event-targeted Git status refreshes.

Baskets are applied here because this is the only place repository *names* exist: a manifest
carries salted digests, so selection cannot be expressed -- or second-guessed -- downstream.
Both halves of every split are kept. A repository excluded from observation or publication is
counted and reported, never quietly dropped.
"""
from __future__ import annotations

from pathlib import Path

import baskets
from manifest import build_manifest, fleet_id_for
from observer import RootSpec, observe_paths, observe_roots


class IncrementalObserver:
    """Discover once, then inspect only repositories named by filesystem events."""
    def __init__(self, config: dict):
        self.config = config
        self.scopes = config.get("baskets") or baskets.DEFAULT_SCOPES
        self._repos: dict[Path, dict] = {}
        self._catalog: dict[Path, dict] = {}
        self._issues: list[str] = []
        self.excluded_from_observation = 0

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._repos)

    def local_repositories(self) -> dict[str, Path]:
        """Local-only launch lookup; paths never enter a manifest or peer report."""
        return {record["repo_id"]: path for path, record in list(self._repos.items())}

    def observes(self, catalog: dict) -> bool:
        return baskets.selects(self.scopes["observe"], baskets.namespace_of(catalog))

    def namespaces(self) -> dict[str, str]:
        """`repo_id -> host/owner` for what this machine observes. Local only; never published."""
        return {repo["repo_id"]: baskets.namespace_of(self._catalog[path])
                for path, repo in list(self._repos.items()) if path in self._catalog}

    def inventory(self) -> int:
        roots = [RootSpec(Path(root), True) for root in self.config["roots"]]
        observation = observe_roots(roots, self.config["fleet_secret"])
        self._repos.clear()
        self._catalog.clear()
        self._issues = list(observation.issues)
        self.excluded_from_observation = 0
        for repo in observation.repositories:
            catalog = observation.catalog[repo["repo_id"]]
            if not self.observes(catalog):
                self.excluded_from_observation += 1
                continue
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
        if not found:
            return found
        # Only alert about checkouts this machine would actually observe. Nagging to rescan for
        # a namespace the user deliberately excluded would make the basket useless.
        observation = observe_paths(sorted(found), self.config["fleet_secret"])
        selected = {Path(catalog["path"]).resolve()
                    for catalog in observation.catalog.values() if self.observes(catalog)}
        # A candidate we could not read stays in the alert: unknown is never "not yours".
        readable = {Path(catalog["path"]).resolve() for catalog in observation.catalog.values()}
        return {path for path in found if path in selected or path not in readable}

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
                catalog = observation.catalog[repo["repo_id"]]
                if not self.observes(catalog):
                    # Its remote moved into an excluded namespace. Drop it and say so at the
                    # next inventory rather than keeping a stale record nobody chose.
                    self.excluded_from_observation += 1
                    continue
                self._repos[path] = repo
                self._catalog[path] = catalog
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

    def shared_report(self, report: dict) -> tuple[dict, set]:
        """`(report other machines may see, repo ids withheld)`.

        Publication is filtered here rather than per transport, because the tailnet peer
        endpoint serves this same report -- a repository withheld from a synced folder must not
        leak to a peer that happens to be reachable. The withheld half is returned so the local
        dashboard can say what it is not sharing.
        """
        selection = self.scopes["publish"]
        if selection["mode"] == "all":
            return report, set()
        keep, withheld = baskets.split(selection, self.namespaces())
        manifest = {**report["manifest"],
                    "repositories": [repo for repo in report["manifest"]["repositories"]
                                     if repo["repo_id"] in keep]}
        names = {key: value for key, value in report["names"].items() if key in keep}
        return {**report, "manifest": manifest, "names": names}, withheld
