"""What the tray shows, decided without Qt: state from the display contract, and why a start failed.

Why:          the tray is a skin. Every number and colour comes from the peer's
              `gitspecops.fleet.display` document; this module only reads it. Keeping it free of
              Qt makes the tray's behavior testable on any machine, with or without a display.
Reads:        one display document, or one error line the peer printed.
May change:   nothing.
Results:      a Snapshot for the tray to render; a fixed, specific failure message.
Layer:        App: presence and presentation.
Status:       working
"""
from __future__ import annotations

from dataclasses import dataclass

from App._mark.geometry import STATES as MARK_STATES

CONTRACT_NAME = "gitspecops.fleet.display"
CONTRACT_VERSION = 1
POLL_SECONDS = 5.0

#: Icon colour per state, as RGB. State is reported by the peer, never inferred here.
STATE_COLOURS = {
    "starting": (150, 150, 150),
    "ok": (90, 190, 90),
    "attention": (245, 180, 60),
    "error": (225, 60, 60),
}

SETUP_HINT = "Enroll it: python Special/enroll_machine.py add <library folder>."
#: (what the peer said, what the person reads). The peer's own text can carry paths, so it is
#: never shown; a known cause gets a fixed sentence, anything else the generic one.
KNOWN_FAILURES = (
    (("not enrolled", "no saved configuration", "no app enrollment", "run setup first"),
     "This machine is not set up yet. " + SETUP_HINT),
    (("already running",),
     "Another gitSpecOps peer is already running for this profile."),
    (("address already in use", "only one usage of each socket address", "10048", "errno 98"),
     "The dashboard port is in use by another program. Choose another port with "
     "Elaborate/setup_fleet.py peer --configure-only."),
    (("unsupported fleet app configuration", "invalid", " must ", "older format"),
     "The saved fleet settings are not valid. Elaborate/doctor.py shows them; "
     "Elaborate/setup_fleet.py fixes them."),
)
GENERIC_FAILURE = ("gitSpecOps stopped unexpectedly. Run Elaborate/peer.py in a terminal to "
                   "see why.")


@dataclass
class Snapshot:
    state: str = "starting"
    text: str = "Starting the fleet peer..."
    url: str = ""
    ready: bool = False
    repositories: int = 0
    attention: int = 0
    machines: int = 0
    stale: int = 0
    #: The mark's two signals (App/_mark): this machine, and the fleet condensed to one state.
    machine: str = "starting"
    fleet: str = "none"
    machine_text: str = "starting"
    fleet_text: str = "not known yet"
    #: What the peer is doing right now (the display document's `activity`).
    activity: str = "starting"
    activity_text: str = "starting"

    @property
    def working(self) -> bool:
        """The mark animates while the app is working something out or doing something."""
        return self.machine == "starting" or self.activity not in ("idle", "")

    def tooltip(self) -> str:
        """Windows cuts tray tooltips at 127 characters: short lines, the menu has the rest. While
        working, the first line says what it is doing."""
        head = f"gitSpecOps: {self.activity_text}" if self.working else "gitSpecOps"
        text = f"{head}\nThis machine: {self.machine_text}\nFleet: {self.fleet_text}"
        return text if len(text) <= 127 else text[:126] + "…"


def snapshot_from_display(document: dict, url: str, label: str) -> Snapshot:
    """Translate one display document into tray state. An unsupported contract version is an
    error, not a guess: the version field exists so a skin stops instead of misreading."""
    snapshot = Snapshot(url=url, ready=True)
    contract = document.get("contract") or {}
    if contract.get("name") != CONTRACT_NAME or contract.get("version") != CONTRACT_VERSION:
        snapshot.state = "error"
        snapshot.text = (f"{label}: dashboard contract {contract.get('name')} "
                         f"v{contract.get('version')} is not supported by this tray "
                         f"(expects v{CONTRACT_VERSION}).")
        return snapshot
    summary = document.get("summary") or {}
    snapshot.repositories = int(summary.get("repositories", 0))
    snapshot.attention = int(summary.get("attention", 0))
    snapshot.machines = int(summary.get("machines", 0))
    snapshot.stale = int(summary.get("stale_machines", 0))
    snapshot.state = "attention" if snapshot.attention else "ok"
    detail = (f"{snapshot.attention} of {snapshot.repositories} repositories need attention"
              if snapshot.attention else f"{snapshot.repositories} repositories, all clear")
    stale = f", {snapshot.stale} machine(s) stale" if snapshot.stale else ""
    snapshot.text = f"{label}: {detail}{stale}"
    signals = document.get("mark") or {}
    machine, fleet = signals.get("machine") or {}, signals.get("fleet") or {}
    if machine.get("state") in MARK_STATES and fleet.get("state") in MARK_STATES:
        snapshot.machine, snapshot.machine_text = machine["state"], str(machine.get("text") or "")
        snapshot.fleet, snapshot.fleet_text = fleet["state"], str(fleet.get("text") or "")
    else:  # a peer from before the mark: the overall state, no fleet signal
        snapshot.machine, snapshot.machine_text = snapshot.state, detail
        snapshot.fleet, snapshot.fleet_text = "none", "not reported by this peer"
    activity = document.get("activity") or {}
    snapshot.activity = str(activity.get("phase") or "idle")
    snapshot.activity_text = str(activity.get("text") or "watching for changes")
    return snapshot


def setup_snapshot(url: str) -> Snapshot:
    """An un-enrolled machine: not an error, an invitation."""
    return Snapshot(state="attention", url=url, ready=True,
                    text="gitSpecOps is not set up yet. Double-click to choose your library folders.",
                    machine="attention", machine_text="not set up yet; double-click to start",
                    fleet="none", fleet_text="not in a fleet",
                    activity="idle", activity_text="waiting for you to choose a library")


def error_snapshot(url: str, label: str) -> Snapshot:
    return Snapshot(state="error", url=url, ready=bool(url),
                    text=f"{label}: cannot read the fleet dashboard right now.",
                    machine="error", machine_text="cannot read the fleet dashboard right now",
                    fleet="starting", fleet_text="not known right now",
                    activity="idle", activity_text="cannot read the fleet dashboard")


def failure_reason(error_line: str | None) -> str:
    """A start that failed says why for the known causes, and nothing raw ever."""
    text = (error_line or "").casefold()
    for needles, message in KNOWN_FAILURES:
        if any(needle in text for needle in needles):
            return message
    return GENERIC_FAILURE


def stopped_snapshot(reason: str) -> Snapshot:
    """`reason` is already one of the fixed sentences above, never the peer's own text."""
    return Snapshot(state="error", text=f"gitSpecOps is not running: {reason}",
                    machine="error", machine_text="not running; open the menu to see why",
                    fleet="starting", fleet_text="not known while stopped",
                    activity="idle", activity_text="stopped")
