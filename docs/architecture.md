# Architettura iniziale

`collect.py` legge le osservazioni del kernel e produce uno `Snapshot`.
`diagnose.py` applica regole deterministiche a quel modello senza accedere al sistema.
`cli.py` presenta i risultati o esporta il JSON su stdout.
`models.py` definisce dati e risultati condivisi.

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
