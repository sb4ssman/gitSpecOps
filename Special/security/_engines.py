"""Optional credential engines over material already selected by the built-in reader.

EngineBatch accepts bounded text fragments and appends normalized findings/coverage to a
Report. No pip dependency, shell, download, report file or provider verification is involved.
Gitleaks 8 and Betterleaks 1 use JSON reports on stdout; TruffleHog 3 uses JSON lines. Other
CLI/report versions fail incomplete rather than falling back. Native binary acceptance is
separate from the adapter's offline protocol tests.

Input goes through Basic.stream's stdin pipe, never argv or a temporary source file. A fresh
empty working directory prevents repository-local config/ignore files changing the checks.
Custom configs/live validation are not enabled by this adapter. Returned secrets must map
back to the selected fragments; unfamiliar/transformed results become explicit coverage gaps.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from Basic._run import CommandFailed, stream
from Special._settings import SECURITY_ENGINES, SettingsError
from Special.security._findings import Finding

BATCH_CHARACTERS = 1024 * 1024
BATCH_FRAGMENTS = 256
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
ENGINE_TIMEOUT = 120


def selected_engines(values):
    """Normalize an explicit selection; none is represented by the empty tuple."""
    if not isinstance(values, (list, tuple)):
        raise SettingsError("engine selection must be a list")
    values = tuple(values)
    if (any(not isinstance(value, str) for value in values) or
            len(set(values)) != len(values) or not set(values) <= set(SECURITY_ENGINES)):
        raise SettingsError("select distinct supported engines or none")
    return values


def command(engine, executable):
    """Fixed offline stdin protocol; no target path, secret or user-supplied shell options."""
    if engine not in SECURITY_ENGINES:
        raise SettingsError("unsupported credential engine")
    if engine == "trufflehog":
        return [str(executable), "stdin", "--json", "--no-verification", "--no-update",
                "--fail-on-scan-errors", "--log-level=-1"]
    args = [str(executable), "stdin", "--report-format=json", "--report-path=-", "--exit-code=0",
            "--no-banner", "--log-level=error", "--ignore-gitleaks-allow"]
    if engine == "betterleaks":
        args.append("--validation=false")
    return args


def _records(engine, payload):
    """Parse only documented finding shapes; never publish raw engine output/errors."""
    text = payload.decode("utf-8", errors="strict")
    if engine == "trufflehog":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        fields = ("Raw", "DetectorName")
    else:
        rows = json.loads(text)
        rows = [] if rows is None else rows
        fields = ("Secret", "RuleID")
    if not isinstance(rows, list):
        raise ValueError("unsupported engine report")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("unsupported engine finding")
        value, rule = (row.get(key) for key in fields)
        if (not isinstance(value, str) or not value or not isinstance(rule, str) or
                re.fullmatch(r"[A-Za-z0-9_. /-]{1,120}", rule) is None):
            raise ValueError("unsupported engine finding")
        result.append((value, rule))
    return result


def _execute(engine, executable, data):
    # Empty overrides suppress ambient scanner configs and Betterleaks opt-in validation.
    # Auth remains with the user's CLIs; no credentials are copied into reports or argv.
    environment = {"GITLEAKS_CONFIG": "", "GITLEAKS_CONFIG_TOML": "",
                   "BETTERLEAKS_CONFIG": "", "BETTERLEAKS_CONFIG_TOML": "",
                   "BETTERLEAKS_VALIDATE": "false", "BETTERLEAKS_ANALYZE": "false"}
    with tempfile.TemporaryDirectory(prefix="gitso-engine-") as directory:
        oversized = False
        with stream(command(engine, executable), timeout=ENGINE_TIMEOUT, cwd=directory,
                    env=environment, feed=(data,)) as process:
            payload = process.stdout.read(MAX_OUTPUT_BYTES + 1)
            if len(payload) > MAX_OUTPUT_BYTES:
                process.stop()
                oversized = True
        # Basic.stream.stop() deliberately ends a stream without a new child-process error;
        # enforce our own limit after its context exits, even if the prefix is valid JSON.
        if oversized:
            raise ValueError("engine output exceeds limit")
    return _records(engine, payload)


class EngineBatch:
    """Bounded selected-material scan; failed engines stay incomplete for this invocation.

    `executables` is an optional trusted caller's local binding, not portable policy. Otherwise
    resolve the selected engine on PATH. Never search/download an unselected engine. Findings
    are candidates, not proof a credential is live; existing safe-value policy still applies.
    """

    def __init__(self, report, policy, engines=(), *, executables=None):
        self.report, self.policy = report, policy
        self.fragments, self.characters = [], 0
        self.executables = dict(executables or {})
        if set(self.executables) - set(SECURITY_ENGINES):
            raise SettingsError("unsupported engine executable binding")
        self.states = {name: "pending" for name in selected_engines(engines)}
        self.report.engines = self.states
        self.seen = set()

    def add(self, text, where, object_id=""):
        """Queue a fragment already admitted by the material/policy reader; no disk writes."""
        if not self.states or not any(value != "incomplete" for value in self.states.values()):
            return
        if self.fragments and (self.characters + len(text) > BATCH_CHARACTERS or
                               len(self.fragments) >= BATCH_FRAGMENTS):
            self.flush()
        self.fragments.append((text, where, object_id))
        self.characters += len(text)

    def flush(self):
        """Run selected engines, map results to source fragments and discard transient text."""
        fragments, self.fragments = self.fragments, []
        self.characters = 0
        if not fragments:
            return
        data = ("\n".join(text for text, _, _ in fragments) + "\n").encode("utf-8")
        for engine, state in self.states.items():
            if state == "incomplete":
                continue
            try:
                executable = self.executables.get(engine) or shutil.which(engine)
                if executable is None:
                    raise ValueError("selected engine unavailable")
                rows = _execute(engine, str(Path(executable).absolute()), data)
                for value, rule in rows:
                    mapped = False
                    for text, where, object_id in fragments:
                        for match in re.finditer(re.escape(value), text):
                            mapped = True
                            if self.policy.allowed(text, *match.span()):
                                continue
                            line = text.count("\n", 0, match.start()) + 1
                            key = (engine, rule, value, where, object_id, line)
                            if key not in self.seen:
                                self.seen.add(key)
                                self.report.findings.append(Finding(
                                    engine + "/" + rule, "candidate", value, where, object_id, line))
                    if not mapped:
                        raise ValueError("engine result cannot be mapped to selected material")
                self.states[engine] = "checked"
            except (CommandFailed, OSError, UnicodeError, ValueError):
                self.states[engine] = "incomplete"
                self.report.gap(engine, "selected engine unavailable, failed or returned unsupported output; no clean result")

    def finish(self):
        """Complete remaining fragments. Empty material still checks the selected protocol."""
        if not self.fragments and any(value == "pending" for value in self.states.values()):
            self.fragments.append(("", "empty material", ""))
        self.flush()
        self.seen.clear()
