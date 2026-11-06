# Phase B: Spielerprognosen (Minuten, Verlängerung, Ausfälle, Rollen)

Stand: Do 5.11.2026, 22:00. Gemeinsame Regeln und Festlegungen: claude/Roadmap.md. Details bis 5.11.: Roadmap_Archiv.md und Roadmap_Archiv_2.md (nur bei Bedarf lesen, nicht mehr beschreiben). Diese Sitzung schreibt nur diese Datei (neue Details unten im Abschnitt "Archiv Phase B" anhängen).

## Hintergrund (Stand 5.11.)
- Die Spielerkarten rechnen seit 29.10. ohne Ausfälle (Snapshot ohne Neuberechnung, DESIGN_REGELN.md Regel 94; create_variant existiert, schreibt aber keine neuen Varianten). Grund: Die Neuberechnung mit Ausfällen schlug Roh in den Messungen im Mittel nicht (Archiv Teil A 1.6, 4.3).
- Pacers-Fall 2.11. (ATL @ IND, Brier Betano 0,2353, Modell roh 0,6355): vier Stammspieler fehlten schon vor dem Anpfiff in absences.json, der Snapshot ignorierte sie, Ersatzspieler spielten 34 bis 44 Minuten (Details Archiv_2, 3.11c).
- Ausfall-Gruppen (ab 22.10., 13 Tage): Gruppe A (Team mit mindestens 3 großen Ausfällen, 10 Spiele, 115 Spieler-Tage): Abstand Brier roh minus Betano +0,045, Verzerrung roh -12,0 PP; Gruppe B (78 Spiele): +0,013, +3,5 PP. A ist zu klein (Schwelle 150 Spieler-Tage), 5 von 10 A-Spielen sind Oklahoma City mit denselben drei Ausfällen (vermutlich langer Ausfall); auch in B liegt das Modell hinter Betano. Informationswert-Test (13 Tage): kein belegter Zusatz des Modells zu Betano (b2 roh -0,05 [-0,18; +0,08]).
- Verlängerung ist im Spielerpunkte-Modell vorab nicht enthalten (engine/player_forecast.py, Minuten auf 0 bis 48 begrenzt): Spielerpunkte-Chancen sind bei Verlängerung tendenziell zu niedrig, vor allem bei Overs. Beispiele: Pelicans–Grizzlies 2.11., Jazz–Pelicans und Heat–Clippers 4.11. (Wembanyama 52 statt 25,8 Punkte, Keyonte George 43,6 statt 30,3 Min., Adebayo 40,5 statt 33,8 Min.; Zusammenhang mit der Verlängerung nicht geprüft).

## Offen
- [ ] 5.7 Beobachten (eingebaut 6.11. abends, Version player-2): Gesamttestlauf durch Baran, Streamlit neu starten; nach einigen Spieltagen mit Version player-2 den Informationswert-Test ansehen (Rollenwechsel-Zeilen getrennt).
- [ ] Ideen Phase B (Vorschläge Claude 6.11., Baran will sie am 7.11. nacheinander mit den anderen Punkten durchgehen; Empfehlung: 1 und 2 zuerst; vorher in den Archiven prüfen, ob 3 und 4 schon getestet wurden):
  - [ ] B1 Rollenwechsel verfeinern: Faktor 0,565 getrennt für "mehr Minuten" und "weniger Minuten", Schwelle 5 Min. prüfen, Gegenprobe mit Saison 2023-24.
  - [ ] B2 Rückkehr nach längerer Pause getrennt testen (aus Lücken zwischen den Spieldaten, ohne Startformation).
  - [ ] B3 Halbwertszeit der Spielgewichte (heute HALF_LIFE_GAMES = 8) kürzer testen (Anlass: Modell reagiert bei Rollenwechsel zu langsam). Nicht geprüft, ob früher getestet.
  - [ ] B4 Back-to-Back und Ruhetage bei Spielerminuten (für den Sieger-Teil gibt es backtest_winner_rest_travel; für Spielerminuten nicht geprüft, ob getestet).
  - [ ] B5 Punkte pro Minute: Bias Punkte auch ohne Rollenwechsel -0,17, ansehen.
- [ ] Ausfallbehandlung (Schritt 2 aus 3.11c): Neuberechnung nur für die Auswertung wieder einschalten und gegen Roh vergleichen, aber erst, wenn Gruppe A deutlich größer ist (ca. Dezember, siehe auch Phase E). Möglicher Zusatztest: Gruppe A aufteilen in "langer Ausfall" (wie OKC) und "neuer Ausfall am selben Tag" (wie Pacers). Nicht gebaut.
- [ ] Idee (nicht entschieden, Oberfläche gehört zu Phase D): Warnhinweis auf der Spielerkarte, wenn das Team 3 oder mehr große Ausfälle hat.
- [ ] Spielerpunkte-Streuung und Minutenverteilung (4.2b war negativ): bei neuen Daten 2026-27 erneut ansehen, nur wenn Zeit.

## Erledigt (Kurzfassung, Details in den Archiven)
- 5.7 Rollenwechsel-Korrektur (6.11., positiv, eingebaut als player-2): Minutenmittel + 0,565 x (Mittel letzte 5 minus Mittel) bei Hinweis und mind. 10 Spielen; Brier der betroffenen Zeilen -0,0068 (beide Saisonhälften); Archiv Phase B.
- 4.1 Zweite Vorsaison (6.11.): formal positiv (Brier -0,0007 bei 0 bis 4 Saisonspielen, Intervall ohne 0), aber vernachlässigbar klein (ca. 0,6 %), Minuten unverändert; nichts eingebaut (Entscheidung Claude, Baran "du entscheidest"; Archiv Phase B, 6.11. Schritte 1 bis 3).
- 4.4 Verlängerung (negativ, 6.11.): Effekt real (Stammspieler bei Verlängerung +5,6 Min., +2,8 Punkte, 173 Spiele in 3 Saisons), aber vorab kaum vorhersagbar (Rate 4,7 %, aus Abstand Brier-Gewinn ca. 0,00006) und im Mittel nur ca. +0,13 Punkte; nichts eingebaut (Archiv Phase B, Schritte 1 bis 4).
- 4.2a (Minutenkorrektur nach Abstand), 4.2b (empirische Minutenverteilung), 5.1 (Stufe 1 und 2), 2.3a: alle negativ, nichts eingebaut.
- 4.3 Umverteilung bei Ausfällen (real gemessen, Prompt Q): Rückfluss Minuten 0,31, Punkte 0,38, nahe an den Modellwerten (34 % / 41 %); nichts geändert.
- Aufstellungstabelle, Garbage Time G1, Konsistenzprüfung (Spielerpunkte decken 99,5 % der Teampunkte).
- 3.11c und 3.4: Pacers-Befund und Ausfall-Gruppen (analysis/ausfall_gruppen.py, tests/test_ausfall_gruppen.py 17 Fälle, analysis/results/ausfall_gruppen.txt), wöchentlich mittwochs neu laufen lassen (läuft über Phase A).

## Startnachricht für eine neue Sitzung dieser Phase
Lies claude/Roadmap.md (Regeln) und claude/Phase_B.md (Hintergrund und offene Punkte). Details nur bei Bedarf in claude/Roadmap_Archiv.md und claude/Roadmap_Archiv_2.md. Schreibe nur in claude/Phase_B.md. Beginne mit Schritt 1 und stelle mir dann die erste Frage.

## Archiv Phase B (neue Details ab 6.11. hier anhängen)

### 5.11. Schritt 1 zu 4.4: Wie oft kommt Verlängerung vor? (lesend)
Quelle: ~/NBAEdge_live_history/*/*/result.json (Feld went_to_overtime). 118 aufgezeichnete Spiele (21.10. bis 4.11.), davon 7 mit Verlängerung (5,9 %), alle nur mit einer Verlängerung (ot_count 1). Pro Tag 0 bis 2 (4.11.: 2 von 14). Hinweis: 118 Aufzeichnungen sind mehr als die 108 Spiele in der Auswertung; welche Spiele die Auswertung nicht enthält, ist hier nicht geprüft. Noch nicht geprüft: wie weit Minuten und Punkte in diesen 7 Spielen über dem Modell lagen.

### 5.11. Schritt 2 zu 4.4: Minuten und Punkte in Spielen mit Verlängerung (lesend)
Methode: Snapshots (analysis/results/forecast_snapshots) mit Ergebnissen aus dem Recorder-Boxscore (eval_player_forecasts.game_results, nur lesen), Verlängerung aus result.json. Skript nur im Scratchpad (ot_check.py), nichts im Projekt geändert. Spieler mit Modell-Minuten > 0 und Ist-Minuten > 0, Punkte = Modell roh.
- Ohne Verlängerung: 101 Spiele, 1287 Spieler: Minuten Ist minus Modell +1,60, Punkte Ist minus Modell roh -0,81. Nur Spieler mit Modell >= 25 Min. (782): Minuten -0,35, Punkte -0,91.
- Mit Verlängerung: 7 Spiele, 92 Spieler: Minuten +5,13, Punkte +0,82. Nur Modell >= 25 Min. (55): Minuten +5,56, Punkte +2,30.
- Unterschied Verlängerung gegen keine: alle Spieler ca. +3,5 Min. und +1,6 Punkte; Spieler >= 25 Min. ca. +5,9 Min. und +3,2 Punkte.
- Einschränkungen: nur 7 Spiele, 55 Stammspieler (stark korreliert innerhalb eines Spiels), keine Streuung/Intervall gerechnet; Verlängerungsspiele sind oft enge Spiele (Spielausgang nicht getrennt); die +1,6 Min. ohne Verlängerung für alle Spieler sind vermutlich Auswahl (nur Spieler mit Einsatz), nicht untersucht.

### 5.11. Schritt 3 zu 4.4: Verlängerung in den drei Vorsaisons (lesend)
Quelle: ~/NBAEdge_pbp/boxscore/<Saison>/ (Feld period minus regulationPeriods) und ~/NBAEdge_pbp/derived/forecast_players_<Saison>.csv.gz (rückgerechnete Prognosen, Modell roh). Skript nur im Scratchpad (ot_season.py), nichts im Projekt geändert, kein Netz.
- Verlängerungsrate: 2023-24 59 von 1230 (4,8 %), 2024-25 60 (4,9 %), 2025-26 54 (4,4 %); mehr als eine Verlängerung: 8, 4, 8 Spiele. Zusammen 173 von 3690 (4,7 %).
- Spieler mit Modell >= 25 Min., Ist minus Modell, je Spiel gemittelt: ohne Verlängerung (3501 Spiele, 32559 Spieler) Minuten -0,74, Punkte -0,24; mit Verlängerung (173 Spiele, 1609 Spieler) Minuten +4,84, Punkte +2,55.
- Unterschied: Minuten +5,58 (95 %-Intervall Bootstrap über Spiele +4,99 bis +6,09), Punkte +2,79 (+2,41 bis +3,17). Passt zu den 7 Spielen 2026-27 (ca. +6 Min., +3 Pkt.).
- Einschränkung: Das ist der Effekt, WENN eine Verlängerung stattfindet (im Nachhinein bekannt). Ob das Modell vorab die Wahrscheinlichkeit einer Verlängerung (ca. 4,7 %, vermutlich höher bei engem erwarteten Abstand) nutzbar vorhersagen kann, ist nicht geprüft. Erwarteter Zusatz im Mittel über alle Spiele nur ca. 0,047 x 2,8 = 0,13 Punkte je Stammspieler.

### 6.11. Schritt 4 zu 4.4: Lässt sich eine Verlängerung aus dem erwarteten Abstand vorhersagen? (lesend)
Quelle wie Schritt 3 (3675 Spiele mit Prognose, 3 Vorsaisons; 15 Spiele 2023-24 ohne Spielerprognose fehlen). Skript nur im Scratchpad (ot_spread.py), nichts im Projekt geändert. Abstand = |tspread| aus forecast_players (erwarteter Punkteabstand).
- Rate nach Abstand: 0-2: 5,5 % (903 Spiele) | 2-4: 5,3 % (791) | 4-6: 3,9 % (648) | 6-8: 6,5 % (480) | 8-10: 3,2 % (371) | 10-13: 2,1 % (335) | ab 13: 4,1 % (147). Grundrate 4,7 %.
- Tendenz fallend (eng ca. 5,5 %, groß ca. 2 bis 4 %), aber unruhig (6-8 höher als 4-6), je Gruppe nur 6 bis 50 Verlängerungen.
- Einfache logistische Anpassung (nur in der Stichprobe, nicht getrennt getestet): Steigung -0,047 je Punkt Abstand; Brier Grundrate 0,04486, mit Abstand 0,04480, also Gewinn ca. 0,00006 (praktisch null).
- Folgerung (Vermutung, nicht weiter geprüft): Die Wahrscheinlichkeit einer Verlängerung ist aus dem Abstand kaum besser als mit der Grundrate vorhersagbar. Bei fester Rate wäre der Zusatz im Mittel ca. +0,13 Punkte je Stammspieler, bei engen Spielen ca. +0,15, bei klaren ca. +0,08. Vorschlag: 4.4 negativ abschließen, nichts einbauen (Entscheidung von Baran offen).

### 6.11. Schritt 1 zu 4.1: Wie wird der Ausgangswert gebildet, wen betrifft eine zweite Vorsaison? (lesend)
Code: engine/player_forecast.py game_weights (Zeilen 75-93): Anteil laufende Saison = n / (n + PRIOR_GAMES_K), PRIOR_GAMES_K = 8; der Rest gehört allen Spielen der Vorsaison (alles was nicht "laufende Saison" ist, innerhalb exponentiell fallend, HALF_LIFE_GAMES). Geladen werden nur 2025-26 und 2026-27 (data/player_history.py, SEASONS_TO_LOAD). Eine zweite Vorsaison (2024-25) gibt es für die Live-Prognose also nicht; lokal liegt sie in data/cache/backtest_player_games_2024-25.json und ~/NBAEdge_pbp/derived/forecast_players_2024-25.csv.gz (Rückrechnung).
Zahlen 2026-27 (Stand 6.11., lesend): 452 Spieler mit Einsatz, Median 7 Spiele, Maximum 9; 415 von 452 haben höchstens 8 Spiele (also Anteil laufende Saison höchstens 50 %). 61 Spieler ohne Einsatz in 2025-26 (Neulinge/Rückkehrer; für sie würde auch eine zweite Vorsaison nur bei Spielern mit Einsatz 2024-25 helfen, nicht geprüft).
Folgerung (Vermutung): Der Test ist in der frühen Saison relevant, weil fast alle Spieler noch stark auf der Vorsaison beruhen; er verliert an Wirkung, je mehr Spiele die Saison hat. Prüfen lässt er sich mit den Rückrechnungen der Vorsaisons (z. B. 2025-26 früh mit/ohne 2024-25 als zweite Vorsaison).

### 6.11. Schritt 2 zu 4.1: Testplan (Entwurf, Baran "du entscheidest") und Datenprüfung
Datenprüfung (lesend): data/cache/backtest_player_games_2023-24.json (26401 Zeilen, 572 Spieler, 160 Spieltage) und _2024-25.json (26306 Zeilen, 569 Spieler, 163 Spieltage) sowie data/cache/player_games_2025-26.json (26651 Zeilen) haben dieselben Felder (date, person_id, minutes, points, team, season u. a.). Daten reichen für den Test.
Plan: (1) Testsaison 2025-26; Variante A = laufende Saison + Vorsaison 2024-25 (wie heute, PRIOR_GAMES_K = 8); Variante B = zusätzlich 2023-24 als zweite Vorsaison mit festem Gewicht 25 % des Vorsaison-Anteils (Annahme, nicht getunt). (2) Wertung nur Spieltage mit 0 bis 15 Saisonspielen des Spielers, getrennt 0-4, 5-9, 10-15. (3) Kennzahlen: mittlerer Fehler Minuten und Punkte, Brier auf den Meilensteinen (Punkte >= N) wie eval_player_forecasts. (4) Bootstrap-Intervall über Spiele. (5) Entscheidungsregel vorab: B bleibt nur, wenn der Brier in der frühen Gruppe besser ist und das Intervall die 0 nicht enthält, sonst negativ. (6) Skript nur im Scratchpad, forecast_player(..., games=...) mit vorgegebenen Spielen, nichts in App, Modell, Daten.
Achtung (Code): game_weights behandelt alles außer der laufenden Saison als EINE Vorsaison; für B braucht das Skript eigene Gewichte (nicht in engine ändern). Nicht geprüft: Wirkung bei Team- oder Rollenwechsel.

### 6.11. Schritt 3 zu 4.1: Ergebnis Test zweite Vorsaison (lesend, Skript nur im Scratchpad: vs2.py)
Aufbau wie im Plan: Testsaison 2025-26, Spieler-Spieltage mit 0 bis 15 Saisonspielen (Spieler spielte mind. 1 Minute), A = laufende Saison + 2024-25 (Originalgewichte), B = zusätzlich 2023-24 mit 25 % des Vorsaison-Anteils (game_weights nur im Skript ersetzt, engine unverändert). Ohne Spread (exp_spread None) für beide gleich. Brier = Mittel über die Linien 5, 8, 10, 12, 15, 18, 20, 25, 30 Punkte. Intervalle: Bootstrap über Spiele (1000), B minus A, negativ = B besser.
- 0-4 Saisonspiele (2520 Zeilen, 546 Spiele): Brier A 0,1101, B 0,1094, Diff -0,0007 [-0,0014; -0,0001]; MAE Minuten +0,011 [-0,039; +0,061]; MAE Punkte -0,019 [-0,045; +0,009].
- 5-9 (2548, 635): Brier -0,0004 [-0,0008; +0,0001]; Minuten -0,003 [-0,040; +0,032]; Punkte -0,016 [-0,035; +0,004].
- 10-15 (2874, 702): Brier -0,0002 [-0,0005; +0,0001]; Minuten +0,010 [-0,015; +0,035]; Punkte -0,009 [-0,022; +0,003].
- Alle (7942, 1054): Brier A 0,1087, B 0,1083, Diff -0,0004 [-0,0007; -0,0001]; Punkte-MAE -0,014 [-0,026; -0,003]; Minuten +0,006 [-0,016; +0,031].
- Nur Spieler mit Spielen aus 2023-24 (5669 Zeilen): Brier -0,0006 [-0,0010; -0,0002].
Bewertung nach der vorab festgelegten Regel: formal erfüllt (Brier in der frühen Gruppe 0-4 besser, Intervall ohne 0), aber der Effekt ist sehr klein (ca. 0,6 % des Brier; zum Vergleich Lücke Modell roh gegen Betano ca. 0,015), Minuten unverändert, die Gruppen 5-9 und 10-15 nicht belegt. Einschränkungen: nur eine Testsaison, nur ein fester Gewichtswert 25 % (nicht getunt), 4 Gruppen/3 Kennzahlen betrachtet (kein Mehrfachtest-Ausgleich), Rückrechnung ohne Spread und ohne Ausfälle, Live-Einbau würde 2023-24 in SEASONS_TO_LOAD und game_weights brauchen. Nicht geprüft: andere Gewichte, Wirkung auf Teamabgleich.
Entscheidung 6.11. (Frage Baran, Claude): Kein Wiederholungstest im Saisonverlauf nötig. Der Test lief schon über die ganze Saison 2025-26 (inkl. früher Phase) und ein späterer Test käme nur mit Spielern, die mehr Saisonspiele haben, wo der Effekt noch kleiner wird (10-15 Spiele: -0,0002, nicht belegt). Nur falls 2026-27 deutlich andere Verhältnisse zeigt (viele Neulinge, Regeländerung), neu ansehen.

### 6.11. Schritt 1 zu 5.7: Bestandsaufnahme Rollenwechsel (lesend, Skript nur im Scratchpad: rolle.py)
Code: engine/player_forecast.py Zeilen ca. 200-210: Hinweis "Rollenwechsel", wenn der Mittelwert der Minuten der letzten 5 Spiele um mindestens ROLE_CHANGE_MINUTES = 5,0 vom gewichteten Mittel abweicht (ab 5 Spielen); der Hinweis ändert die Rechnung nicht, er steht nur in quality/warnings.
Test (2025-26, Modell roh ohne Spread, Spieler-Spieltage mit mindestens 10 Spielen Verlauf inkl. 2024-25, 25427 Zeilen, Ist minus Modell):
- Kein Hinweis (22448 Zeilen): Bias Minuten -0,35, MAE Minuten 4,94 (Vorhersage nur "Mittel der letzten 5": 4,92), Bias Punkte -0,17, Brier 0,1156.
- Hinweis, letzte 5 höher (1521): Bias Minuten +4,54, MAE Modell 7,29 gegen 6,33 mit "letzte 5", Bias Punkte +1,99, Brier 0,1391.
- Hinweis, letzte 5 niedriger (1458): Bias Minuten -3,86, MAE Modell 6,67 gegen 5,86 mit "letzte 5", Bias Punkte -1,66, Brier 0,0965.
Befund: Bei gemeldetem Rollenwechsel liegt das Modell im Mittel 4 bis 4,5 Minuten falsch in Richtung der letzten 5 Spiele (Rollenwechsel hält also eher an, als das Modell annimmt), und "letzte 5" allein ist dort ca. 0,8 bis 0,9 Minuten genauer. Nicht geprüft: Konfidenzintervalle, ob es an einzelnen Spielern liegt (Zeilen eines Spielers hängen zusammen), "neu in der Startformation" und "Rückkehr nach Pause" getrennt (Startformation steht nicht in den Spielerdaten), Wirkung einer Korrektur. Auswahleffekt möglich: Der Schwellenwert 5 Minuten wählt gerade Fälle, in denen die letzten 5 stark abweichen.

### 6.11. Schritt 2 zu 5.7: Testplan Korrektur bei Rollenwechsel (Baran "du entscheidest")
Plan vorab: (1) Nur Zeilen mit Hinweis "Rollenwechsel" (Abweichung der letzten 5 Spiele >= 5 Min.), mindestens 10 Spiele Verlauf. (2) Korrektur: Minutenmittel = Modellmittel + beta x (Mittel letzte 5 minus gewichtetes Mittel); Punkte und Chancen mit diesen Minuten neu über minutes_mean_override. (3) beta wird NICHT auf den Testdaten gewählt: beta per Kleinste-Quadrate auf der Vorsaison 2024-25 (flagged Zeilen) bestimmt, dann fest auf 2025-26 angewendet. (4) Kennzahlen: MAE Minuten, MAE Punkte, Brier (Linien 5 bis 30), Bootstrap über Spiele (1000), zusätzlich getrennt für die erste und zweite Hälfte der Saison 2025-26 (nach Datum). (5) Regel: Korrektur nur dann sinnvoll, wenn der Brier in BEIDEN Hälften besser ist und beide Intervalle die 0 nicht enthalten. Sonst negativ. (6) Nur Scratchpad, engine und Daten unverändert.

### 6.11. Schritt 3 zu 5.7: Ergebnis Korrektur bei Rollenwechsel (lesend, Skript nur im Scratchpad: rolle2.py)
beta aus 2024-25 (2833 Zeilen mit Hinweis): 0,565, fest auf 2025-26 angewendet. Korrektur: Minutenmittel = Modellmittel + 0,565 x (Mittel letzte 5 minus gewichtetes Mittel). Nur Zeilen mit Hinweis "Rollenwechsel", Bootstrap über Spiele, neu minus alt (negativ = besser):
- Alle (3008 Zeilen, 1099 Spiele): MAE Minuten 7,02 -> 5,91 (Diff -1,11 [-1,24; -0,97]); MAE Punkte 4,68 -> 4,43 (-0,25 [-0,31; -0,19]); Brier 0,1187 -> 0,1120 (-0,0066 [-0,0080; -0,0052]).
- 1. Hälfte (bis 17.1.2026, 1524 Zeilen): Brier -0,0055 [-0,0074; -0,0036]; Minuten -1,08; Punkte -0,22.
- 2. Hälfte (1484 Zeilen): Brier -0,0078 [-0,0098; -0,0056]; Minuten -1,13; Punkte -0,28.
Regel vorab (Brier in beiden Hälften besser, beide Intervalle ohne 0): erfüllt. Betroffen sind ca. 12 % der Spieler-Spieltage (3008 von ca. 25400); über alle Zeilen gerechnet wäre der Brier-Gewinn ca. 0,0008. Einschränkungen: eine Testsaison; beta nur aus einer Vorsaison; Rückrechnung ohne Spread und ohne Ausfälle; Hinweis-Schwelle 5 Min. nicht getestet; Teamabgleich nicht geprüft; Live-Einbau hieße Änderung in engine/player_forecast.py (Minutenmittel bei Hinweis), neue Tests und neue Modellversion. Nicht geprüft: Wirkung im Informationswert-Test gegen Betano.

### 6.11. Schritt 4 zu 5.7: Einbauplan Rollenwechsel-Korrektur (Plan, NICHTS gebaut, Baran "du entscheidest")
Betroffene Stellen (nur gelesen): engine/player_forecast.py (Zeile ca. 167 mu0/sd0, ca. 205 Hinweis), PLAYER_MODEL_VERSION "player-1" (auch in engine/player_snapshots.py, data/day_bets_store.py), Tests mit Bezug: tests/test_player_forecast.py, test_player_cards.py, test_player_tab.py, test_player_cards_pregame.py, test_player_model_version.py (Rollenwechsel/Version).
Plan: (1) Neue Konstante ROLE_CHANGE_BETA = 0.565 (Quelle: Fit 2024-25, Archiv 6.11. Schritt 3). (2) In forecast_player nach mu0: Wenn mindestens 10 Spiele Verlauf und |Mittel letzte 5 - mu0| >= ROLE_CHANGE_MINUTES: mu0_korrigiert = mu0 + beta x (last5 - mu0), vor blowout_factor; Hinweis-Bedingung weiter mit dem ORIGINAL-mu0. Spielerkarten-Hinweistext um "Minuten korrigiert" ergänzen. (3) Version auf "player-2", damit alte und neue Snapshots getrennt auswertbar bleiben (Informationswert-Test, Auswertung). (4) Vorher: Test mit dem echten Code statt der Override-Näherung (Blowout wird dort leicht anders angewendet), Zahlen müssen den Scratchpad-Werten (Brier -0,0066) nahekommen. (5) Neue Tests: Korrektur greift nur bei Hinweis und >= 10 Spielen; Zeilen ohne Hinweis unverändert; Version player-2; Teamabgleich nutzt die korrigierten Minuten. (6) Betroffene Tests einzeln laufen lassen, Gesamtlauf macht Baran. (7) Zeitpunkt: nicht an einem Spieltag mit laufender Aufzeichnung ändern; Baran entscheidet Tag. Offen: Schwelle 5 Min. und beta nicht weiter getunt.

### 6.11. Schritt 5 zu 5.7: Prüfung mit dem echten Code (Kopie im Scratchpad: pf_neu.py, rolle3.py; engine/ unverändert)
Kopie von engine/player_forecast.py mit der Korrektur (beta 0,565, ab 10 Spielen Verlauf und Abweichung >= 5 Min., vor dem Blowout-Abschlag; Hinweis-Bedingung mit Original-mu0), gegen das Original auf 2025-26 (Spieler mit >= 10 Spielen Verlauf, ohne Spread):
- Zeilen ohne Hinweis (22448): 0 verändert (Minuten und Punkte identisch).
- Mit Hinweis (2979): Brier 0,1182 -> 0,1114 (Diff -0,0068 [-0,0083; -0,0053]); MAE Minuten 6,98 -> 5,86 (-1,12); MAE Punkte 4,67 -> 4,41 (-0,26).
- 1. Hälfte (1513): Brier -0,0057 [-0,0077; -0,0037]; 2. Hälfte (1466): Brier -0,0080 [-0,0102; -0,0059].
Ergebnis: bestätigt die Näherung (vorher -0,0066), Regel erfüllt. Einbau weiter nur nach Freigabe durch Baran.

### 6.11. abends, Schritt 6 zu 5.7: Einbau (auf Wunsch von Baran schon am 6.11. 23:xx statt 7.11.)
Geändert (nur diese Dateien): engine/player_forecast.py (PLAYER_MODEL_VERSION "player-2"; neue Konstanten ROLE_CHANGE_BETA = 0.565 und ROLE_CHANGE_MIN_GAMES = 10; nach mu0/sd0 Korrektur mu0 = mu0_orig + beta x (last5 - mu0_orig) bei mind. 10 Spielen und |last5 - mu0_orig| >= ROLE_CHANGE_MINUTES; Hinweis "Rollenwechsel" weiter mit mu0_orig, Warnung ergänzt um "Minuten korrigiert auf ..."; Docstring), tests/test_player_model_version.py (player-1 -> player-2), tests/test_player_forecast.py (6 neue Prüfungen: Formel, Hinweistext, Konstanten, Spieler ohne Rollenwechsel unverändert, unter 10 Spielen Hinweis aber keine Korrektur).
Tests (einzeln, nur betroffene): test_player_forecast FAIL=0 (71 PASS), test_player_model_version FAIL=0 (17), test_player_cards FAIL=0 (35), test_player_tab FAIL=0 (40), test_player_cards_pregame FAIL=0 (18). Erste Fassung eines neuen Tests war falsch (Testdaten ohne Hinweis), korrigiert. Nicht gelaufen: Gesamttestlauf (Baran), andere Tests mit forecast_player-Zahlen (z. B. Snapshot-/Teamabgleich-Tests) nicht einzeln geprüft. Alte Snapshots und Wetten bleiben unverändert (player-1/player-0). Streamlit läuft noch mit altem Code und muss neu gestartet werden. Nicht geändert: Daten, Modelle, analysis/-Skripte.
