"""CLI entry point. Exit codes describe diagnostics, never visual success."""

import argparse
import json
from dataclasses import asdict

from . import __version__
from .desktop import collect_doctor as collect
from .diagnose import diagnose
from .terminal import render_doctor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local diagnostics for Linux displays and projectors.")
    parser.add_argument("--version", action="version", version=f"BeamFix {__version__}")
    parser.add_argument("--plain", action="store_true", help="Use plain text without colors or decorative characters.")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Read system state without changing it.")
    doctor.add_argument("--json", action="store_true", help="Structured report for development and support.")
    guided = commands.add_parser("troubleshoot", help="Guide troubleshooting when the projector does not show the expected image.")
    guided.add_argument("--try-fix", action="store_true",
                        help="Offer KDE/GNOME Wayland activation and KDE mode trials with approval and automatic undo.")
    for command in (doctor, guided):
        command.add_argument("--plain", action="store_true", default=argparse.SUPPRESS,
                             help="Use plain text without colors or decorative characters.")
    args = parser.parse_args(argv)
    if args.command == "troubleshoot":
        from .troubleshoot import run

        return run(plain=args.plain, try_fix=args.try_fix)
    snapshot = collect()
    findings = diagnose(snapshot)
    uncertain = any(c.status == "unknown" or (c.current_mode is not None and c.current_mode.state == "unknown")
                    for c in snapshot.connectors)
    exit_code = 2 if snapshot.errors or uncertain else (1 if any(f.severity == "warning" for f in findings) else 0)
    if args.json:
        print(json.dumps({
            "schema_version": 1,
            "beamfix_version": __version__,
            "mode": "read_only",
            "visual_confirmation": "not_performed",
            "snapshot": asdict(snapshot),
            "findings": [asdict(finding) for finding in findings],
            "exit_code": exit_code,
        }, ensure_ascii=True, indent=2))
    else:
        render_doctor(snapshot, findings, exit_code, plain=args.plain)
    return exit_code
