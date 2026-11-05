# NBAEdge (Projektanweisung für Claude Code)

NBA-Wettanalyse von Baran: Python/Streamlit-App (localhost:8501), virtuelle Bankroll, KEIN Echtgeld. Projektordner `~/Desktop/NBAEdge`, Python immer `venv/bin/python`.
Ziel: verlässliche, kalibrierte Prognosen (nicht Betano schlagen).

## Wie du mit Baran arbeitest
- Antworte auf Deutsch, einfach und kurz. Immer nur eine Frage und ein Schritt auf einmal.
- Zu jeder Frage schreibst du deine Empfehlung dazu. Sagt Baran "du entscheidest", "entscheide du" oder "weiter", gilt die Empfehlung.
- Erst besprechen, dann ändern. Keine Änderung an App, Daten oder Tests ohne vorherige Absprache.
- Sag ehrlich, was geprüft ist und was nur vermutet ist. Nichts erfinden. Wenn du etwas nicht weißt: nachsehen oder "nicht geprüft" schreiben.
- Rückmeldungen höchstens ca. 15 Zeilen: Ursache (Datei, Zeile), was geändert wurde, Ergebnisse, welche Tests liefen.
- Kein Commit, kein Push, kein Backup. Das macht Baran selbst mit `nbabackup`. Frag ihn nie danach.
- Gesamttestlauf macht Baran selbst (11 bis 18 Minuten, währenddessen Claude Code nicht nutzen). Du lässt nur neue oder direkt betroffene Tests laufen.
- Keine Netzabrufe zu Betano, ESPN oder der Odds API ohne ausdrückliche Erlaubnis.
- Das echte Plist in ~/Library/LaunchAgents und den echten launchd-Job nie anfassen (nicht kopieren, laden, löschen).
- Echte Daten (data/, data/tracking, Modelle) nie ändern, außer es ist ausdrücklich Teil der Aufgabe.
- Jeder Punkt: Daten beschaffen -> testen -> entscheiden. Positiv = behalten. Negativ = ausführlich ins Archiv der Phase, in der Aufräumliste (Phase A) eine Zeile.
- "Festgelegt" heißt nur: was und wann. Ob etwas etwas bringt, entscheiden wir nach dem Test.

## Befehle
- Projekt: `cd ~/Desktop/NBAEdge`
- Shell-Befehle von Baran: `aufzeichnen` (Recorder, ~30 Min. vor dem ersten Anpfiff starten, Fenster offen lassen), `betano` (Handabruf kurz vor Spielbeginn), `morgenroutine` (Aufzeichnungsprüfung, Liga-Datei, Auswertung, Informationswert-Test, Backup), `nbabackup` (nur Baran).
- Elo-Update: `venv/bin/python update_model.py` (läuft täglich 08:00 per launchd, Daten von api.balldontlie.io, 2 Tage Überlappung holen verpasste Spiele nach).
- Aufzeichnungsprüfung: `venv/bin/python analysis/check_recordings.py <US-Tag>` (Ordner ~/NBAEdge_live_history)
- Mittwochs: Informationswert-Test ansehen und `venv/bin/python analysis/ausfall_gruppen.py`.
- Einzeltest: `venv/bin/python tests/test_xyz.py` (zählt FAIL-Zeilen). `test_snapshots_helpers` braucht `PYTHONPATH=.`
- Gesamttestlauf (nur Baran):
  `cd ~/Desktop/NBAEdge && for t in tests/test_*.py; do echo "$(basename $t .py) FAIL=$(venv/bin/python $t 2>&1 | grep -c '^FAIL')"; done | grep -v "FAIL=0"; echo FERTIG`

## Roadmap (Quelle der Wahrheit liegt im Repo-Ordner `claude/`)
- `claude/Roadmap.md`: Übersicht, Regeln, Festlegungen, Stand der Zahlen. Immer zuerst lesen.
- `claude/Phase_A.md` Betrieb (täglich) | `Phase_B.md` Spielerprognosen | `Phase_C.md` Team-Märkte | `Phase_D.md` App/Oberfläche | `Phase_E.md` Entscheidungen im Dezember (ab ca. 300 Spiele) | `Phase_F.md` Januar und später.
- `claude/Roadmap_Archiv.md` (bis 1.11.) und `claude/Roadmap_Archiv_2.md` (2. bis 5.11.): eingefroren, nur bei Bedarf lesen, nie beschreiben.
- Pro Sitzung eine Phase: erst Roadmap.md, dann die Phasen-Datei. Schreibe nur in die Datei deiner Phase. Neue Details unten in den Abschnitt "Archiv Phase X", oben nur offene Punkte und Ein-Satz-Ergebnisse. Roadmap.md nur ändern, wenn Baran es ausdrücklich will.
- Was bei einer anderen Phase gebraucht wird, sagst du Baran als Hinweis, du schreibst nicht in deren Datei.
- Pflege deine Phasen-Datei nach jedem Schritt.

## Festlegungen (Kurzfassung, Details in Roadmap.md)
- Betano-Abruf kurz vor Spielbeginn, Automatik stündlich (`betano_auto.py`, launchd, speichert source="auto"); Hand-Linien bleiben immer unberührt; Stopp bei 429 (6 h Pause) und 403 (AUS bis --reset).
- Abruf-Prompts nie gleichzeitig; Downloads nur tagsüber, nie nachts während der Aufzeichnung.
- Keine Wetten auf Rebounds, Assists, Dreier.
- Prognosen für alle Spiele vor dem ersten Anpfiff des Spieltags erstellen. Kein Knopf "Prognose erstellen" mehr, sobald ein Spiel eine Prognose hat.
- Spielerkarten rechnen seit 29.10. ohne Ausfälle (DESIGN_REGELN.md Regel 94). Value Bets aus (SHOW_VALUE_BETS=False), Teamabgleich ausgeblendet (SHOW_TEAM_ADJUSTED=False).
- Kein Backup für NBAEdge_pbp.
- Ohne Spiele am US-Tag keine Morgenroutine nötig.

## Startablauf einer Sitzung
Lies `claude/Roadmap.md` und die Phasen-Datei, die Baran nennt (Standard: Phase A). Beginne mit dem ersten Schritt und stelle Baran dann die erste Frage.
