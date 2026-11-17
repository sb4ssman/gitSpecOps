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

ACTIONS = ("find", "add", "remove", "presentation", "join", "leave", "open-folder",
           "settings", "connections", "fetch", "sign-in", "fleets", "show-key", "shared-answer", "seal",
           "name-fleet", "baskets", "tasks")
PLANNED = ("find", "add", "join", "leave", "connections", "show-key", "seal")
QUESTIONS = {"find": "Look in these folders?", "add": "Enroll these library folders?",
             "join": "Join with these choices?", "leave": "Leave the fleet?",
             "connections": "Connect this way?",
             "show-key": "Show the fleet key on this page? Anyone who has it can join your fleet.",
             "seal": "Change how protected values go through the synced folder?"}
POLL_CHOICES = (60, 300, 1800)       # the same choices setup offers for Tailscale
FETCH_CHOICES = (0, 60, 360, 1440)   # never, hourly, every 6 hours, daily


class SetupRoutes:
    def __init__(self, home=None, config_dir=None, *, on_change=None):
        self.home, self.config_dir = home, config_dir
        self.on_change = on_change or (lambda state: None)

    def state(self, readiness: bool = False) -> dict:
        from Elaborate._fleet.setup_state import setup_state

        return setup_state(self.home, self.config_dir, readiness=readiness)

    def settings(self) -> dict:
        """Every setting the Settings tab can change, as it is now. Never the fleet key."""
        from Elaborate._fleet import autostart
        state = self.state()
        config = self._config()
        transports = ((state.get("fleet") or {}).get("transports")) or {}
        tailnet, folder, repo = (transports.get(name) for name in ("tailnet", "folder", "repo"))
        try:
            sign_in = autostart.status()
        except (OSError, ValueError) as exc:
            sign_in = {"supported": False, "enabled": False, "reason": str(exc)}
        machine = state.get("machine") or {}
        # Where your own phone or other computers open this page: the tailnet view's address
        # (numeric on purpose: the view refuses names, a guard against DNS tricks). 2026-11-17.
        remote = None
        if (machine.get("presentation") or {}).get("web") == "tailnet":
            try:
                from App._web.remote import DEFAULT_REMOTE_PORT
                from Elaborate._fleet.net import local_identity
                remote = f"http://{local_identity()['ip']}:{int((config or {}).get('remote_port') or DEFAULT_REMOTE_PORT)}/"
            except (OSError, ValueError, KeyError):
                remote = None
        return {
            "remote_view": remote,
            "enrolled": state.get("machine") is not None,
            "libraries": machine.get("libraries", []),
            "presentation": machine.get("presentation"),
            "baskets": {scope: (config or {}).get("baskets", {}).get(scope) for scope in ("observe", "publish", "capture")},
            "fleet_id": (state.get("fleet") or {}).get("fleet_id"),
            "fleet_name": (state.get("fleet") or {}).get("name"),
            "connections": {
                "tailnet": {"on": bool(tailnet), "seconds": int((tailnet or {}).get("seconds") or 300),
                            "names": (tailnet or {}).get("names", True), "choices": list(POLL_CHOICES)},
                "folder": {"on": bool(folder), "path": (folder or {}).get("path", ""),
                           "names": (folder or {}).get("names", False)},
                "repo": {"on": bool(repo), "name": (repo or {}).get("name", ""),
                         "names": (repo or {}).get("names", False)}},
            "fetch_minutes": int((config or {}).get("fetch_minutes") or 0),
            "fetch_choices": list(FETCH_CHOICES),
            "shared": self._shared_state(config, bool(folder)),
            "sign_in": {"supported": bool(sign_in.get("supported")), "enabled": bool(sign_in.get("enabled")),
                        "elsewhere": sign_in.get("elsewhere"), "reason": sign_in.get("reason")},
        }

    def _shared(self, config):
        """This machine's side of the shared protected values (Elaborate/_fleet/shared_policy.py)."""
        from Elaborate._fleet.shared_policy import SharedPolicy
        from Special._settings.fleet import fleet_directory
        from Special._sync.manifest import fleet_id_for
        return SharedPolicy(self.home, fleet_directory(self.config_dir, home=self.home),
                            fleet_id=fleet_id_for(config["fleet_secret"]), machine_id=config["machine_id"],
                            label=config["label"])

    def _shared_state(self, config, has_folder: bool) -> dict:
        from Elaborate._fleet.sealed import venv_has
        questions = []
        if config is not None:
            try:
                questions = self._shared(config).questions()
            except (OSError, ValueError):
                questions = []
        return {"questions": questions, "sealed": bool((config or {}).get("seal_settings")),
                "encryption_installed": venv_has("cryptography"), "has_folder": has_folder}

    def _config(self):
        from Special._settings.fleet import load_fleet_settings
        snapshot = load_fleet_settings(self.home)
        return snapshot.config("app") if snapshot is not None else None

    def _connections_plan(self, payload: dict) -> dict:
        """What a connections change does, in words, from what is set now."""
        current = self.settings()
        now = current["connections"]
        tailnet = bool(payload.get("tailnet"))
        seconds = int(payload.get("tailnet_seconds") or now["tailnet"]["seconds"])
        if seconds not in POLL_CHOICES:
            raise ValueError("choose every 1, 5 or 30 minutes")
        folder = str(payload.get("folder") or "").strip()
        repo = str(payload.get("repo") or "").strip()
        names = {key: bool(value) for key, value in (payload.get("names") or {}).items()
                 if key in ("tailnet", "folder", "repo")}
        changes = []
        if tailnet != now["tailnet"]["on"]:
            changes.append("Tailscale: " + ("on" if tailnet else "off"))
        if tailnet and seconds != now["tailnet"]["seconds"]:
            changes.append(f"Tailscale: ask every {seconds // 60} minute{'s' if seconds != 60 else ''}")
        if folder != (now["folder"]["path"] if now["folder"]["on"] else ""):
            changes.append(f"synced folder: {folder}" if folder else "synced folder: off")
        if repo != (now["repo"]["name"] if now["repo"]["on"] else ""):
            changes.append(f"state repository: {repo}" if repo else "state repository: off")
        for key, value in names.items():
            if (tailnet if key == "tailnet" else folder if key == "folder" else repo) and value != now[key]["names"]:
                changes.append(f"{key}: {'with' if value else 'without'} repository names")
        starts = not current["fleet_id"] and bool(tailnet or folder or repo)
        name = " ".join(str(payload.get("fleet_name") or "").split())[:60] or "My fleet"
        if starts:
            changes.insert(0, f"start the fleet {name} with this machine (your other machines join it "
                              "by that name on Tailscale)")
        elif current["fleet_id"] and not (tailnet or folder or repo):
            changes.append("no connection left: this machine leaves the fleet (it keeps its libraries)")
        return {"action": "connections", "changes": changes or ["nothing changes"],
                "tailnet": tailnet, "tailnet_seconds": seconds, "folder": folder or None,
                "repo": repo or None, "create_repo": bool(payload.get("create_repo")), "names": names,
                "starts_fleet": starts, "fleet_name": name if starts else None}

    def _apply_connections(self, plan: dict) -> None:
        from Elaborate._fleet import setup_state as fleet_setup
        from Elaborate._fleet.cli import load_saved
        from Special._settings.fleet import fleet_directory
        if not (plan["tailnet"] or plan["folder"] or plan["repo"]):
            fleet_setup.leave_fleet(self.home, self.config_dir)
            return
        if plan["starts_fleet"]:
            fleet_setup.join_fleet(self.home, self.config_dir, folder=plan["folder"], tailnet=plan["tailnet"],
                                   repo=plan["repo"], create_repo=plan["create_repo"], names=plan["names"],
                                   tailnet_seconds=plan["tailnet_seconds"], name=plan["fleet_name"])
            return
        directory = fleet_directory(self.config_dir, home=self.home)
        config = load_saved(directory, home=self.home)
        now = config.get("transports") or {}
        fleet_setup.apply_transports(
            config,
            folder=plan["folder"] if plan["folder"] != (now.get("folder") or {}).get("path") else None,
            clear_folder=not plan["folder"] and "folder" in now,
            repo=plan["repo"] if plan["repo"] != (now.get("repo") or {}).get("name") else None,
            create_repo=plan["create_repo"], clear_repo=not plan["repo"] and "repo" in now,
            tailnet=plan["tailnet"] and "tailnet" not in now,
            clear_tailnet=not plan["tailnet"] and "tailnet" in now,
            tailnet_seconds=plan["tailnet_seconds"] if plan["tailnet"] else None,
            names=plan["names"], directory=directory, home=self.home)

    def _fleets(self) -> list[dict]:
        """The fleets your machines on this tailnet are in, by name (setup_state.fleets_on_tailnet)."""
        from Elaborate._fleet.setup_state import fleets_on_tailnet
        return fleets_on_tailnet()

    def _key_from_fleet(self, fleet_id: str) -> tuple[str, dict | None]:
        """The key and name, handed over by a running machine of that fleet; it checks who asks."""
        from Elaborate._fleet.setup_state import key_from_fleet
        return key_from_fleet(fleet_id)

    def plan(self, action: str, payload: dict, paths: list[str]) -> tuple[dict, dict]:
        """(what the page shows, what the id covers). A fleet key is covered but never shown."""
        from Special._sync import enrollment

        if action == "connections":
            shown = self._connections_plan(payload)
            return shown, shown
        if action == "show-key":
            shown = {"action": "show-key", "shows": "this machine's fleet key, on this page only"}
            return shown, shown
        if action == "seal":
            from Elaborate._fleet.sealed import REQUIREMENT, venv_has
            enabled = bool(payload.get("enabled"))
            install = enabled and not venv_has("cryptography")
            changes = ([f"install {REQUIREMENT} into this folder's .venv (one package, nothing else changes)"]
                       if install else [])
            changes.append("share protected values through the synced folder, sealed with a key from the "
                           "fleet key" if enabled else "stop sharing protected values through the synced "
                           "folder (Tailscale still carries them)")
            shown = {"action": "seal", "changes": changes, "enabled": enabled, "install": install}
            return shown, shown

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
            via = str(payload.get("fleet_id") or "")
            label = str(payload.get("fleet_label") or "")[:60]
            shown = {"action": "join", "fleet": f"{label or 'the fleet'} (a machine in it hands over what is needed)" if via
                     else "the fleet of that key" if key else "a new fleet",
                     "tailnet_seconds": payload.get("tailnet_seconds"),
                     "folder": payload.get("folder") or None, "repo": payload.get("repo") or None,
                     "create_repo": bool(payload.get("create_repo")), "tailnet": bool(payload.get("tailnet")),
                     "share_names": payload.get("share_names")}
            return shown, {**shown, "key": key, "via": via}
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
        if action == "open-folder":
            # The settings folder in the system's file manager. The page never receives the path.
            from Special._settings.fleet import fleet_home
            open_folder(fleet_home(self.home))
            return {"applied": True, "notice": "Opened your settings folder."}
        if action == "shared-answer":
            config = self._config()
            if config is None:
                raise ValueError("this machine is not enrolled")
            answered = self._shared(config).answer(str(payload.get("id") or ""), bool(payload.get("accept")))
            return {**answered, "applied": True, "settings": self.settings(),
                    "notice": "Changed here too." if answered["accepted"] else "Kept as it is here; not asked again."}
        if action == "seal" and shown.get("install"):
            from Elaborate._fleet import sealed
            sealed.install()
        if action == "seal":
            enrollment.set_seal_settings(bool(shown["enabled"]), home=self.home)
        if action == "settings":
            return {"settings": self.settings(), "applied": True}
        if action == "fleets":
            return {"fleets": self._fleets(), "applied": True}
        if action == "tasks":
            # The task log (Elaborate/_fleet/requests.py): requests sent, applied, dismissed, and
            # local runs, newest first. Names and counts only.
            import json
            from Special._settings.fleet import fleet_directory
            path = fleet_directory(self.config_dir, home=self.home) / "tasks.log"
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:] if path.exists() else []
            entries = []
            for line in reversed(lines):
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
            return {"applied": True, "tasks": entries}
        if action == "baskets":
            # Which repositories this machine observes, and which it publishes to the fleet.
            # Capture stays with the fleet baskets command and a confirmed recovery location.
            import Special._sync.baskets as baskets
            from Elaborate._fleet.cli import load_saved, save_saved
            from Elaborate._fleet.config import validate
            from Special._settings.fleet import fleet_directory
            scope = payload.get("scope")
            if scope not in ("observe", "publish"):
                raise ValueError("choose observe or publish")
            names = [n.strip() for n in str(payload.get("namespaces") or "").split(",") if n.strip()]
            selection = baskets.parse_selection(str(payload.get("mode") or ""), names or None)
            directory = fleet_directory(self.config_dir, home=self.home)
            config = load_saved(directory, home=self.home)
            config["baskets"] = baskets.validate_scopes({**(config.get("baskets") or baskets.DEFAULT_SCOPES),
                                                         scope: selection})
            validate(config)
            save_saved(directory, config, home=self.home)
            self.on_change(self.state())
            return {"applied": True, "settings": self.settings(),
                    "notice": f"Saved. The app applies the {scope} basket now."}
        if action == "name-fleet":
            named = fleet_setup.name_fleet(self.home, self.config_dir, name=str(payload.get("name") or ""))
            self.on_change(self.state())
            return {"applied": True, "settings": self.settings(),
                    "notice": f"The fleet is called {named['name']}; your other machines take the name on their next round."}
        if action == "show-key":
            config = self._config()
            if config is None:
                raise ValueError("this machine is not enrolled")
            return {"key": config["fleet_secret"], "applied": True,
                    "notice": "Copy it into setup, or the Settings tab, on the machine joining."}
        if action == "fetch":
            minutes = payload.get("minutes")
            if minutes not in FETCH_CHOICES:
                raise ValueError("choose never, every hour, every 6 hours or every day")
            enrollment.set_fetch_minutes(int(minutes), home=self.home)
        elif action == "sign-in":
            from Elaborate._fleet import autostart
            from App._launch import profile_arguments
            if payload.get("enabled"):
                autostart.enable(profile_arguments(self.config_dir, self.home),
                                 script=Path(__file__).resolve().parents[1] / "tray.py")
            else:
                autostart.disable()
            return {"settings": self.settings(), "applied": True,
                    "notice": "Starts at sign-in." if payload.get("enabled") else "Does not start at sign-in."}
        elif action == "connections":
            self._apply_connections(shown)
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
            named = None
            if covered.get("via"):
                key, named = self._key_from_fleet(covered["via"])
            else:
                key = payload.get("key") or None
            seconds = payload.get("tailnet_seconds")
            fleet_setup.join_fleet(self.home, self.config_dir, key=key,
                                   folder=payload.get("folder") or None, tailnet=bool(payload.get("tailnet")),
                                   repo=payload.get("repo") or None, create_repo=bool(payload.get("create_repo")),
                                   share_names=payload.get("share_names"),
                                   tailnet_seconds=int(seconds) if seconds in POLL_CHOICES else None,
                                   name=(named or {}).get("name"), named_at=(named or {}).get("at"))
        elif action == "leave":
            fleet_setup.leave_fleet(self.home, self.config_dir)
        state = self.state()
        self.on_change(state)
        return {"state": state, "notice": NOTICES.get(action, ""), "applied": True}


def open_folder(folder) -> None:
    """Open a folder in Explorer, Finder or the desktop's file manager."""
    import os
    import subprocess
    import sys
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("the settings folder does not exist yet; run setup first")
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 - a folder the app itself names, never input
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


NOTICES = {
    "add": "Saved. The app inventories new libraries when it (re)starts the peer.",
    "remove": "Removed. The app applies this when it restarts the peer.",
    "join": "Joined. The app shares through the chosen ways when it restarts the peer.",
    "leave": "Left the fleet. This machine keeps its libraries and web view.",
    "presentation": "Saved. Takes effect when the app restarts.",
    "connections": "Saved. The app reconnects now.",
    "fetch": "Saved. The app uses the new schedule now.",
    "seal": "Saved. The app uses it now.",
}
