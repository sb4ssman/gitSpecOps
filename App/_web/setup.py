"""The web view's setup routes: enroll this machine and join a fleet from the app.

Why:          a person should set gitSpecOps up by touching the app, not a terminal. Each route
              calls the same headless step the commands use (Special/_sync/enrollment.py,
              Elaborate/_fleet/setup_state.py), so the page can do nothing a command cannot.
Reads:        the settings profile; folder names only where `find` is pointed, once approved.
May change:   this machine's libraries and presentation; the fleet key and transports. Never a
              repository.
Results:      JSON for the setup page.
Layer:        App: presence and presentation.
Status:       working

The same approval as the commands (Basic/_cli.py): looking for libraries, adding them, joining
and leaving a fleet first return their plan and its id, and change nothing; the page shows the
plan, and "Yes" sends it back with `apply` set to that id. A plan that changed in between is
refused and the new one returned. Removing one library and choosing how the app shows itself
are single explicit settings, made at once. The server around these routes
(App/_web/server.py) adds loopback, Host, Origin and per-run token checks.
"""
from __future__ import annotations

from pathlib import Path

ACTIONS = ("find", "add", "remove", "presentation", "join", "leave")
PLANNED = ("find", "add", "join", "leave")
QUESTIONS = {"find": "Look in these folders?", "add": "Enroll these library folders?",
             "join": "Join with these choices?", "leave": "Leave the fleet?"}


class SetupRoutes:
    def __init__(self, home=None, config_dir=None, *, on_change=None):
        self.home, self.config_dir = home, config_dir
        self.on_change = on_change or (lambda state: None)

    def state(self, readiness: bool = False) -> dict:
        from Elaborate._fleet.setup_state import setup_state

        return setup_state(self.home, self.config_dir, readiness=readiness)

    def plan(self, action: str, payload: dict, paths: list[str]) -> tuple[dict, dict]:
        """(what the page shows, what the id covers). A fleet key is covered but never shown."""
        from Special._sync import enrollment

        if action == "find":
            starts = enrollment.whole_machine_starts() if payload.get("whole_machine") else paths
            if not starts:
                raise ValueError("say where to look, or choose the whole machine")
            shown = {"action": "find", "look_in": [str(start) for start in starts],
                     "depth": int(payload.get("depth") or 4),
                     "reads": "folder names only: no file contents, no Git; nothing is enrolled by looking"}
            return shown, shown
        if action == "add":
            if not paths:
                raise ValueError("name at least one library folder")
            shown = {"action": "add", "libraries": [str(Path(path).expanduser().resolve()) for path in paths],
                     "notice": enrollment.inventory_notice(paths)}
            return shown, shown
        if action == "join":
            key = payload.get("key") or ""
            shown = {"action": "join", "fleet": "the fleet of that key" if key else "a new fleet",
                     "folder": payload.get("folder") or None, "repo": payload.get("repo") or None,
                     "create_repo": bool(payload.get("create_repo")), "tailnet": bool(payload.get("tailnet")),
                     "share_names": payload.get("share_names")}
            return shown, {**shown, "key": key}
        state = self.state()
        shown = {"action": "leave", "stop_sharing_through": sorted(((state.get("fleet") or {}).get("transports"))
                                                                   or [])}
        return shown, shown

    def act(self, action: str, payload: dict) -> dict:
        from Basic._cli import plan_id
        from Elaborate._fleet import setup_state as fleet_setup
        from Special._sync import enrollment

        if action not in ACTIONS:
            raise ValueError("unknown setup action")
        paths = [str(item) for item in payload.get("paths") or [] if str(item).strip()]
        if action in PLANNED:
            shown, covered = self.plan(action, payload, paths)
            identity = plan_id(covered)
            given = payload.get("apply")
            if given != identity:
                return {"plan": shown, "plan_id": identity, "applied": False, "question": QUESTIONS[action],
                        **({"notice": "The plan changed since you saw it; nothing was done. Here is the "
                                      "plan as it is now."} if given else {})}
        if action == "find":
            return {"found": enrollment.find_libraries(shown["look_in"], max_depth=shown["depth"])[:40],
                    "looked_in": shown["look_in"], "applied": True}
        if action == "add":
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
        return {"state": state, "notice": NOTICES.get(action, ""), "applied": True}


NOTICES = {
    "add": "Saved. The app inventories new libraries when it (re)starts the peer.",
    "remove": "Removed. The app applies this when it restarts the peer.",
    "join": "Joined. The app shares through the chosen ways when it restarts the peer.",
    "leave": "Left the fleet. This machine keeps its libraries and web view.",
    "presentation": "Saved. Takes effect when the app restarts.",
}
