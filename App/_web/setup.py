"""The web view's setup routes: enroll this machine and join a fleet from the app.

Why:          a person should set gitSpecOps up by touching the app, not a terminal. Each route
              calls the same headless step the commands use (Special/_sync/enrollment.py,
              Elaborate/_fleet/setup_state.py), so the page can do nothing a command cannot.
Reads:        the settings profile; folder names only where `find` is pointed, after LOOK.
May change:   this machine's libraries and presentation (after SCAN for new libraries); the
              fleet key and transports (after JOIN or LEAVE). Never a repository.
Results:      JSON for the setup page.
Layer:        App: presence and presentation.
Status:       working

Every change needs the typed word the terminal asks for: LOOK, SCAN, JOIN, LEAVE. The server
around these routes (App/_web/server.py) adds loopback, Host, Origin and per-run token checks.
"""
from __future__ import annotations

WORDS = {"find": "LOOK", "add": "SCAN", "join": "JOIN", "leave": "LEAVE"}
ACTIONS = ("find", "add", "remove", "presentation", "join", "leave")


class SetupRoutes:
    def __init__(self, home=None, config_dir=None, *, on_change=None):
        self.home, self.config_dir = home, config_dir
        self.on_change = on_change or (lambda state: None)

    def state(self, readiness: bool = False) -> dict:
        from Elaborate._fleet.setup_state import setup_state

        return setup_state(self.home, self.config_dir, readiness=readiness)

    def act(self, action: str, payload: dict) -> dict:
        from Elaborate._fleet import setup_state as fleet_setup
        from Special._sync import enrollment

        if action not in ACTIONS:
            raise ValueError("unknown setup action")
        word = WORDS.get(action)
        if word and payload.get("confirm") != word:
            raise ValueError(f"type {word} to allow this")
        paths = [str(item) for item in payload.get("paths") or [] if str(item).strip()]
        if action == "find":
            starts = enrollment.whole_machine_starts() if payload.get("whole_machine") else paths
            if not starts:
                raise ValueError("say where to look, or choose the whole machine")
            return {"found": enrollment.find_libraries(starts, max_depth=int(payload.get("depth") or 4))[:40],
                    "looked_in": [str(start) for start in starts]}
        if action == "add":
            if not paths:
                raise ValueError("name at least one library folder")
            enrollment.add_libraries(paths, home=self.home)
        elif action == "remove":
            enrollment.remove_library(payload.get("path") or "", home=self.home)
        elif action == "presentation":
            enrollment.set_presentation(face=payload.get("face"), web=payload.get("web"), home=self.home)
        elif action == "join":
            fleet_setup.join_fleet(self.home, self.config_dir, key=payload.get("key") or None,
                                   folder=payload.get("folder") or None, tailnet=bool(payload.get("tailnet")),
                                   repo=payload.get("repo") or None, create_repo=bool(payload.get("create_repo")),
                                   share_names=payload.get("share_names"))
        elif action == "leave":
            fleet_setup.leave_fleet(self.home, self.config_dir)
        state = self.state()
        self.on_change(state)
        return {"state": state, "notice": NOTICES.get(action, "")}


NOTICES = {
    "add": "Saved. The app inventories new libraries when it (re)starts the peer.",
    "remove": "Removed. The app applies this when it restarts the peer.",
    "join": "Joined. The app shares through the chosen ways when it restarts the peer.",
    "leave": "Left the fleet. This machine keeps its libraries and web view.",
    "presentation": "Saved. Takes effect when the app restarts.",
}
