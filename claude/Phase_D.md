# Phase D: App und Oberfläche (Streamlit-App, Tabs, Browser-Test, Verletzungsberichte)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase D" anhängen).

## Hintergrund (Stand 5.11.)
- Die App läuft lokal (localhost:8501): Tagesübersicht mit Anpfiffzeiten, Spielerkarten (Tab Spieler: Betano- und Modell-Prozente je Stufe, orange Balken = Modell roh, "Alle speichern", "✓ gesetzt"), Seitenleiste mit Odds-API-Credits und Betano-Automatik-Zeile, History-Tab.
- Tab Spieler im echten Browser am 30.10. geprüft und in Ordnung: anklickbare Karten, "Alle speichern" mit 9 Wetten, grünes ✓ mit Mindestquote bei Matas Buzelis 11+ @ 1,39, Warnung "nur 5 Spiele, Chance vermutlich zu hoch" mit ⚠ bei Caleb Wilson.
- Fraglich-Warnung auf den Karten wird nicht umgesetzt (Festlegung).
- Änderungen an der App brauchen danach den Gesamttestlauf (Befehl in Roadmap.md) und nbabackup.

## Offen
- [ ] 3.3 Anzeige, ob eine Quote von der Automatik (auto) oder von Hand (hand) kommt (Baran 2.11.: später).
- [ ] 3.3 Datumsauswahl für kommende Tage (bis 3 Tage, nur Modell), Vortag-Knopf, Spielzahl in der Liste, History-Tab Layout.
- [ ] 3.3 Idee (nicht entschieden): Warnhinweis auf der Spielerkarte, wenn das Team 3 oder mehr große Ausfälle hat (Modell rechnet ohne Ausfälle); erst nach weiterer Auswertung der Ausfall-Gruppen (Phase B).
- [ ] 3.1 browser_score_check.py ist seit 30.10. repariert (Ports, Uhrzeit, Kartenreihenfolge); feste Wartezeiten und Aufnahme in den Gesamtlauf offen.
- [ ] 3.6 Injury-Report-Archiv (PDF-Parser): nur wenn Zeit bleibt; für 2026-27 einzige bekannte Quelle für Inaktive.
- [ ] Bei einer Änderung des Meldungstexts "übersprungen (Handeingabe hat Vorrang)" (Phase A) die Sidebar und Tests mitprüfen.

## Erledigt (Kurzfassung, Details in den Archiven)
- Tab Spieler neu (Block 1), History-Tab, Wettliste, Spieltag-Logik, Feed-Änderung Spielstart.
- Sidebar-Zeile "Betano-Automatik" (3.2d), Tab Spieler: orange Balken = Modell roh (Entscheidung 29.10.), grünes ✓ nur für Starter mit mindestens 10 Spielen und Roh-Chance ab 80 %.
- 3.7: Teamabgleich in der App ausgeblendet (SHOW_TEAM_ADJUSTED = False).
- 3.11d: Tests der Sidebar und des Schalters Value Bets repariert (nur Tests).

## Startnachricht für eine neue Sitzung dieser Phase
Lies claude/Roadmap.md (Regeln) und claude/Phase_D.md (Hintergrund und offene Punkte). Details nur bei Bedarf in claude/Roadmap_Archiv.md und claude/Roadmap_Archiv_2.md. Schreibe nur in claude/Phase_D.md. Beginne mit Schritt 1 und stelle mir dann die erste Frage.

## Archiv Phase D (neue Details ab 6.11. hier anhängen)
