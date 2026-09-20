"""Small, deterministic rules with evidence-backed wording."""

from .models import Finding, Snapshot


def diagnose(snapshot: Snapshot) -> list[Finding]:
    findings: list[Finding] = []
    if snapshot.errors:
        findings.append(Finding(
            "incomplete_observation", "warning", "La raccolta dei dati è incompleta.",
            "Consulta gli errori; riprova nella sessione Linux locale con il display collegato.",
        ))
    if snapshot.session not in {"wayland", "x11"}:
        findings.append(Finding(
            "graphical_session_unconfirmed", "info", "Sessione grafica non confermata.",
            "Per le future correzioni avvia BeamFix dal terminale del desktop interessato.",
        ))
    external = [c for c in snapshot.connectors if c.kind == "external"]
    if external and all(c.status == "disconnected" for c in external):
        findings.append(Finding(
            "no_external_connected", "warning", "Linux non segnala display esterni collegati sulle porte osservate.",
            "Se ti aspetti un proiettore, controlla alimentazione, ingresso selezionato, cavo e adattatore. La causa non è determinabile da questi dati.",
        ))
    for connector in snapshot.connectors:
        if connector.status == "unknown":
            findings.append(Finding(
                "connection_unknown", "warning", "Lo stato del collegamento non è determinabile.",
                "Riprova dopo aver ricollegato il display; non equivale a un cavo guasto.", connector.name,
            ))
        if connector.status != "connected":
            continue
        if connector.enabled == "disabled":
            findings.append(Finding(
                "connected_disabled", "info" if connector.kind == "internal" else "warning",
                "Connettore collegato ma segnalato come disabilitato da Linux.",
                "Può essere intenzionale. Se vuoi usare questo schermo, verifica l'attivazione nelle impostazioni Schermi.", connector.name,
            ))
        if connector.modes == ():
            findings.append(Finding(
                "connected_no_modes", "warning", "Connettore collegato senza modalità video elencate.",
                "Controlla il collegamento e ripeti la diagnosi; può dipendere da driver, rilevamento o adattatore.", connector.name,
            ))
    return findings
