# Automatik (vorbereitet, NICHT aktiviert)

Zwei geplante Aufträge im Benutzerkonto (launchd, lokale Zeit des Macs):

| Auftrag | Zeit | Befehl | Wirkung |
|---|---|---|---|
| `de.nbaedge.update-model` | täglich 08:00 | `python update_model.py` | Ratings mit den beendeten Spielen fortschreiben |
| `de.nbaedge.fetch-odds` | täglich 22:00 | `python fetch_odds_daily.py` | ein Odds-Abruf (Totals/Spreads, 4 Credits) füllt `data/odds_cache.json` |

Beide protokollieren in `data/automation.log` (Zeit, Auftrag, OK / SKIP mit Grund / ERROR mit kurzer Meldung, ohne Keys und URLs).
stdout/stderr landen in `data/automation_update_model.{out,err}.log` bzw. `data/automation_fetch_odds.{out,err}.log`.

## Installation und Entfernung (erst nach einem manuellen Testlauf von `update_model.py`)

```bash
cd ~/Desktop/NBAEdge
bash automation/install_schedule.sh      # installieren (kein sudo), zeigt am Ende die geladenen Aufträge
bash automation/uninstall_schedule.sh    # wieder entfernen
```

Die plist-Dateien enthalten absolute Pfade für diesen Projektordner (`/Users/baranalturk/Desktop/NBAEdge`).
Wird das Projekt verschoben, die Pfade in `automation/*.plist` anpassen (das Installationsskript prüft, ob sie existieren).

Einmaliger Test nach der Installation (startet den Auftrag sofort, unabhängig von der Uhrzeit):

```bash
launchctl kickstart gui/$(id -u)/de.nbaedge.update-model
tail -3 data/automation.log; cat data/automation_update_model.err.log
```

## Was launchd bei diesem Aufbau tut (Schlaf, Aus, Deckel zu)

Gekennzeichnet: **[bekannt]** = steht in der Apple-Dokumentation (`man launchd.plist`) oder ist gängiges, dokumentiertes
Verhalten; **[Annahme]** = Erfahrungswert oder Schlussfolgerung, nicht auf diesem Mac geprüft.

- **Mac schläft um 08:00/22:00** (auch Deckel zu ohne externen Monitor): **[bekannt]** `StartCalendarInterval` wird beim
  nächsten Aufwachen nachgeholt; mehrere verpasste Termine werden zu einem Lauf zusammengefasst. Launchd weckt den Mac nicht
  selbst. Der Lauf startet also erst, wenn du den Mac aufklappst bzw. er aufwacht.
- **Mac ist um die Zeit ausgeschaltet:** **[Annahme, gestützt auf die Dokumentation, die nur den Schlaf erwähnt]** Der Termin
  verfällt. Es gibt keinen Nachholmechanismus beim nächsten Start (`RunAtLoad` ist bewusst `false`). Für Ratings ist das
  unkritisch: `update_model.py` holt mit 2 Tagen Überlappung alles Verpasste beim nächsten Lauf nach. Die Quoten (22:00) würden
  für den Tag fehlen, dann bleibt der Knopf „Refresh Odds“.
- **Abgemeldet / Anmeldefenster:** **[bekannt]** Ein LaunchAgent läuft nur in der Sitzung des angemeldeten Benutzers.
  Nach einem Neustart (mit FileVault) passiert nichts, bis du dich angemeldet hast. Bildschirmsperre ist unproblematisch.
- **Deckel zu mit Netzteil + externem Monitor** (Clamshell): **[bekannt]** Der Mac bleibt wach, die Aufträge laufen pünktlich.
- **Netz direkt nach dem Aufwachen:** **[Annahme]** Das WLAN ist oft erst nach einigen Sekunden wieder da, ein nachgeholter Lauf
  kann dann am Netz scheitern. Der Odds-Auftrag wiederholt nach 5 Minuten genau einmal. `update_model.py` hat bewusst keine
  Wiederholung: Es protokolliert den Fehler (Sidebar gelb) und holt am nächsten Tag alles nach. Du kannst es auch von Hand
  neu starten (idempotent).
- **Zeitzone:** **[bekannt]** `StartCalendarInterval` richtet sich nach der Systemzeitzone. Steht der Mac auf Europe/Berlin,
  sind es 08:00/22:00 deutscher Zeit (Sommer-/Winterzeit folgt der Ortszeit **[Annahme]**). Die `TZ`-Variable in der plist wirkt
  nur auf die Zeitstempel im Protokoll.
- **Datenschutz-Sperre für Desktop (macOS TCC):** **[Annahme/Erfahrungswert, der wichtigste Punkt zum Prüfen]** Skripte unter
  `~/Desktop` können aus launchd mit „Operation not permitted“ scheitern, weil macOS Desktop/Dokumente schützt und das
  Python-Programm dafür keine Freigabe hat. Dann: Projekt in einen Ordner außerhalb von Desktop/Dokumente/Downloads verschieben
  (plist-Pfade anpassen) oder dem Python-Programm unter Systemeinstellungen → Datenschutz & Sicherheit → Vollständiger
  Festplattenzugriff erlauben. Der Test oben (`kickstart` und `err.log` ansehen) zeigt es sofort.

Was du selbst einstellen könntest (von mir nicht geändert, kein sudo, kein `pmset`):
1. Mac zu den Zeiten wach halten: Systemeinstellungen → Batterie/Energie sparen → „Ruhezustand bei ausgeschaltetem Bildschirm
   verhindern“ (nur am Netzteil), oder der Mac bleibt beim Schlafengehen angeschlossen mit externem Monitor.
2. Mac automatisch aufwecken: Systemeinstellungen → Energie sparen → „Zeitplan…“ (Hochfahren/Aufwachen z. B. 07:55 und 21:55).
   Das macht dasselbe wie `pmset repeat wakeorpoweron` und braucht Administratorrechte.
3. 22:00 Berlin entspricht 16:00 Ostküste, also vor den Spielen (Anpfiff ab ca. 19:00 ET): die Linien sind Vorab-Quoten.
   08:00 liegt nach dem Ende der letzten Spiele (ca. 05–06 Uhr).
