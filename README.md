# BeamFix

Diagnostica locale per monitor e proiettori su Linux. L'obiettivo è arrivare a
«collego il proiettore, lancio BeamFix, provo una correzione e confermo il risultato».

**Stato: percorso guidato v0.2.0.** Il comando `doctor` raccoglie dati e segnala
anomalie; `troubleshoot` guida una prova alla volta e verifica l'esito con l'utente.
Le correzioni automatiche e l'interfaccia grafica sono in roadmap.

## Provalo subito

Richiede Linux e Python 3.11 o successivo. Dalla cartella del repository:

```bash
python3 -m beamfix doctor
python3 -m beamfix doctor --json
python3 -m beamfix troubleshoot
```

Funziona senza dipendenze aggiuntive, accesso a Internet, servizi esterni o chiavi API.
Non richiede `sudo`. Non cambia risoluzione, driver o configurazione del desktop.

Per installare il comando in un ambiente virtuale (richiede `venv` e `pip`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/beamfix doctor
.venv/bin/beamfix troubleshoot
```

L'installazione può scaricare strumenti di build; l'esecuzione di BeamFix è offline.
Se avevi già installato una versione precedente, ripeti `.venv/bin/python -m pip install .`
per aggiornare il comando nell'ambiente virtuale. L'avvio con `python3 -m beamfix`
dalla cartella del repository usa direttamente il codice locale.

## Percorso guidato: proiettore collegato, immagine assente o inattesa

Avvia `python3 -m beamfix troubleshoot` dal terminale del computer collegato al
proiettore. Seleziona con i numeri quello che vedi: «Nessun segnale», schermo nero,
oppure desktop senza presentazione. Poi indica l'uscita del proiettore; se non sai
riconoscerla, puoi dichiararlo senza scegliere a caso un altro monitor.

BeamFix propone una sola prova pertinente ai dati disponibili: ingresso del
proiettore, collegamento, attivazione dell'uscita, schermo della presentazione,
duplicazione o modalità video. Le eventuali modifiche le esegui manualmente nelle
impostazioni del desktop: BeamFix non le applica e non può ripristinarle.

Dopo «Fatto» rilegge lo stato e domanda cosa vedi. Se il sintomo cambia, cambia
anche il percorso. Una prova eseguita o saltata non viene riproposta nella stessa
sessione. Se cambia il collegamento e occorre identificare una nuova uscita, chiede
di selezionarla esplicitamente. Puoi saltare le prove non disponibili e chiudere
in qualsiasi momento con `0` o Ctrl+C.

Il riepilogo distingue prove eseguite e saltate, stato prima/dopo ed esito visivo.
La soluzione è confermata soltanto quando dichiari di vedere l'immagine attesa;
un'uscita abilitata non è sufficiente. Una prova fallita non dimostra da sola un
guasto fisico, e una prova saltata non esclude alcuna causa.

Codici di uscita di `troubleshoot`: `0` immagine attesa confermata dall'utente,
`1` problema ancora presente al termine delle prove disponibili, `2` dati o
verifica visiva insufficienti oppure percorso interrotto. Questi codici hanno un
significato diverso da quelli di `doctor`. Il riepilogo resta nel terminale:
non viene salvato o inviato automaticamente. Il percorso non ha un'opzione JSON;
il report tecnico resta disponibile con `doctor --json`.

## Cosa controlla oggi

- Sistema, kernel, tipo di sessione dichiarato e desktop.
- Schede grafiche DRM e nome del driver, quando disponibile.
- Connettori, stato del collegamento, abilitazione e modalità video elencate.
- Uscite collegate ma disabilitate, modalità mancanti e dati non accessibili.
- Report italiano da terminale o JSON con versione dello schema e codici diagnostici.

Il programma legge `/sys/class/drm` e due variabili di sessione:
`XDG_SESSION_TYPE` e `XDG_CURRENT_DESKTOP`. Non raccoglie EDID grezzi, seriali,
hostname, account o log di sistema. Non salva né invia report automaticamente.
Il report contiene comunque dettagli su hardware e ambiente: controllalo prima di condividerlo.

## Limiti da conoscere

Un'uscita abilitata non prova che l'immagine sia visibile o corretta. Questa versione
non misura refresh rate, risoluzione corrente, scala, audio, HDCP o qualità del cavo.
Non identifica con certezza se il dispositivo sia un monitor o un proiettore.
USB-C può apparire come DisplayPort: il tipo di connettore DRM non identifica il cavo fisico.

I dati sono un'osservazione del kernel, possono essere incompleti o cambiare durante
il collegamento. Una modalità elencata non è necessariamente quella in uso.
Non viene eseguita alcuna scansione forzata. Il backend è indipendente dal desktop;
la compatibilità con specifici driver e dispositivi richiede prove hardware.

Il codice di uscita di `doctor` è `0` se i controlli disponibili non segnalano anomalie,
`1` se ci sono avvisi, `2` se l'osservazione è incompleta o lo stato è sconosciuto.
Anche gli errori di sintassi della CLI restituiscono `2`.
`0` non significa «proiezione verificata». Le porte scollegate possono essere normali;
l'avviso va interpretato rispetto al display che ci si aspettava di trovare.

## Sviluppo

```bash
python3 -m unittest discover -s tests -v
```

I test usano dispositivi simulati e non modificano il sistema grafico.
GitHub Actions esegue i test e verifica l'installazione su Python 3.11 e 3.14.
Vedi [architettura](docs/architecture.md) e [roadmap](docs/roadmap.md).

Il progetto è in sviluppo privato. La licenza di distribuzione è ancora da scegliere.
