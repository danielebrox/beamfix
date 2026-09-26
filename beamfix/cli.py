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
    parser = argparse.ArgumentParser(description="Diagnostica locale per display e proiettori Linux.")
    parser.add_argument("--version", action="version", version=f"BeamFix {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Legge lo stato del sistema senza modificarlo.")
    doctor.add_argument("--json", action="store_true", help="Report strutturato per sviluppo e assistenza.")
    commands.add_parser("troubleshoot", help="Guida le prove quando il proiettore non mostra l'immagine attesa.")
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
        print(f"BeamFix {__version__} — diagnosi in sola lettura")
        print(f"Sistema: {_safe(snapshot.system)} | kernel: {_safe(snapshot.kernel)}")
        print(f"Sessione: {snapshot.session} | desktop: {_safe(snapshot.desktop)}")
        for gpu in snapshot.gpus:
            print(f"GPU: {_safe(gpu.card)} | driver: {_safe(gpu.driver or 'non disponibile')}")
        for connector in snapshot.connectors:
            modes = "non disponibili" if connector.modes is None else (", ".join(connector.modes) or "nessuna")
            print(f"\n{_safe(connector.name)} ({connector.kind}): {connector.status}, {connector.enabled}")
            print(f"  Modalità elencate: {_safe(modes)}")
        for finding in findings:
            target = f" [{_safe(finding.connector)}]" if finding.connector else ""
            print(f"\n{finding.severity.upper()}{target}: {finding.message}\n  {finding.suggestion}")
        for error in snapshot.errors:
            print(f"\nDati mancanti: {_safe(error)}")
        if not any(f.severity == "warning" for f in findings):
            print("\nNessuna anomalia rilevata dai controlli disponibili.")
        print("\nNessuna modifica applicata. La qualità dell'immagine richiede conferma visiva.")
    return exit_code
