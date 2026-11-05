# Phase C: Team-Märkte (team-2, Tempo, Moneyline, Spread, Total, Team Total)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase C" anhängen).

## Hintergrund (Stand 5.11.)
- Team-Märkte kommen aus Normalverteilungen mit festen Streuungen (Spread 13,2, Team Total 11,6, Total 18,6); die Siegchance ist Φ(erwarteter Spread / 13,2), begrenzt auf 3 bis 97 % (engine/line_probabilities.py, engine/projection.py). Es gibt zwei Formeln für die Siegchance (Normalverteilung und Elo-Logistik), die vor einem Wiedereinschalten der Value Bets angeglichen werden müssen (5.6).
- team-2 = Ausfall-Abzug für die Teamwerte (Spread, Total, Team Total, Sieger): nur Status "Fehlt", halbe gemessene Stärke des Ausgefallenen (Archiv 3.2). Mit den Spielerkarten hat es nichts zu tun.
- Messungen der Vorsaison zeigen gute Kalibrierung bei Spread und Team Total (Team Total 0,47 Prozentpunkte Abweichung); beim Total ein Anfangs-Bias von etwa 3 Punkten nur in 2025-26. Ausfälle erklären das Total nicht (Archiv 4.2).
- Value Bets sind ausgeschaltet (SHOW_VALUE_BETS = False). Der Teamabgleich ist in der App ausgeblendet (SHOW_TEAM_ADJUSTED = False), Berechnung läuft weiter.

## Offen
- [ ] 3.5 team-2 auswerten, erste Kalibrierung (108 Spiele in der Auswertung erreicht am 5.11.). Genaues Vorgehen gemeinsam festlegen, bevor etwas gebaut wird. Offen ist, was für team-2 in 2026-27 überhaupt gespeichert wird (mit und ohne team-2?), in wie vielen Spielen es einen Abzug gab und ob die Fälle für eine Kalibrierung reichen. Nächster Schritt: den lesenden Inventar-Prompt unten ausführen, dann mit den Zahlen entscheiden.
- [ ] 5.3 Tempo-Test beim Total und Streuung des Teams (Hängt der Total-Fehler mit dem Tempo-Mix der beiden Teams zusammen? Streuung gegen erwartete Totalhöhe, Spreadgröße, Saisonphase, Verlängerung; Regel: auf beiden Saisonhälften besser); Termin ab Mo 16.11.
- [ ] 5.4 Betano-Marge je Markt messen, Abschlag von 3 Prozentpunkten prüfen; ab Mo 16.11.
- [ ] 5.5 Moneyline: Saisonübergang, Aufstellungsstärke; ab Mo 16.11.
- [ ] 5.8 Spread, Total, Team Total mit Aufstellungsdaten erneut prüfen; ab Mo 16.11.
- [ ] 5.6 Kleine Genauigkeitspunkte: Rundung (kostet bis zu 0,5 Punkte), Push und Kontinuitätskorrektur, die zwei Siegchancen angleichen (vor den Value Bets); ab Mo 16.11.
- [ ] Verlängerung auch in den Team-Verteilungen (gehört zu 4.4 in Phase B, hier nur abstimmen).

## Vorbereiteter Inventar-Prompt für 3.5 (noch nicht ausgeführt)
Nur lesen und untersuchen. Keine Änderung an App, Tests, Daten oder Plist. Keine Netzabrufe. Den launchd-Job nicht anfassen.
Ziel: Für Punkt 3.5 (team-2 auswerten, erste Kalibrierung) klären, was für team-2 in der Saison 2026-27 an Daten vorhanden ist. team-2 = Ausfall-Abzug für die Teamwerte, nur Status "Fehlt", halbe gemessene Stärke (Roadmap_Archiv.md, 3.2). Mit den Spielerkarten hat es nichts zu tun (dort rechnet der Snapshot seit 29.10. ohne Ausfälle, Regel 94).
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
