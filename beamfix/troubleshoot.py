"""Guided, read-only troubleshooting with explicit human visual verification."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .collect import collect
from .models import Connector, Snapshot


@dataclass(frozen=True)
class Step:
    code: str
    title: str
    reason: str
    instruction: str


STEPS = {
    "input": Step(
        "input", "Controllare alimentazione e ingresso",
        "Il rilevamento del computer non conferma quale ingresso stia mostrando il proiettore.",
        "Verifica che il proiettore sia acceso e seleziona l'ingresso del cavo collegato "
        "(per esempio HDMI 1 oppure HDMI 2).",
    ),
    "reconnect": Step(
        "reconnect", "Ricollegare il proiettore",
        "Un nuovo collegamento permette di verificare se Linux rileva il display e le sue modalità video.",
        "Scollega e ricollega il cavo del proiettore, controllando anche i raccordi "
        "dell'eventuale adattatore. Attendi qualche secondo.",
    ),
    "direct": Step(
        "direct", "Provare senza dock o adattatori",
        "Un collegamento diretto può aiutare a isolare un problema nella catena di collegamento.",
        "Se disponi di una connessione compatibile, collega il proiettore direttamente "
        "al computer. Se non è possibile o è già collegato direttamente, salta questa prova.",
    ),
    "cable": Step(
        "cable", "Provare un altro cavo",
        "Un confronto con un altro cavo aiuta a circoscrivere il problema; i dati attuali non provano un guasto.",
        "Se ne hai uno disponibile, prova un altro cavo compatibile. Altrimenti salta questa prova.",
    ),
    "activate": Step(
        "activate", "Attivare l'uscita nelle impostazioni Schermi",
        "Linux rileva il display selezionato ma segnala la sua uscita come disabilitata.",
        "Apri le impostazioni Schermi del desktop, identifica il proiettore e abilitalo. "
        "Mantieni acceso anche lo schermo del computer. Applica e usa l'eventuale conferma del desktop.",
    ),
    "presentation": Step(
        "presentation", "Mostrare la presentazione sul proiettore",
        "Vedi il desktop: il collegamento produce un'immagine, ma il contenuto potrebbe essere sull'altro schermo.",
        "Nelle impostazioni della presentazione seleziona lo schermo del proiettore, "
        "oppure sposta la finestra su quello schermo e avvia la presentazione.",
    ),
    "mirror": Step(
        "mirror", "Provare la duplicazione dello schermo",
        "La duplicazione permette di verificare se il contenuto atteso compare anche sul proiettore.",
        "Nelle impostazioni Schermi scegli Duplica o Rispecchia, se disponibile, "
        "mantenendo attivo lo schermo del computer. Annota l'impostazione precedente "
        "per poterla ripristinare e usa l'eventuale conferma del desktop.",
    ),
    "mode": Step(
        "mode", "Provare un'altra modalità offerta dal desktop",
        "L'uscita risulta attiva, ma BeamFix non conosce risoluzione e frequenza effettivamente in uso.",
        "Nelle impostazioni Schermi del proiettore, annota la modalità attuale e prova "
        "un'altra modalità tra quelle offerte dal desktop. Mantieni attivo lo schermo "
        "del computer; se peggiora, ripristina la precedente. Salta se non ci sono alternative.",
    ),
    "refresh": Step(
        "refresh", "Ripetere la lettura dei dati",
        "I dati sul display sono incompleti o sconosciuti: non bastano per scegliere una correzione.",
        "Verifica di aver avviato BeamFix nella sessione Linux del computer collegato "
        "al proiettore. Attendi qualche secondo e scegli Fatto per ripetere la lettura.",
    ),
}


@dataclass
class Attempt:
    step: Step
    performed: bool
    before: str
    after: str | None = None
    observation: str | None = None


@dataclass
class Session:
    symptom: str = "no_signal"
    target: str | None = None
    snapshot: Snapshot | None = None
    attempts: list[Attempt] = field(default_factory=list)
    outcome: str = "interrupted"


SYMPTOMS = {
    "no_signal": "Il proiettore mostra Nessun segnale",
    "black": "Lo schermo proiettato è nero",
    "desktop": "Vedo il desktop, ma non la presentazione",
}


def candidates(snapshot: Snapshot) -> list[Connector]:
    # An unclassified connector is not proof that no external display exists.
    return [c for c in snapshot.connectors if c.kind in {"external", "unknown"}]


def target_connector(snapshot: Snapshot, target: str | None) -> Connector | None:
    return next((c for c in candidates(snapshot) if c.name == target), None)


def next_step(snapshot: Snapshot, target: str | None, symptom: str, tried: set[str]) -> Step | None:
    """Choose one applicable test; never infer visual success or repeat a test."""
    connector = target_connector(snapshot, target)
    if not candidates(snapshot):
        codes = ["refresh"]
    elif connector is None:
        codes = ["input", "reconnect", "direct", "cable"]
    elif connector.status == "unknown":
        codes = ["refresh"]
    elif connector.status == "disconnected":
        codes = ["input", "reconnect", "direct", "cable"]
    elif connector.enabled == "unknown" or connector.modes is None:
        codes = ["refresh"]
    elif not connector.modes:
        codes = ["reconnect", "direct", "cable"]
    elif connector.enabled == "disabled":
        # Do not propose resolution/duplication changes for an inactive output.
        codes = ["activate", "reconnect", "direct", "cable"]
    elif symptom == "desktop":
        codes = ["presentation", "mirror"]
    else:
        codes = ["input", "mirror", "mode", "reconnect", "direct", "cable"]
    return next((STEPS[code] for code in codes if code not in tried), None)


def describe(snapshot: Snapshot, target: str | None) -> str:
    connector = target_connector(snapshot, target)
    if connector is None:
        return "Display interessato non identificato."
    status = {"connected": "collegato", "disconnected": "scollegato", "unknown": "collegamento sconosciuto"}
    enabled = {"enabled": "uscita abilitata", "disabled": "uscita disabilitata", "unknown": "abilitazione sconosciuta"}
    modes = "modalità non leggibili" if connector.modes is None else f"{len(connector.modes)} modalità elencate"
    return f"{connector.name!r}: {status[connector.status]}, {enabled[connector.enabled]}, {modes}."


class StopSession(Exception):
    pass


def choose(prompt: str, options: list[tuple[str, str]], read: Callable[[str], str], write: Callable[[str], None]) -> str:
    write(prompt)
    for index, (_, label) in enumerate(options, 1):
        write(f"  {index}. {label}")
    write("  0. Chiudi e mostra il riepilogo")
    while True:
        value = read("> ").strip()
        if value == "0":
            raise StopSession
        if value.isascii() and value.isdecimal() and len(value) <= len(str(len(options))):
            index = int(value) - 1
            if 0 <= index < len(options):
                return options[index][0]
        write("Inserisci il numero di una delle opzioni.")


def select_target(snapshot: Snapshot, read: Callable[[str], str], write: Callable[[str], None]) -> str | None:
    ports = candidates(snapshot)
    if not ports:
        write("Nessuna uscita esterna identificabile nei dati disponibili.")
        return None
    options = [(c.name, describe(snapshot, c.name)) for c in ports]
    options.append(("", "Non so quale sia / il proiettore non è nell'elenco"))
    write("I nomi delle uscite non identificano con certezza il dispositivo o il cavo fisico.")
    return choose("Quale uscita corrisponde al proiettore? Puoi confrontarla con le impostazioni Schermi.", options, read, write) or None


def insufficient(session: Session) -> bool:
    snapshot = session.snapshot
    if snapshot is None or snapshot.errors:
        return True
    connector = target_connector(snapshot, session.target)
    return connector is None or connector.status == "unknown" or (
        connector.status == "connected" and (connector.enabled == "unknown" or connector.modes is None)
    )


def summarize(session: Session, write: Callable[[str], None]) -> int:
    labels = {
        "resolved": "Immagine attesa confermata dall'utente.",
        "unresolved": "Problema ancora presente: le prove guidate disponibili sono terminate.",
        "insufficient": "Dati insufficienti per proseguire con una diagnosi mirata.",
        "interrupted": "Percorso interrotto; soluzione non confermata.",
    }
    write("\nRiepilogo — " + labels[session.outcome])
    for number, attempt in enumerate(session.attempts, 1):
        state = "eseguita" if attempt.performed else "saltata, non verificata"
        write(f"{number}. {attempt.step.title}: {state}.")
        if attempt.performed:
            write("   Prima: " + attempt.before)
            if attempt.after is not None:
                write("   Dopo: " + attempt.after)
            write("   Esito visivo: " + (attempt.observation or "non confermato"))
    if not session.attempts:
        write("Nessuna prova eseguita.")
    if session.snapshot is not None:
        write("Ultima lettura: " + describe(session.snapshot, session.target))
        if session.snapshot.errors:
            write("La raccolta contiene dati mancanti; usa beamfix doctor per i dettagli.")
    if session.outcome != "resolved":
        write("Le prove fallite o saltate non escludono un guasto a cavo, adattatore o proiettore.")
        write("Per approfondire: conserva questo riepilogo e il report di beamfix doctor --json.")
    write("BeamFix non ha applicato modifiche né salvato report automaticamente.")
    return 0 if session.outcome == "resolved" else (1 if session.outcome == "unresolved" else 2)


def run(
    *,
    snapshot_reader: Callable[[], Snapshot] | None = None,
    read: Callable[[str], str] | None = None,
    write: Callable[[str], None] | None = None,
) -> int:
    snapshot_reader = snapshot_reader or collect
    read = read or input
    write = write or print
    session = Session()
    write("BeamFix — percorso guidato: proiettore collegato, immagine assente o inattesa")
    write("Ti proporrò una prova alla volta. Le modifiche nelle impostazioni le esegui tu; "
          "BeamFix rilegge i dati e chiede cosa vedi. Puoi saltare una prova o chiudere con 0.")
    try:
        session.symptom = choose("Che cosa vedi sul proiettore?", list(SYMPTOMS.items()), read, write)
        session.snapshot = snapshot_reader()
        session.target = select_target(session.snapshot, read, write)
        while True:
            write("\nStato osservato: " + describe(session.snapshot, session.target))
            tried = {a.step.code for a in session.attempts}
            step = next_step(session.snapshot, session.target, session.symptom, tried)
            if step is None:
                session.outcome = "insufficient" if insufficient(session) else "unresolved"
                break
            write("\nProva: " + step.title)
            write("Perché: " + step.reason)
            write(step.instruction)
            action = choose("Quando sei pronto:", [("done", "Fatto: rileggi lo stato"), ("skip", "Salta questa prova")], read, write)
            attempt = Attempt(step, action == "done", describe(session.snapshot, session.target))
            session.attempts.append(attempt)
            if action == "skip":
                continue
            previous = session.snapshot
            session.snapshot = snapshot_reader()
            # Hot-plug can change names. Never silently switch to another monitor.
            old_ports = {(c.name, c.status) for c in candidates(previous)}
            new_ports = {(c.name, c.status) for c in candidates(session.snapshot)}
            current_target = target_connector(session.snapshot, session.target)
            newly_connected = any(status == "connected" and (name, status) not in old_ports for name, status in new_ports)
            if (session.target is not None and target_connector(session.snapshot, session.target) is None) or (
                session.target is None and old_ports != new_ports
            ) or (
                newly_connected and current_target is not None and current_target.status != "connected"
            ):
                write("L'elenco dei collegamenti è cambiato: identifica di nuovo il proiettore.")
                session.target = None
                session.target = select_target(session.snapshot, read, write)
            attempt.after = describe(session.snapshot, session.target)
            write("Nuova lettura: " + attempt.after)
            write("Lo stato di Linux, da solo, non conferma che l'immagine sia visibile.")
            observed = choose("Che cosa vedi adesso?", [
                ("resolved", "Vedo l'immagine che volevo proiettare"),
                *SYMPTOMS.items(),
                ("unverified", "Non posso verificare l'immagine"),
            ], read, write)
            attempt.observation = "immagine attesa confermata" if observed == "resolved" else (
                "non verificabile" if observed == "unverified" else SYMPTOMS[observed]
            )
            if observed == "resolved":
                session.outcome = "resolved"
                break
            if observed == "unverified":
                session.outcome = "insufficient"
                break
            session.symptom = observed
    except (EOFError, KeyboardInterrupt, StopSession):
        write("\nChiusura del percorso guidato.")
    return summarize(session, write)
