"""Identity/watch/safe policy over common settings or an explicitly selected legacy profile.

load_policy accepts a selected home or caller-resolved settings. Common blocks accumulate
with explicit watch files; explicit safe values supplement saved allowances, with exact
block/safe conflicts refused. Legacy text defaults require legacy_policy=True and cannot
bypass an existing common profile. Reads discover local identity; they never save policy.
Raw values stay in trusted code; summary()/repr do not disclose them.
"""
from __future__ import annotations

import re
import copy
import os
import socket
import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from Basic._run import run
from Special._runtime.files import checked_path, excluded, linked, RuntimeIOError
from Special._settings import (SETTINGS_NAME, SettingsError, ResolvedSettings, _part,
                               _policy_conflicts, resolve_settings, select_home)


@dataclass
class Policy:
    identities: dict[str, list[str]] = field(default_factory=dict, repr=False)
    safe: list[str] = field(default_factory=list, repr=False)
    logins: list[str] = field(default_factory=list, repr=False)
    sources: dict = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)
    exclude_paths: tuple[Path, ...] = field(default=(), repr=False)
    engines: tuple[str, ...] = ()
    reviewed_examples: dict = field(default_factory=dict, repr=False)
    review_revision: str = field(default="", repr=False)

    def allowed(self, text, start, end):
        key = (tuple(self.safe), tuple(self.logins))
        if getattr(self, "_allowed_key", None) != key:
            values = [value for value in [*self.safe, *self.logins] if value]
            patterns = [rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])" for value in values]
            # A public login@HOST alias is safe; login@example.test is not a host alias.
            patterns += [rf"(?<![A-Za-z0-9]){re.escape(login)}@[A-Za-z0-9_-]{{1,253}}(?![A-Za-z0-9_.-])"
                         for login in self.logins if login]
            self._allowed_patterns = [re.compile(pattern, re.I) for pattern in patterns]
            self._allowed_window = max([len(value) for value in values] +
                                       [len(login) + 254 for login in self.logins] + [1])
            self._allowed_key = key
        # Only an enclosing safe value can allow this candidate. Searching the whole file
        # for each hit made large archives quadratic in the number of candidates.
        low, high = max(0, start - self._allowed_window), min(len(text), end + self._allowed_window + 1)
        return any(match.start() <= start and match.end() >= end
                   for pattern in self._allowed_patterns for match in pattern.finditer(text, low, high))

    def summary(self):
        return {"identity_values": sum(map(len, self.identities.values())),
                "reviewed_examples": len(self.reviewed_examples),
                "safe_values": len(self.safe), "public_handles": len(self.logins),
                "engines": list(self.engines), "sources": self.sources}


def policy_revision(policy):
    """Private shared action-plan binding, including content-bound review changes."""
    values = {name: getattr(policy, name) for name in
              ("identities", "safe", "logins", "engines", "gaps", "sources", "review_revision", "reviewed_examples")}
    values["exclusions"] = [str(path) for path in policy.exclude_paths]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _scope(repo, exclusions):
    """Check requested read scope before Git identity or material access, allowing source scans."""
    path = Path(os.path.abspath(Path(repo).expanduser()))
    try:
        if any(linked(part) for part in (path, *path.parents)):
            raise SettingsError("scan roots must not traverse filesystem links")
        if excluded(path, exclusions, contains=True):
            raise SettingsError("requested repository or a subtree is excluded; no scan was started")
    except OSError:
        raise SettingsError("scan scope could not be checked safely") from None


def _values(policy, path, label, *, explicit):
    """Read one chosen list without following links; inaccessible inputs become coverage gaps."""
    try:
        path = Path(os.path.abspath(Path(path).expanduser()))
        if any(linked(part) for part in (path, *path.parents)):
            raise OSError("linked input")
        if excluded(path, policy.exclude_paths):
            raise OSError("excluded input")
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        policy.sources[label] = "missing-explicit" if explicit else "not-configured"
        if explicit:
            policy.gaps.append({"where": label, "reason": "explicit policy file does not exist"})
        return []
    except (OSError, UnicodeError):
        policy.sources[label] = "unreadable"
        policy.gaps.append({"where": label, "reason": "policy file could not be read safely"})
        return []
    values = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    policy.sources[label] = {"loaded_values": len(values)}
    return values


def load_policy(repo: Path, *, home=None, settings: ResolvedSettings | None = None,
                legacy_policy=False, never_file=None, safe_file=None, safe=(), login=()):
    """Load one effective policy; malformed common settings never yield legacy/default policy.

    A fresh unconfigured profile uses resolver defaults without writing. Known legacy state
    requires migration or explicit legacy_policy selection. Explicit files supplement common
    lists; in legacy mode they select the corresponding text sources. Missing/unreadable
    explicit files retain incomplete coverage. The caller-resolved seam reads no config files.
    """
    if settings is not None and (home is not None or legacy_policy):
        raise SettingsError("select resolved settings or a profile mode, not both")
    if not isinstance(legacy_policy, bool):
        raise SettingsError("legacy policy selection must be explicit")
    if settings is None:
        selected, home_source = select_home(home, component="security")
        try:
            target = checked_path(selected / SETTINGS_NAME)
        except (RuntimeIOError, OSError):
            raise SettingsError("security settings require unlinked storage outside the checkout") from None
        if legacy_policy:
            try:
                target.lstat()
            except FileNotFoundError:
                pass
            except OSError:
                raise SettingsError("security settings could not be checked") from None
            else:
                raise SettingsError("legacy policy mode cannot bypass an existing common settings file")
        else:
            settings = replace(resolve_settings("security", home=selected), home_source=home_source)
    elif not isinstance(settings, ResolvedSettings):
        raise SettingsError("security policy needs caller-resolved settings")

    if settings is not None:
        values = copy.deepcopy(settings.values["security"])
        exclusions = tuple(settings.values["scope"]["exclude_paths"])
        _part({"security": values})
        _policy_conflicts({"security": values})
    else:
        values, exclusions = {"never_publish": [], "safe_values": []}, ()
    if isinstance(safe, str) or isinstance(login, str):
        raise SettingsError("safe values and public handles must be lists, not scalar text")
    try:
        safe, login = list(safe), list(login)
    except TypeError:
        raise SettingsError("safe values and public handles must be lists") from None
    _part({"security": {"safe_values": [*safe, *login]}})
    _scope(repo, exclusions)
    policy = Policy(safe=[*values["safe_values"], *values.get("local_safe_values", ()), *safe],
                    logins=list(login), exclude_paths=exclusions,
                    engines=tuple(values.get("engines", ())))
    policy.identities["never-publish"] = list(dict.fromkeys(
        [*values["never_publish"], *values.get("local_never_publish", ())]))
    policy.sources["settings"] = "legacy-explicit" if legacy_policy else settings.summary()
    defaults = selected / "security" if legacy_policy else None
    for explicit, name, label in ((never_file, "never_publish.txt", "never-publish"),
                                   (safe_file, "safe.txt", "safe-list")):
        if explicit is None and not legacy_policy:
            policy.sources[label] = ({"saved_values": len(values["safe_values" if label == "safe-list" else "never_publish"])}
                                     if settings.configured else "not-configured")
            continue
        listed = _values(policy, Path(explicit) if explicit is not None else defaults / name,
                         label, explicit=explicit is not None)
        if label == "safe-list":
            policy.safe.extend(listed)
        else:
            policy.identities["never-publish"].extend(listed)
    if not legacy_policy:
        combined = {"never_publish": policy.identities["never-publish"], "safe_values": policy.safe}
        _part({"security": combined})
        _policy_conflicts({"security": combined})

    for key, label in (("user.email", "configured email"), ("user.name", "configured name")):
        result = run(["git", "-C", str(repo), "config", "--get", key], timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            value = result.stdout.strip()
            if key == "user.email":
                match = re.fullmatch(r"(?:\d+\+)?([^@]+)@users\.noreply\.github\.com", value, re.I)
                if match:
                    policy.logins.append(match[1])
                    policy.safe.append(value)
                else:
                    policy.identities[label] = [value]
            else:
                policy.identities[label] = [value]
        elif result.returncode not in (0, 1):
            policy.gaps.append({"where": key, "reason": "could not read effective Git configuration"})
        policy.sources[key] = "loaded" if result.returncode == 0 else "unavailable"
    for name in policy.identities.get("configured name", []):
        if any(name.lower() == item.lower() or re.fullmatch(re.escape(item) + r"@[A-Za-z0-9_-]+", name, re.I)
               for item in policy.logins):
            policy.safe.append(name)
    policy.identities["machine name"] = [socket.gethostname()]
    policy.identities["home-folder name"] = [Path.home().name]
    if not legacy_policy:
        _policy_conflicts({"security": {"never_publish": policy.identities["never-publish"],
                                        "safe_values": [*policy.safe, *policy.logins]}})
    policy.logins = sorted(set(policy.logins))
    policy.safe = sorted(set(policy.safe))
    from Special.security import _reviews
    try:
        review_home = settings.home if settings is not None else selected
        if excluded(_reviews.directory(review_home, repo), policy.exclude_paths, contains=True):
            policy.review_revision = "excluded"
        else:
            policy.reviewed_examples, policy.review_revision = _reviews.load(review_home, repo,
                                                                            configured=settings is not None and settings.configured)
    except (OSError, ValueError):
        policy.gaps.append({"where": "review records", "reason": "private example reviews could not be verified"})
        policy.review_revision = "unreadable"
    policy.sources["tailnet"] = "not-requested"
    policy.sources["online-organizations"] = "not-requested"
    return policy
