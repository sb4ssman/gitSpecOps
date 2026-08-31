#!/usr/bin/env python3
"""Read-only cross-machine Git status observer and advisor (initial scaffold)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from advice import render_table
from folder_transport import FolderTransport
from manifest import build_manifest
from observer import RootSpec, observe_roots


def _not_ready(command: str) -> int:
    print(f"'{command}' is reserved by the scaffold; use 'check' or 'doctor' in this slice.")
    return 2


def command_check(args: argparse.Namespace) -> int:
    if args.state_dir and not args.machine_id:
        print("error: --machine-id is required when --state-dir publishes a manifest", file=sys.stderr)
        return 2
    machine_id = args.machine_id or "local-preview"
    machine_label = args.machine_label or machine_id
    observation = observe_roots([RootSpec(Path(root), args.recursive) for root in args.root])
    manifest = build_manifest(machine_id, machine_label, observation.repositories)
    if args.state_dir:
        written = FolderTransport(args.state_dir).write_own_manifest(machine_id, manifest)
        print(f"Manifest written: {written}")
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(render_table(manifest, observation.catalog))
    for issue in observation.issues:
        print(f"warning: {issue}", file=sys.stderr)
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    print(json.dumps(FolderTransport(args.state_dir).doctor(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="observe configured roots and show local advice")
    check.add_argument("--root", action="append", required=True, help="bounded root to inspect")
    check.add_argument("--recursive", action="store_true", help="scan recursively (default: direct children)")
    check.add_argument("--machine-id", help="stable non-personal id; required with --state-dir")
    check.add_argument("--machine-label", help="readable label (default: machine id)")
    check.add_argument("--state-dir", help="optional manifest folder; omit for preview-only")
    check.add_argument("--json", action="store_true", help="print the privacy-minimized manifest")
    check.set_defaults(handler=command_check)

    doctor = subparsers.add_parser("doctor", help="inspect a folder transport without changing it")
    doctor.add_argument("state_dir")
    doctor.set_defaults(handler=command_doctor)

    for name in ("init", "watch", "handoff"):
        reserved = subparsers.add_parser(name, help=f"reserved: {name} workflow")
        reserved.set_defaults(handler=lambda _args, command=name: _not_ready(command))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
