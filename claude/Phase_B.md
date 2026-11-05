# Phase B: Spielerprognosen (Minuten, Verlängerung, Ausfälle, Rollen)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase B" anhängen).

## Hintergrund (Stand 5.11.)
- Die Spielerkarten rechnen seit 29.10. ohne Ausfälle (Snapshot ohne Neuberechnung, DESIGN_REGELN.md Regel 94; create_variant existiert, schreibt aber keine neuen Varianten). Grund: Die Neuberechnung mit Ausfällen schlug Roh in den Messungen im Mittel nicht (Archiv Teil A 1.6, 4.3).
- Pacers-Fall 2.11. (ATL @ IND, Brier Betano 0,2353, Modell roh 0,6355): vier Stammspieler fehlten schon vor dem Anpfiff in absences.json, der Snapshot ignorierte sie, Ersatzspieler spielten 34 bis 44 Minuten (Details Archiv_2, 3.11c).
- Ausfall-Gruppen (ab 22.10., 13 Tage): Gruppe A (Team mit mindestens 3 großen Ausfällen, 10 Spiele, 115 Spieler-Tage): Abstand Brier roh minus Betano +0,045, Verzerrung roh -12,0 PP; Gruppe B (78 Spiele): +0,013, +3,5 PP. A ist zu klein (Schwelle 150 Spieler-Tage), 5 von 10 A-Spielen sind Oklahoma City mit denselben drei Ausfällen (vermutlich langer Ausfall); auch in B liegt das Modell hinter Betano. Informationswert-Test (13 Tage): kein belegter Zusatz des Modells zu Betano (b2 roh -0,05 [-0,18; +0,08]).
- Verlängerung ist im Spielerpunkte-Modell vorab nicht enthalten (engine/player_forecast.py, Minuten auf 0 bis 48 begrenzt): Spielerpunkte-Chancen sind bei Verlängerung tendenziell zu niedrig, vor allem bei Overs. Beispiele: Pelicans–Grizzlies 2.11., Jazz–Pelicans und Heat–Clippers 4.11. (Wembanyama 52 statt 25,8 Punkte, Keyonte George 43,6 statt 30,3 Min., Adebayo 40,5 statt 33,8 Min.; Zusammenhang mit der Verlängerung nicht geprüft).

## Offen
- [ ] 4.4 Verlängerung in Spielerpunkte und Team-Verteilungen einbauen und testen (Wahrscheinlichkeit einer Verlängerung aus dem erwarteten Abstand, Minuten über 48); Vergleich auf beiden Hälften; Termin ab Mo 9.11. (zusammen mit Minutentests)
- [ ] 4.1 Vortest: bringt eine zweite Vorsaison als Ausgangswert bei Spielern etwas? Termin ab Mo 9.11.
- [ ] 5.7 Rollenwechsel testen (neu in der Startformation, Rückkehr); Termin ab Mo 16.11.
- [ ] Ausfallbehandlung (Schritt 2 aus 3.11c): Neuberechnung nur für die Auswertung wieder einschalten und gegen Roh vergleichen, aber erst, wenn Gruppe A deutlich größer ist (ca. Dezember, siehe auch Phase E). Möglicher Zusatztest: Gruppe A aufteilen in "langer Ausfall" (wie OKC) und "neuer Ausfall am selben Tag" (wie Pacers). Nicht gebaut.
- [ ] Idee (nicht entschieden, Oberfläche gehört zu Phase D): Warnhinweis auf der Spielerkarte, wenn das Team 3 oder mehr große Ausfälle hat.
- [ ] Spielerpunkte-Streuung und Minutenverteilung (4.2b war negativ): bei neuen Daten 2026-27 erneut ansehen, nur wenn Zeit.

## Erledigt (Kurzfassung, Details in den Archiven)
- 4.2a (Minutenkorrektur nach Abstand), 4.2b (empirische Minutenverteilung), 5.1 (Stufe 1 und 2), 2.3a: alle negativ, nichts eingebaut.
- 4.3 Umverteilung bei Ausfällen (real gemessen, Prompt Q): Rückfluss Minuten 0,31, Punkte 0,38, nahe an den Modellwerten (34 % / 41 %); nichts geändert.
- Aufstellungstabelle, Garbage Time G1, Konsistenzprüfung (Spielerpunkte decken 99,5 % der Teampunkte).
- 3.11c und 3.4: Pacers-Befund und Ausfall-Gruppen (analysis/ausfall_gruppen.py, tests/test_ausfall_gruppen.py 17 Fälle, analysis/results/ausfall_gruppen.txt), wöchentlich mittwochs neu laufen lassen (läuft über Phase A).

## Startnachricht für eine neue Sitzung dieser Phase
Lies claude/Roadmap.md (Regeln) und claude/Phase_B.md (Hintergrund und offene Punkte). Details nur bei Bedarf in claude/Roadmap_Archiv.md und claude/Roadmap_Archiv_2.md. Schreibe nur in claude/Phase_B.md. Beginne mit Schritt 1 und stelle mir dann die erste Frage.

## Archiv Phase B (neue Details ab 6.11. hier anhängen)
