"""The host seam: providers register where they live, and nobody has to ask them to.

Before phase 2, the GitHub provider only existed once some caller remembered to import a
tool-side facade (`remote_provider.py`, reached from Sync Suggester via `_register_providers()`,
which also put another tool's folder on `sys.path`). Forgetting meant "no providers", which
silently degraded every lookup to host-agnostic. Offline: nothing here runs `gh`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


# A fresh interpreter proves registration needs no help from any caller.
probe = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, sys.argv[1]);"
     "from Basic._providers._registry import provider_for;"
     "p = provider_for('https://github.com/example/work.git');"
     "print(type(p).__name__)", str(ROOT)],
    capture_output=True, text=True, timeout=60)
check("fresh process: github.com resolves with no registration call",
      probe.returncode == 0 and probe.stdout.strip() == "GitHubProvider")

from Basic._providers import _registry  # noqa: E402
from Basic._providers.github import GhError, GitHubProvider  # noqa: E402

check("github.com is registered", "github.com" in _registry.registered_hosts())
check("ssh remote resolves", isinstance(_registry.provider_for("git@github.com:example/work.git"),
                                        GitHubProvider))
check("subdomain resolves", isinstance(_registry.provider_for_host("api.github.com"),
                                       GitHubProvider))
check("unknown host degrades to None", _registry.provider_for("https://example.invalid/a/b") is None)
check("no host degrades to None", _registry.provider_for(None) is None
      and _registry.provider_for_host("") is None)
check("a lookalike host does not match", _registry.provider_for_host("evilgithub.com") is None)
check("GhError is a RuntimeError (callers catch it as one)", issubclass(GhError, RuntimeError))


class FakeProvider:
    name = "fake"


_registry.register_provider("git.example.test", FakeProvider)
check("a second host is one register_provider() call",
      isinstance(_registry.provider_for("https://git.example.test/team/repo"), FakeProvider))

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-PROVIDER-TESTS-PASS")
