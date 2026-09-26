# Architettura iniziale

`collect.py` legge le osservazioni del kernel e produce uno `Snapshot`.
`diagnose.py` applica regole deterministiche a quel modello senza accedere al sistema.
`cli.py` presenta i risultati o esporta il JSON su stdout.
`models.py` definisce dati e risultati condivisi.

## Percorso guidato

`troubleshoot.py` aggiunge il comando interattivo mantenendo `doctor` e il suo
schema JSON invariati. `next_step` sceglie una prova usando lo snapshot, l'uscita
selezionata, il sintomo dichiarato e i codici delle prove già eseguite o saltate;
non legge il sistema e non esegue modifiche. L'ordine delle prove è deterministico.

`run` gestisce domande, letture e riepilogo. Collector e funzioni di input/output
sono sostituibili nei test. Dopo ogni prova dichiarata eseguita acquisisce uno
snapshot e chiede l'esito visivo. Lo stato DRM non genera mai da solo un risultato
di successo. Le prove saltate sono registrate come non verificate.

La scelta dell'uscita è esplicita anche quando ne appare una sola. Se un'uscita
scompare o il collegamento passa a un'altra porta, il percorso richiede una nuova
selezione. Il nome del connettore serve soltanto a seguire la sessione: non è
un'identità persistente del proiettore e non permette di rilevare la sostituzione
di due dispositivi sulla stessa porta fra due letture.

Il numero di prove è limitato: ogni codice viene proposto al massimo una volta
nella sessione, anche se cambia uscita. I dati sconosciuti richiedono una rilettura;
se restano insufficienti il percorso si ferma senza dedurre un guasto. EOF, Ctrl+C
e l'opzione `0` producono un riepilogo con esito non confermato. Nulla viene
salvato automaticamente; le modifiche manuali restano sotto il controllo dell'utente.

## Raccolta e test

Il backend iniziale è in sola lettura. I test iniettano un albero DRM temporaneo:
è possibile simulare porte scollegate, dati mancanti e più GPU senza hardware.
Gli stati sconosciuti restano distinti da «scollegato»; le modalità non leggibili
restano distinte da una lista vuota. Il nome della scheda non è una sua identità stabile.

## Confini delle osservazioni

I campi `status`, `enabled` e `modes` seguono l'implementazione
[DRM sysfs nel kernel Linux](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_sysfs.c).
In particolare `modes` elenca nomi di modalità e non fornisce il refresh rate corrente.
Il rilevamento di X11 non si basa sulla sola variabile `DISPLAY`, presente anche
in alcune sessioni Wayland tramite XWayland.

## Estensione verso le correzioni

Un futuro backend per GNOME, KDE o X11 dovrà prima interrogare il desktop e
ottenere una configurazione completa ripristinabile. Una correzione avrà una
precondizione, un'azione specifica, la verifica dello stato e un ripristino.
Non basta riutilizzare i nomi DRM come identificatori del compositore.

Prima di qualsiasi modifica serve una nuova lettura: i dati possono essere diventati
obsoleti dopo un hot-plug. Il ripristino dovrà sopravvivere al crash della UI e
rispettare scollegamenti e modifiche effettuate nel frattempo dall'utente.
L'interfaccia chiederà conferma visiva entro un timeout. Riavviare la sessione grafica,
installare driver o modificare file di sistema non fa parte del primo MVP.

Per aggiungere una regola, usa un codice stabile, indica l'evidenza, mantieni
esplicita l'incertezza e aggiungi un caso di test che distingua errore e normalità.
