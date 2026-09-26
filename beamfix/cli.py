"""CLI entry point. Exit codes describe diagnostics, never visual success."""

import argparse
import json
from dataclasses import asdict

from . import __version__
from .collect import collect
from .diagnose import diagnose


def _safe(value: str) -> str:
    return "".join(char if char.isprintable() else "?" for char in value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local diagnostics for Linux displays and projectors.")
    parser.add_argument("--version", action="version", version=f"BeamFix {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Read system state without changing it.")
    doctor.add_argument("--json", action="store_true", help="Structured report for development and support.")
    commands.add_parser("troubleshoot", help="Guide troubleshooting when the projector does not show the expected image.")
    args = parser.parse_args(argv)
    if args.command == "troubleshoot":
        from .troubleshoot import run

        return run()
    snapshot = collect()
    findings = diagnose(snapshot)
    uncertain = any(c.status == "unknown" for c in snapshot.connectors)
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
        print(f"BeamFix {__version__} — read-only diagnostics")
        print(f"System: {_safe(snapshot.system)} | kernel: {_safe(snapshot.kernel)}")
        print(f"Session: {snapshot.session} | desktop: {_safe(snapshot.desktop)}")
        for gpu in snapshot.gpus:
            print(f"GPU: {_safe(gpu.card)} | driver: {_safe(gpu.driver or 'unavailable')}")
        for connector in snapshot.connectors:
            modes = "unavailable" if connector.modes is None else (", ".join(connector.modes) or "none")
            print(f"\n{_safe(connector.name)} ({connector.kind}): {connector.status}, {connector.enabled}")
            print(f"  Listed modes: {_safe(modes)}")
        for finding in findings:
            target = f" [{_safe(finding.connector)}]" if finding.connector else ""
            print(f"\n{finding.severity.upper()}{target}: {finding.message}\n  {finding.suggestion}")
        for error in snapshot.errors:
            print(f"\nMissing data: {_safe(error)}")
        if not any(f.severity == "warning" for f in findings):
            print("\nNo issues detected by the available checks.")
        print("\nNo changes applied. Image quality requires visual confirmation.")
    return exit_code
