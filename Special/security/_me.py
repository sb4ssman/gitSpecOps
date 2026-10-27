"""One explicit identity/watch/safe policy. Reads sources; never creates configuration."""
from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field
from pathlib import Path

from Basic._paths import config_home
from Basic._run import run


@dataclass
class Policy:
    identities: dict[str, list[str]] = field(default_factory=dict)
    safe: list[str] = field(default_factory=list)
    logins: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)

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
                "safe_values": len(self.safe), "public_handles": len(self.logins),
                "sources": self.sources}


def load_policy(repo: Path, *, never_file=None, safe_file=None, safe=(), login=()):
    policy = Policy(safe=list(safe), logins=list(login))
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
    defaults = config_home() / "security"
    for explicit, default, label in ((never_file, defaults / "never_publish.txt", "never-publish"),
                                      (safe_file, defaults / "safe.txt", "safe-list")):
        path = Path(explicit) if explicit is not None else default
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            policy.sources[label] = "missing-explicit" if explicit is not None else "not-configured"
            if explicit is not None:
                policy.gaps.append({"where": label, "reason": "explicit policy file does not exist"})
            continue
        except (OSError, UnicodeError):
            policy.sources[label] = "unreadable"
            policy.gaps.append({"where": label, "reason": "policy file could not be read"})
            continue
        values = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        policy.sources[label] = {"loaded_values": len(values)}
        if label == "safe-list":
            policy.safe.extend(values)
        else:
            policy.identities[label] = values
    policy.logins = sorted(set(policy.logins))
    policy.safe = sorted(set(policy.safe))
    policy.sources["tailnet"] = "not-requested"
    policy.sources["online-organizations"] = "not-requested"
    return policy
