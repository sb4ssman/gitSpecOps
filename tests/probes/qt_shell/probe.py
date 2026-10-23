"""Qt trial: a tray icon and a native window over the fleet display contract.

    python tests/probes/qt_shell/probe.py --demo
    python tests/probes/qt_shell/probe.py --root <your library folder>
    python tests/probes/qt_shell/probe.py --demo --screenshot <file.png> --seconds 5

Answers one question before the App is built on Qt: on this OS and desktop, does PySide6 give
a working tray / menu-bar icon and a usable native window? It renders the same versioned display
document the web dashboard renders, and refuses a contract version it does not know -- a skin,
deciding nothing. `--root` observes a library read-only (no fetch, nothing published);
`--demo` shows an invented three-machine fleet. See README.md beside this file.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "git-sync-suggester"))
from _paths import bootstrap  # noqa: E402

bootstrap()

from fleet_display import CONTRACT_NAME, CONTRACT_VERSION  # noqa: E402
from local_view import display_from_manifests  # noqa: E402
from manifest import build_manifest, fleet_id_for, repository_id  # noqa: E402
from observer import RootSpec, observe_roots  # noqa: E402

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QHeaderView, QLabel, QMainWindow,  # noqa: E402
                               QMenu, QSplitter, QSystemTrayIcon, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

#: Invented, for the demo only.
DEMO_SECRET = "ab" * 32
TONES = {"success": "#2e9d5b", "warning": "#d99a1e", "danger": "#d0463b",
         "neutral": "#7a8593", "muted": "#b5bcc5"}


def _stamp(seconds_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record(owner: str, name: str, **state) -> dict:
    record = {"repo_id": repository_id("github.com", owner, name, DEMO_SECRET),
              "branch_id": "0" * 16, "has_upstream": True, "upstream_observed_at": _stamp(60),
              "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0, "untracked": 0,
              "stashes": 0, "operation": None, "identity": "remote", "has_remote": True,
              "unpushed": 0, "name": {"host": "github.com", "owner": owner, "name": name},
              "branch": "main", "head": "1" * 40}
    record.update(state)
    return record


def demo_document() -> dict:
    """An invented fleet: three machines, one of them not seen for two hours."""
    fleet = fleet_id_for(DEMO_SECRET)
    desk = [_record("example-org", "website"),
            _record("example-org", "api", unstaged=3, untracked=1),
            _record("example-user", "dotfiles", ahead=2, unpushed=2, head="2" * 40),
            _record("example-user", "notes")]
    laptop = [_record("example-org", "website", behind=4),
              _record("example-org", "api"),
              _record("example-user", "dotfiles", head="3" * 40),
              _record("example-user", "sketchbook", has_remote=False, has_upstream=False,
                      identity="root", unpushed=7)]
    server = [_record("example-org", "website"), _record("example-org", "api", stashes=1)]
    manifests = [build_manifest(fleet, "machine-a", "desk", desk, _stamp(20), carries_names=True),
                 build_manifest(fleet, "machine-b", "laptop", laptop, _stamp(40),
                                carries_names=True),
                 build_manifest(fleet, "machine-c", "debian", server, _stamp(7200),
                                carries_names=True)]
    return display_from_manifests(manifests, fleet_id=fleet)


def library_document(root: Path) -> dict:
    """This machine's library, observed read-only: no fetch, nothing published."""
    observation = observe_roots([RootSpec(root, True)], None)
    manifest = build_manifest("local-preview", "this-machine", "this machine",
                              observation.repositories, carries_names=True)
    return display_from_manifests([manifest], catalog=observation.catalog)


def dot(color: str) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(6, 6, 52, 52)
    painter.end()
    return QIcon(pixmap)


class FleetWindow(QMainWindow):
    def __init__(self, load):
        super().__init__()
        self.load = load
        self.document: dict = {}
        self.setWindowTitle("gitSpecOps — fleet (Qt trial)")
        self.resize(1000, 560)
        self.summary = QLabel()
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.detail = QTextBrowser()
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([380, 180])
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self.summary)
        layout.addWidget(split)
        self.setCentralWidget(body)
        self.tray: QSystemTrayIcon | None = None

    def refresh(self) -> None:
        document = self.load()
        contract = document.get("contract") or {}
        if contract.get("name") != CONTRACT_NAME or contract.get("version") != CONTRACT_VERSION:
            self.summary.setText(f"Unsupported display contract {contract!r}; view not changed.")
            return
        self.document = document
        summary = document["summary"]
        machines = document["machines"]
        text = (f"{summary['repositories']} repositories on {summary['machines']} machine(s) — "
                f"{summary['attention']} need attention; {summary['stale_machines']} stale")
        self.summary.setText(text)
        headers = ["Repository"] + [f"{m['label']} ({m['freshness']})" for m in machines] + \
                  ["Advice"]
        rows = document["rows"]
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(row["name"]))
            for c, machine in enumerate(machines, start=1):
                cell = row["cells"].get(machine["id"]) or {}
                item = QTableWidgetItem(cell.get("description", ""))
                tint = QColor(TONES.get(cell.get("tone"), TONES["muted"]))
                tint.setAlpha(70)
                item.setBackground(QBrush(tint))
                self.table.setItem(r, c, item)
            self.table.setItem(r, len(headers) - 1, QTableWidgetItem(row["advice"]))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
        if self.tray is not None:
            self.tray.setIcon(dot(TONES["warning" if summary["attention"] else "success"]))
            self.tray.setToolTip(f"gitSpecOps: {text}")
        if rows:
            self.table.selectRow(0)

    def show_detail(self) -> None:
        selected = self.table.selectedIndexes()
        if not selected or not self.document:
            return
        row = self.document["rows"][selected[0].row()]
        parts = [f"<h3>{row['identity']['owner']}/{row['identity']['name']}</h3>",
                 f"<p>{row['advice']}</p>"]
        for machine in self.document["machines"]:
            cell = row["cells"].get(machine["id"]) or {}
            facts = cell.get("facts")
            if not facts:
                parts.append(f"<p><b>{machine['label']}</b>: {cell.get('description', '')}</p>")
                continue
            head = facts.get("head")
            parts.append(f"<p><b>{machine['label']}</b>: {cell.get('description', '')}<br>"
                         f"branch {facts.get('branch') or 'not shared'}, commit "
                         f"{head[:10] if head else 'not shared'}, ahead {facts.get('ahead')}, "
                         f"behind {facts.get('behind')}, unstaged {facts.get('unstaged')}</p>")
        self.detail.setHtml("".join(parts))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.tray is not None and self.tray.isVisible():
            self.hide()        # closing the window leaves the tray running, like the real App
            event.ignore()
        else:
            event.accept()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Qt trial over the fleet display contract.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="an invented three-machine fleet")
    source.add_argument("--root", type=Path, help="observe this library read-only")
    parser.add_argument("--seconds", type=float, help="quit by itself after this long")
    parser.add_argument("--screenshot", type=Path, help="save the window to this PNG first")
    args = parser.parse_args(argv)
    load = demo_document if args.demo else (lambda: library_document(args.root))

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    window = FleetWindow(load)
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    print(f"Qt platform: {app.platformName()}; system tray available: {tray_available}")
    if tray_available:
        tray = QSystemTrayIcon(dot(TONES["neutral"]), app)
        menu = QMenu()
        for label, slot in (("Open gitSpecOps", lambda: (window.showNormal(), window.raise_(),
                                                         window.activateWindow())),
                            ("Refresh", window.refresh), (None, None), ("Quit", app.quit)):
            if label is None:
                menu.addSeparator()
                continue
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: window.showNormal()
                               if reason == QSystemTrayIcon.Trigger else None)
        tray.show()
        window.tray = tray
    else:
        app.setQuitOnLastWindowClosed(True)
    window.refresh()
    window.show()
    if args.screenshot:
        QTimer.singleShot(800, lambda: print("screenshot saved:",
                                             window.grab().save(str(args.screenshot))))
    if args.seconds:
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
