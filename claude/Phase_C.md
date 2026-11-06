# Phase C: Team-Märkte (team-2, Tempo, Moneyline, Spread, Total, Team Total)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase C" anhängen).

## Hintergrund (Stand 5.11.)
- Team-Märkte kommen aus Normalverteilungen mit festen Streuungen (Spread 13,2, Team Total 11,6, Total 18,6); die Siegchance ist Φ(erwarteter Spread / 13,2), begrenzt auf 3 bis 97 % (engine/line_probabilities.py, engine/projection.py). Es gibt zwei Formeln für die Siegchance (Normalverteilung und Elo-Logistik), die vor einem Wiedereinschalten der Value Bets angeglichen werden müssen (5.6).
- team-2 = Ausfall-Abzug für die Teamwerte (Spread, Team Total, Sieger; das Total bleibt gleich): nur Status "Fehlt", halbe gemessene Stärke des Ausgefallenen (engine/team_injury.py; Roadmap_Archiv.md Z. 358, dort unter dem Schritt "Minuten verteilen", Unterpunkt Umverteilung bei Ausfällen; "3.2" im Archiv ist sonst die Betano-Automatik). Mit den Spielerkarten hat es nichts zu tun.
- Messungen der Vorsaison zeigen gute Kalibrierung bei Spread und Team Total (Team Total 0,47 Prozentpunkte Abweichung); beim Total ein Anfangs-Bias von etwa 3 Punkten nur in 2025-26. Ausfälle erklären das Total nicht (Archiv 4.2).
- Value Bets sind ausgeschaltet (SHOW_VALUE_BETS = False). Der Teamabgleich ist in der App ausgeblendet (SHOW_TEAM_ADJUSTED = False), Berechnung läuft weiter.

## Offen
- [ ] 3.5 team-2 auswerten, erste Kalibrierung. Inventar am 5.11. gemacht (Bericht analysis/results/team2_inventar.txt, Details im Archiv Phase C): 55 Spiele mit team2-Block (seit 27.10.), 52 mit Abzug, Mittel 1,2 Punkte Spread-Verschiebung, Maximum 3,6. Das Total bleibt unverändert; team-2 ändert nur Spread, Team Total und Sieger. Für eine Kalibrierung des Faktors (0,25 / 0,5 / 0,75) reichen 55 Spiele nicht (Standardfehler ca. 0,7 im Faktor); erst ab ca. 300 bis 500 Spielen (etwa Ende Dezember, Phase E). Jetzt nur Plausibilitätscheck möglich. Nächster Schritt: mit Baran besprechen (Vorschläge im Archiv Phase C).
- [ ] 3.5a Auffälligkeit prüfen: ab 3.11. kein Spiel mehr mit Abzug > 0 (3 Spiele ohne Abzug). Ob das echt ist (keine "Fehlt"-Spieler) oder ein Fehler, ist nicht geprüft.
- [ ] 5.3 Tempo-Test beim Total und Streuung des Teams (Hängt der Total-Fehler mit dem Tempo-Mix der beiden Teams zusammen? Streuung gegen erwartete Totalhöhe, Spreadgröße, Saisonphase, Verlängerung; Regel: auf beiden Saisonhälften besser); Termin ab Mo 16.11.
- [ ] 5.4 Betano-Marge je Markt messen, Abschlag von 3 Prozentpunkten prüfen; ab Mo 16.11.
- [ ] 5.5 Moneyline: Saisonübergang, Aufstellungsstärke; ab Mo 16.11.
- [ ] 5.8 Spread, Total, Team Total mit Aufstellungsdaten erneut prüfen; ab Mo 16.11.
- [ ] 5.6 Kleine Genauigkeitspunkte: Rundung (kostet bis zu 0,5 Punkte), Push und Kontinuitätskorrektur, die zwei Siegchancen angleichen (vor den Value Bets); ab Mo 16.11.
- [ ] Verlängerung auch in den Team-Verteilungen (gehört zu 4.4 in Phase B, hier nur abstimmen).

## Vorbereiteter Inventar-Prompt für 3.5 (ausgeführt am 5.11., Ergebnis siehe Archiv Phase C)
Nur lesen und untersuchen. Keine Änderung an App, Tests, Daten oder Plist. Keine Netzabrufe. Den launchd-Job nicht anfassen.
Ziel: Für Punkt 3.5 (team-2 auswerten, erste Kalibrierung) klären, was für team-2 in der Saison 2026-27 an Daten vorhanden ist. team-2 = Ausfall-Abzug für die Teamwerte, nur Status "Fehlt", halbe gemessene Stärke (Roadmap_Archiv.md Z. 358; nicht "3.2" = Betano-Automatik). Mit den Spielerkarten hat es nichts zu tun (dort rechnet der Snapshot seit 29.10. ohne Ausfälle, Regel 94).
Prüfe der Reihe nach, melde je Punkt Ergebnis oder "nicht geprüft":
1. Wo ist team-2 im Code (grep nach team-2, team2, team_injury, Ausfall-Abzug im Team-Modell; Dateien und Zeilen) und wie genau rechnet es (Abzug in Punkten, Formel, Faktor 0,5)?
2. Wo werden die Team-Prognosen je Spiel gespeichert (projection_snapshots.json oder anderswo)? Wird dort der Wert MIT und OHNE team-2 gespeichert, oder nur einer? Seit welchem Datum? (Das reine Modell ohne Marktanteil wird seit 3.8 mitgespeichert, gilt das auch für team-2?)
3. Für wie viele Spiele ab 22.10. (Prognose vor Anpfiff, Ergebnis vorhanden) hat team-2 überhaupt etwas abgezogen? Verteilung der Abzüge in Punkten (Anzahl Spiele, Mittel, Maximum, Spiele mit Abzug von mindestens 1 und mindestens 2 Punkten).
4. Welche vorhandenen Auswertungsskripte (analysis/) bewerten Spread, Total, Team Total und Sieger gegen die Ergebnisse, und laufen sie mit Daten 2026-27? Wo liegen die Berichte (analysis/results/)?
5. Lässt sich aus den gespeicherten Daten ein Vergleich "mit team-2 gegen ohne team-2 gegen Ergebnis" rechnen? Wenn nein: was fehlt (welche Werte müssten gespeichert werden)?
6. Reichen die Fälle aus Punkt 3 für eine Kalibrierung des Faktors (zum Beispiel 0,25 / 0,5 / 0,75)? Nur grob schätzen, mit Zahlen aus Punkt 3, und die Einschränkung nennen.
Ergebnis in analysis/results/team2_inventar.txt. Höchstens 15 Zeilen zurückmelden. Keine neuen Tests, nichts ausführen, was Daten schreibt.
Kein Commit, keine Pushes, kein Backup. Das mache ich selbst mit nbabackup.

## Erledigt (Kurzfassung, Details in den Archiven)
- Messungen Moneyline, Spread, Total, Team Total, Spielerpunkte (Vorsaison), Sicherheitsstufen, Betano-Quoten in den Karten.
- 3.7 (30.10.): Teamabgleich in der App ausgeblendet, Live-Chance startet mit Roh.
- 5.2 Gegner, Tempo, Heim/Auswärts: negativ, nichts eingebaut (Folgetest bei neuen Daten in Phase E, 6.4).
- Informationswert-Test (13 Tage, 91 Spiele): Brier Betano 0,2194, Modell roh 0,2368, Teamabgleich 0,2423; Zusatz des Modells nicht belegt (läuft über Phase A und E).

## Startnachricht für eine neue Sitzung dieser Phase
Lies claude/Roadmap.md (Regeln) und claude/Phase_C.md (Hintergrund und offene Punkte). Details nur bei Bedarf in claude/Roadmap_Archiv.md und claude/Roadmap_Archiv_2.md. Schreibe nur in claude/Phase_C.md. Beginne mit Schritt 1 und stelle mir dann die erste Frage.

## Archiv Phase C (neue Details ab 6.11. hier anhängen)

### 5.11. Inventar team-2 (Punkt 3.5), Bericht analysis/results/team2_inventar.txt
Nur gelesen, nichts geändert. Gelesen wurde der Bericht (Stand projection_snapshots.json vom 5.11. 03:44); die Zahlen habe ich nicht selbst nachgerechnet.
- Code: engine/team_injury.py (SLOPE -14,4, FACTOR 0,5, MIN_TEAM_GAMES 10, TOP_N 8). Maß = Summe der Punkteanteile der "fehlt"-Spieler aus den Top 8 nach Minuten; "fraglich" zählt nicht. Abzug delta = 0,5 * (-14,4) * (Maß Heim - Maß Gast) auf den Heim-Spread, Heim +delta/2, Gast -delta/2. Total unverändert. Anbindung app.py:639-644, Anzeige ui/score_cards.py:242-245, ui/score_history.py:54-71.
- Herkunft der Steigung: analysis/reports/winner_injuries_2025-26.txt (1075 Spiele, -14,44, 95 %: -17,8 bis -11,1; Obergrenze, Wissen aus der Zukunft).
- Speicherung: data/tracking/projection_snapshots.json, Block "team2" je Version seit 27.10. 07:19; gespeichert sind mit und ohne team-2 (aber "ohne" = Marktmischwert, kein reines Modell). Reines Modell (model_spread usw.) seit 30.10. in "projection", team2-Variante darauf fehlt (nachrechenbar für 36 von 55 Spielen).
- Abzüge: 93 Spiele ab 22.10. mit Ergebnis, 55 mit Block (alle Basis "Vorjahr"). 52 mit Abzug > 0; Mittel 1,18 (alle) bzw. 1,24 (nur Abzug); Maximum 3,58; >= 1 Punkt: 28 Spiele; >= 2 Punkte: 11; beide Teams mit Maß > 0: 27. Nach Tag: 27.10 3, 28.10 12, 29.10 3, 30.10 9, 31.10 6, 1.11 4, 2.11 15; ab 3.11. keine mit Abzug > 0.
- Auswertungsskripte: kein Skript bewertet den team2-Block gegen 2026-27-Ergebnisse. eval_snapshots.py nutzt nicht den Block; alle Backtests laufen auf Saisons bis 2025-26.
- Vergleich mit/ohne gegen Ergebnis: für 55 Spiele rechenbar (Spread, Team Total, Sieger). Fehlt: team2 auf Basis des reinen Modells; nur ein Faktor gespeichert (0,25 / 0,75 aus Maß und SLOPE nachrechenbar, Siegchance neu über lp.win_prob_home); Spiele vor 27.10. ohne Block; Ausfallstatus-Verlauf nur als letzter Stand in absences.json (unklar, ob "fehlt" zum Prognosezeitpunkt stimmte).
- Kalibrierung: nicht belastbar. n = 55, Streuung der Maß-Differenz 0,20, Modellfehler ca. 14,9 Punkte -> Standardfehler der Steigung ca. 10 Punkte je 1,0 Maß, im Faktor ca. 0,7. Unterschiede 0,25 / 0,5 / 0,75 liegen weit darunter. Mittlerer Abzug 1,2 gegen Spread-Streuung 13,2: Brier-Wirkung klein. Bei 300 bis 500 Spielen Standardfehler ca. 0,25 bis 0,3: erst dann unterscheidbar. Die 1075 Spiele aus 2025-26 bleiben die bessere Basis.
- Hinweis aus dem Bericht (Archiv nicht im Projekt) ist überholt: Archive liegen in claude/. Abgleich mit Code siehe unten (5.11.).
- Korrektur zur Aufgabenbeschreibung: team-2 ändert das Total nicht (nur Spread, Team Total, Sieger).

### 5.11. Abgleich Roadmap_Archiv.md Z. 358 mit dem Code
- Stelle (Z. 358, Schritt "Minuten verteilen", Unterpunkt "Umverteilung bei Ausfällen"): "team-2 für Teamwerte (nur Status Fehlt, halbe gemessene Stärke)". Die Überschrift "3. Datensammlung nach dem Buchmacher-Ablauf" habe ich dort nicht gefunden; die Zeile steht unter "Schritt 3: Minuten verteilen" (Z. 348).
- Code (engine/team_injury.py): nur Status "fehlt" (Z. 3, 144-146), FACTOR = 0,5 (Z. 22) auf die gemessene Steigung -14,4. Das stimmt mit der Archivzeile überein.
- Abweichung nur in Phase_C.md: Dort stand "Spread, Total, Team Total, Sieger". Der Code lässt das Total gleich (Z. 11, 109, 113); korrigiert.
- Verweis "Archiv 3.2" in Phase_C.md war falsch ("3.2" = Betano-Automatik, Archiv Z. 203); korrigiert auf Z. 358. Die Archivzeile selbst nenne ich "Unterpunkt Umverteilung bei Ausfällen" im Schritt "Minuten verteilen".
- Nicht geprüft: Archiv-Text der Messung der Steigung (4.3, Archiv Z. 100) im Detail.
