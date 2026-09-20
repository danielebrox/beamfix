# Roadmap

## 0.1 — Diagnosi locale (implementata)

- CLI `doctor`, output italiano e JSON v1.
- Lettura DRM, GPU/driver e contesto della sessione.
- Regole iniziali e gestione di dati incompleti.
- Test con hardware simulato e configurazione CI.

## 0.2 — Primo backend di correzione

Scegliere un solo ambiente desktop dopo la prima prova sul computer di sviluppo.
Rilevare la configurazione corrente, proporre l'attivazione di un'uscita e offrire
un'anteprima dell'azione. Applicare una modifica per volta, con ripristino automatico
e conferma visiva. Verificare timeout, crash e scollegamento del proiettore.

## 0.3 — Uso quotidiano

Interfaccia con «Diagnostica» e «Prova correzione»; duplicazione/estensione e selezione
di una modalità compatibile usando le informazioni del backend. Aggiungere
diagnosi audio HDMI e un secondo ambiente desktop solo dopo aver verificato il primo.

## Prima di una release pubblica

Scegliere licenza e modalità di distribuzione. Provare su proiettori reali,
HDMI diretto, adattatori USB-C e dock; documentare desktop, GPU e driver verificati.
Nessuna promessa di compatibilità universale o di riparazione dei guasti fisici.
