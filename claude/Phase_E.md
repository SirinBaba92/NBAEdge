# Phase E: Entscheidungen im Dezember (ca. 300 Spiele)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase E" anhängen). Diese Phase beginnt erst, wenn ca. 300 Spiele in der Auswertung sind (aktuell 108 am 5.11.).

## Hintergrund (Stand 5.11.)
- Ziel: verlässliche, kalibrierte Prognosen, nicht Betano schlagen. Das Modell bringt im Informationswert-Test bisher keinen belegten Zusatz zu Betano: 13 Tage, 91 Spiele, 1153 Spieler-Tage: Brier Betano 0,2194, Modell roh 0,2368, Teamabgleich 0,2423; Regression b2 roh -0,05 [-0,18; +0,08], Teamabgleich -0,10 [-0,22; +0,02] (beide Intervalle enthalten 0). Ausfälle erklären einen Teil des Abstands (Phase B), aber auch in Spielen ohne große Ausfälle liegt das Modell hinter Betano (+0,013).
- Das Testverfahren: Betano = 1/Quote inkl. Marge; Mischung mit dem Modell nach Gewicht w; Intervalle nach Spieler-Tagen (Spieler sind die unabhängigen Beobachtungen); Ergebnisse analysis/results/info_value_test.txt und .json; tägliche Zusammenfassung in der Morgenroutine.
- Entscheidungsregel: Stufe der Sicherheitsstufen nur ändern bei mindestens 100 Zeilen und mehr als 6 Prozentpunkten in zwei Monaten nacheinander.
- Value Bets sind ausgeschaltet. Der Teamabgleich ist in der App ausgeblendet; sein Code wird erst nach Entscheidung 6.7 entfernt.

## Offen (alle ab Dezember)
- [ ] 6.1 Informationswert-Test für Spread, Total, Team Total, Sieger (mit reinem Modellwert, seit 3.8 gespeichert)
- [ ] 6.2 Mischgewicht je Markt lernen
- [ ] 6.3 Linienbewegung und Schlusslinien-Vergleich
- [ ] 6.4 Wiederholungen mit Daten 2026-27: W4, H1, Gegner-Faktor D (nur Bank), Live-Prüfung 4.3 mit team-2; Option Kalibrierungstabelle; Zusatzfaktoren bestätigen; Ausfallbehandlung (Schritt 2 aus 3.11c, mit Phase B) mit mehr Spielen in Gruppe A
- [ ] 6.5 Schwellenwerte und Sicherheitsstufen prüfen (monatlicher Bericht zu den Sicherheitsstufen)
- [ ] 6.6 Entscheidung zu historischen Marktdaten
- [ ] 6.7 Entscheidung zu gemeinsamer Simulation, Risikobild und Aufbau von unten; danach Teamabgleich-Code entfernen und Kategorie "Teamabgleich" in den Auswahlfeldern umbenennen oder streichen (Aufräumpunkt)
- [ ] Am Ende gemeinsam: welche Wetten sind am besten gestützt (Block 8)

## Erledigt (Kurzfassung)
- Vorarbeiten: Informationswert-Test täglich in der Morgenroutine (seit 22.10.), reiner Modellwert in den Snapshots (3.8), Ausfall-Gruppen (3.11c, Phase B), Konsistenzprüfung Spielerpunkte gegen Team Total (99,5 %).

## Startnachricht für eine neue Sitzung dieser Phase
Lies claude/Roadmap.md (Regeln) und claude/Phase_E.md (Hintergrund und offene Punkte). Details nur bei Bedarf in claude/Roadmap_Archiv.md und claude/Roadmap_Archiv_2.md. Schreibe nur in claude/Phase_E.md. Beginne mit Schritt 1 und stelle mir dann die erste Frage.

## Archiv Phase E (neue Details ab 6.11. hier anhängen)
