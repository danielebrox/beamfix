# BeamFix

Diagnostica locale per monitor e proiettori su Linux. L'obiettivo è arrivare a
«collego il proiettore, lancio BeamFix, provo una correzione e confermo il risultato».

**Stato: fondamenta v0.1.0.** Il comando `doctor` raccoglie dati e segnala anomalie;
le correzioni automatiche e l'interfaccia grafica sono in roadmap.

## Provalo subito

Richiede Linux e Python 3.11 o successivo. Dalla cartella del repository:

```bash
python3 -m beamfix doctor
python3 -m beamfix doctor --json
```

Funziona senza dipendenze aggiuntive, accesso a Internet, servizi esterni o chiavi API.
Non richiede `sudo`. Non cambia risoluzione, driver o configurazione del desktop.

Per installare il comando in un ambiente virtuale (richiede `venv` e `pip`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/beamfix doctor
```

L'installazione può scaricare strumenti di build; l'esecuzione di BeamFix è offline.

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

Il codice di uscita è `0` se i controlli disponibili non segnalano anomalie,
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
