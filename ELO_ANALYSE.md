# ELO-Analyse: Rating-Spanne, Skalierung, Saisonstart (Stand 20.10.2026)

**Status:** Nur Analyse und Plan. Im Projekt wurde nichts geändert, nichts trainiert, kein API-Call ausgeführt. Alle Rechnungen liefen auf dem vorhandenen Cache (`data/cache/games_2015…2025.json`, 14 168 Spiele inkl. Playoffs) und dem gespeicherten Modell (nur gelesen). Die Rechenskripte liegen im Scratchpad der Sitzung (nicht im Projekt) und können nach Freigabe in einen Ordner `analysis/` übernommen werden. Keine Zugangsdaten enthalten.

**Kennzeichnung:** *gemessen* = aus den Daten berechnet. *geschätzt/offen* = nicht belegt oder nicht geprüft.

---

## 0. Kurzfazit

1. **Der heutige Abstand zum Markt hat zwei Ursachen, und beide sind keine Frage des Saisonwechsels:**
   - **Skalierung (gemessen):** `ELO_TO_SPREAD_FACTOR = 25` ist etwa um den Faktor 2 zu klein. Die Daten ergeben ca. **50,8 ELO pro Punkt** (Spanne je Saison 43–64). Die Modell-Spreads sind dadurch doppelt so groß wie die Realität. Allein diese Korrektur senkt den Spread-MAE in den ersten 20 Spielen (2023–25, ohne Rekalibrierung) von **11,60 auf 10,27** (95 %-CI der Differenz −1,73 … −0,94).
   - **Vorzeichenfehler beim Spread-Blend (Zusatzfund, siehe Abschnitt 1.6):** `compute_projection` mischt den Odds-API-Spread (Heim-Handicap, negativ = Favorit) mit dem Modell-Spread (positiv = Heim-Favorit). Der Markt zieht dadurch in die falsche Richtung. Die drei Beispiele von heute Abend lassen sich damit auf die erste Nachkommastelle exakt reproduzieren.
2. **Die ELO-Struktur ist dagegen weniger schlecht als die Spanne vermuten lässt, wenn man die Skala nachführt:** Nach Rekalibrierung von Steigung und Logistik auf frühere Saisons liegt das aktuelle Modell nur ca. 0,05–0,1 Punkte (Spread-MAE) bzw. 0,003–0,005 (Brier) hinter den besseren Varianten. Der strukturelle Gewinn ist real, aber klein; der Skalierungsgewinn ist groß.
3. **Das Modell ist nur so aktuell wie der letzte `train.py`-Lauf.** Die App schreibt neue Ergebnisse nie ins Rating fort. Ratings, Form und Ruhetage stehen aktuell auf dem 13.06.2026. „Zu jedem Zeitpunkt aktuell“ erfordert deshalb zwingend ein tägliches Fortschreiben, unabhängig von der Formel (Option 12).
4. **Empfehlung (Details Abschnitt 2.3):** Sofortfixes (Vorzeichen, Skalierung) → punktbasiertes Rating mit Saisonübernahme (r ≈ 0,4) und Fortschreibung → Wahrscheinlichkeit per Normalverteilung statt Isotonik → spielanzahl-abhängiger Markt-Anker. Kader/Win-Totals als zweite Phase.

---

## 1. Diagnose (Schritt 1)

### 1.1 Rating-Spanne am Saisonende (gemessen, aktuelles Modell, nach den Playoffs)

| Saison | min | max | Spanne | Std |
|---|---|---|---|---|
| 2015 | 1061 | 2045 | 985 | 222 |
| 2016 | 1195 | 2083 | 888 | 193 |
| 2017 | 1173 | 2056 | 883 | 196 |
| 2018 | 1116 | 2052 | 936 | 213 |
| 2019 | 1136 | 1937 | 801 | 197 |
| 2020 | 1091 | 2025 | 934 | 219 |
| 2021 | 1008 | 1997 | 989 | 202 |
| 2022 | 1122 | 1999 | 877 | 181 |
| 2023 | 1093 | 1951 | 858 | 214 |
| 2024 | 1066 | 1946 | 880 | 243 |
| 2025 | 960 | 2148 | **1189** | **282** |

- **Es gibt keinen schleichenden Drift über die Jahre.** Die Spanne liegt seit 2015 stabil bei ca. 800–1000 und springt nur 2025 auf 1189. Die Ratings sind zero-sum (Mittel bleibt 1500); das Problem ist die Breite, nicht das Niveau.
- **Die Spanne ist in ELO-Einheiten groß, in Punkten aber plausibel:** Die Team-Saisonmargin hat real eine Std von 5,0 Punkten (gemessen, ohne 2019/20). Std 200 ELO entspricht bei 50,8 ELO/Punkt rund 3,9 Punkten, die Spanne von 900–1190 ELO rund 18–23 Punkten; das punktbasierte Vergleichsrating (Option 8) kommt auf ca. 20–26 Punkte. **Die Ratings sind also nicht unrealistisch gespreizt, sondern die Einheit passt nicht:** Sie sind etwa 1,8-mal breiter, als die 400er-Logistik (Siegwahrscheinlichkeit, ELO-Update) und der Faktor 25 (Spread) unterstellen. Die Folgen sind überkonfidente Wahrscheinlichkeiten, doppelt zu große Spreads und rauschempfindliche Updates (1.2).
- Der Sprung 2025 (Knicks 2148, Wizards 960) entsteht, weil ein Team mit sehr vielen hohen Siegen (inkl. Playoffs) über Jahre nichts zurückgibt und keine Saisongrenze existiert.

### 1.2 Wirkung von MOV-Multiplikator und K (gemessen/gerechnet)

Aktuell: `k = 20 × 2,2 × ln(Margin+1)`. Zugewinn des Siegers (Verlierer verliert gleich viel):

| Margin | k | exp 0,50 | exp 0,64 (Heimteam, Dif = HCA) | exp 0,85 (Favorit gewinnt) | exp 0,15 (Underdog gewinnt) |
|---|---|---|---|---|---|
| 1 | 30,5 | 15,2 | 11,0 | 4,6 | 25,9 |
| **5** | 78,8 | 39,4 | 28,4 | 11,8 | 67,0 |
| **15** | 122,0 | 61,0 | 43,9 | 18,3 | 103,7 |
| **30** | 151,1 | 75,5 | 54,4 | 22,7 | 128,4 |

- Über alle Spiele: Median-k = 106, mittleres **|Update| = 39,7 ELO pro Spiel**.
- 538-Formel (`K × (Margin+3)^0,8 / (7,5 + 0,006 × Rating-Vorsprung des Siegers)`, K = 20): Median-k = 19, mittleres |Update| = **9,4 ELO**. Das aktuelle Modell lernt also **ca. 4-mal so aggressiv** und trägt fast jedes Einzelergebnis ins Rating (Rauschen).
- Es gibt keinen Favoriten-Dämpfer: Gewinnt ein klarer Favorit hoch, wird er trotzdem kräftig belohnt (Autokorrelations-Problem).
- Die Rating-Update-Gleichung nutzt die ELO-Erwartung `p_elo = 1/(1+10^(−Diff/400))`, die extrem überkonfident ist (Tabelle in 1.3). Dadurch sind Underdog-Siege besonders teuer.

### 1.3 ELO_TO_SPREAD_FACTOR = 25 (gemessen)

OLS `reale Heim-Margin ~ ELO-Differenz` über alle 14 168 Spiele: Steigung **0,0197 Punkte/ELO → Faktor 50,8** (Achsenabschnitt +0,29). Je Saison zwischen 43,2 (2025) und 64,2 (2022). Der Faktor 25 passt zu keiner Saison.

| ELO-Diff (inkl. HCA, Form, Rest) | n | reale Margin | Prognose `/25` | Heimsieg real | `p_elo` (roh) |
|---|---|---|---|---|---|
| < −600 | 60 | −13,2 | −27,1 | 10,0 % | 2,1 % |
| −400…−300 | 512 | −6,5 | −13,8 | 29,7 % | 12,2 % |
| −100…0 | 1784 | −0,2 | −2,0 | 49,3 % | 43,0 % |
| 100…200 | 2138 | 2,8 | 6,0 | 58,8 % | 70,1 % |
| 300…400 | 1279 | 6,8 | 13,9 | 71,0 % | 88,0 % |
| 400…600 | 1510 | 10,2 | 19,4 | 78,3 % | 94,0 % |
| > 600 | 462 | 13,9 | 27,9 | 87,9 % | 98,0 % |

- Die Beziehung ist **linear, aber mit halber Steigung**. Der rohe ELO-Wert überschätzt Siegwahrscheinlichkeiten ab ca. 200 ELO Differenz deutlich.
- Konsistenzcheck: Heimvorteil 100 ELO ≙ 100/50,8 = 2,0 Punkte. Der reale Heimvorteil liegt bei ca. 1,6–2,2 Punkten (2023–25: 2,2/1,6/1,8; Mittel 2,3 über alle Saisons). Mit Faktor 25 wären es 4 Punkte, also doppelt zu viel. Die Konstanten `HCA = 100` und Faktor ≈ 50 passen zusammen, `25` nicht.
- Spread-MAE gesamt: mit `/25` 10,65–12,51 je Saison, mit gefittetem Faktor 9,80–11,67 (Gewinn ≈ 0,8–1,2).

### 1.4 Kalibrierung der Siegwahrscheinlichkeit (gemessen)

**Walk-forward** (Engine-Pipeline: Logistik + Isotonik, je Saison nur auf frühere Saisons trainiert, Test 2018–2025, 10 613 Spiele):

| Saison | Brier | LogLoss | > 90 % | < 10 % | max p | min p |
|---|---|---|---|---|---|---|
| 2018 | 0,2195 | 0,630 | 3,5 % | 0,5 % | 0,966 | 0,000 |
| 2019 | 0,2233 | 0,635 | 3,5 % | 0,6 % | 1,000 | 0,000 |
| 2020 | 0,2328 | 0,659 | 3,1 % | 0,4 % | 0,977 | 0,022 |
| 2021 | 0,2264 | 0,647 | 2,9 % | 0,3 % | 0,982 | 0,059 |
| 2022 | 0,2334 | 0,661 | 1,1 % | 0,0 % | 0,990 | 0,191 |
| 2023 | 0,2161 | 0,629 | 1,9 % | 0,8 % | 1,000 | 0,000 |
| 2024 | 0,2154 | 0,619 | 2,2 % | 0,4 % | 0,990 | 0,010 |
| 2025 | 0,2121 | 0,612 | 2,6 % | 0,5 % | 1,000 | 0,057 |
| **gesamt** | **0,2222** | | **2,6 %** | **0,4 %** | | **7 Spiele mit exakt 0 oder 1** |

Referenz „immer Heimquote“: Brier ≈ 0,247. Die Kalibrierung ist **in der Mitte gut, an den Rändern zu mutig:**

| p-Bereich | n | mittleres p | real |
|---|---|---|---|
| 0,0–0,1 | 43 | 0,047 | 0,116 |
| 0,1–0,2 | 80 | 0,162 | 0,138 |
| 0,4–0,5 | 1272 | 0,459 | 0,450 |
| 0,6–0,7 | 1965 | 0,655 | 0,633 |
| 0,8–0,9 | 543 | 0,844 | 0,803 |
| **0,9–1,0** | **264** | **0,936** | **0,886** |

**Gespeichertes Modell:** Die Kurve ist flach bei 0,013 für ELO-Diff ≤ −700 und springt auf 1,000 ab ca. +1000 (Isotonik extrapoliert nicht, sie klebt am Rand). Aktuell: OKC (1897) gegen Utah (1112) ergibt Diff ≈ 897 und p ≈ 0,989; nach Form-Beiträgen ist 100 % möglich. Ursache der 0 %/100 % im April ist also: übergroße ELO-Differenz plus Isotonik-Plateau. Knicks gegen 76ers (Diff 619) ergibt heute 87,5 %.

### 1.5 Wo das Modell am Saisonanfang steht (gemessen)

Test 2023–25, Regular Season, erste 20 Spiele beider Teams (n = 873), je Saison auf frühere Saisons rekalibriert:

| Referenz | Spread-MAE |
|---|---|
| Konstante (nur Heimvorteil) | 11,42 |
| aktuelles Modell, Steigung rekalibriert | 10,26 |
| aktuelles Modell **wie eingesetzt (`/25`)** | **11,60** |

Das eingesetzte Modell ist im Saisonstart also **schlechter als die Konstante** (11,42), sobald man die Skalierung nicht nachführt. Total-MAE: aktuelles Modell 14,93, Vorjahres-Median 15,60 (n = 873). Das Total-Modell bringt nur wenig; Änderungen am Dämpfungsparameter α der Off/Def-Werte (0,05–0,20) ändern daran nichts (14,93–15,05).

Saison-zu-Saison-Persistenz (gemessen, 300 Team-Saison-Paare): Korrelation Rating Saisonende → Margin Folgesaison 0,49; Margin → Margin Folgesaison 0,57 mit Steigung **0,59**. Das heißt: Etwa **41 %** der Abweichung vom Mittel verschwinden über den Sommer. Das ist der datenbasierte Ausgangspunkt für r (Regressionsanteil).

### 1.6 Zusatzfund: Vorzeichenfehler im Spread-Blend (gemessen/nachgerechnet)

Code: `engine/projection.py` mischt `exp_spread = 0,75 × (home_elo − away_elo)/25 + 0,25 × market_spread`. Das Modell zählt **positiv = Heim ist Favorit**. `parse_totals_spreads` übernimmt dagegen den Odds-API-Wert `point` des Heimteams: **negativ = Heim ist Favorit**. Der Markt wird also mit falschem Vorzeichen eingemischt.

Nachrechnung der heutigen Beispiele mit dem gespeicherten Modell (Datum 20.10.2026):

| Spiel (Heim zuerst) | ELO-Diff | Modell `/25` | Markt-`point` (Heim) | 0,75·Modell + 0,25·point | im Dashboard |
|---|---|---|---|---|---|
| Knicks – 76ers | 619,0 | +24,8 | −4,5 | 17,4 | 17,4 |
| Spurs – OKC | 208,4 | +8,3 | +0,2 | 6,3 | 6,3 |
| Pistons – Celtics | 152,5 | +6,1 | +1,5 | 4,95 | 4,9 |

Folgerungen:
- **Das Modell sieht bei „OKC @ Spurs“ und „Celtics @ Pistons“ die Heimteams als Favoriten** (Spurs −6,3, Pistons −4,9), nicht OKC/Celtics. Die Anzeige `MODEL -x` hat immer ein Minus (`app.py:551`, `-{abs(exp_spread)}`) und nennt kein Team; das ist vermutlich Quelle der Verwechslung.
- Bei korrektem Vorzeichen wären die Werte 19,7 (Knicks), 6,2 (Spurs), 4,2 (Pistons). Der Fehler ist wegen des 25-%-Gewichts klein aber systematisch (bis ca. 2,3 Punkte beim Knicks-Beispiel) und verwirrend in der Anzeige.
- Die eigentlichen Lücken zum Markt (Knicks 24,8 vs 4,5; Spurs 8,3 vs −0,2; Pistons 6,1 vs −1,5) schrumpfen mit Faktor 50,8 auf 12,2 / 4,1 / 3,0 und mit dem unten vorgeschlagenen Punkte-Rating auf 9,6 / 3,7 / 2,5 (Rechnung in 2.2). Die Knicks-Lücke bleibt groß: Das Modell kennt keine Offseason-Änderungen am Kader.

---

## 2. Lösungsoptionen (Schritt 2)

### 2.1 Zusätzliche Messungen für die Bewertung (gemessen, Vorabergebnis)

**Achtung zur Aussagekraft:** Die Parameter wurden auf denselben Saisons gesucht, auf denen getestet wird (leicht optimistisch). Alle Varianten werden walk-forward bewertet (Skala und Logistik je Saison nur auf frühere Saisons). Konfidenzintervalle mit paired Bootstrap. Der echte Backtest (Abschnitt 3) mit sauberer Parameterwahl steht noch aus.

Kennzahlen: Spread-MAE / Brier, Test-Saisons 2023–25, nur erste 20 Spiele je Team (n = 873); „9S“ = Test 2017–2025.

| Variante | 3S erste 20 | 9S erste 20 | 9S erste 10 | 9S alle Spiele | ELO-/Punkt-Spanne |
|---|---|---|---|---|---|
| 0 Baseline (aktuell, rekalibriert) | 10,26 / 0,2110 | 10,50 / 0,2234 | 10,71 / 0,2307¹ | 10,90 / 0,2205 | 929 ELO |
| 1 Carry r = 0,33 (alte MOV) | 10,31 / 0,2107 | 10,51 / 0,2223 | | 10,90 / 0,2203 | 929 |
| 2a alte MOV, K = 8 | 10,27 / 0,2125 | 10,48 / 0,2230 | | 10,77 / 0,2170 | 637 |
| 2b 538-MOV, K = 20 | 10,29 / 0,2127 | 10,48 / 0,2225 | | 10,75 / 0,2167 | 471 |
| 2c 538-MOV, K = 20, Carry 0,33 | 10,25 / 0,2111 | 10,41 / 0,2202 | 10,64 / 0,2282 | 10,72 / 0,2158 | 463 |
| 2c 538-MOV, K = 15, Carry 0,50 | 10,29 / 0,2116 | 10,42 / 0,2198 | | 10,71 / 0,2156 | 411 |
| 3 538, Carry 0,33, K-Boost 1,0 (erste 15 Spiele) | 10,19 / 0,2089 | 10,40 / 0,2200 | | 10,71 / 0,2157 | 468 |
| **8 Punkte-Rating** (k = 0,05, Carry 0,4) | **10,21 / 0,2077** | 10,41 / 0,2193 | 10,68 / 0,2284 | 10,71 / 0,2156 | ≈ 20 Punkte |
| 8 + K-Boost 1,0 | 10,16 / 0,2059 | 10,42 / 0,2199 | 10,69 / 0,2294 | 10,71 / 0,2158 | ≈ 20 Punkte |

¹ Hier: 538-MOV, Carry 0 (reine Vergleichsbasis der Carry-Reihe).

Weitere Befunde:
- **Carry-Optimum (538-MOV, K = 20, Test 2017–25):** erste 10 Spiele Brier 0,2307 (r = 0) → 0,2287 (0,25) → **0,2282 (0,33)** → **0,2278 (0,50)** → 0,2304 (0,75) → 0,2385 (1,00). Erste 20 Spiele: Optimum bei **0,50** (0,2197). Das Optimum ist flach zwischen 0,33 und 0,5. Zusammen mit der gemessenen Persistenz (Steigung 0,59 → r ≈ 0,41) ist **r ≈ 0,4** datenbasiert gestützt; „raten“ ist nicht nötig.
- **Deployte Genauigkeit (ohne Rekalibrierung, 3S erste 20):** Baseline `/25` 11,60 · Baseline `/50,8` 10,27 · Punkte-Rating direkt 10,16.
- **Signifikanz (paired Bootstrap, n = 873):** `/25` → `/50,8`: −1,33 [−1,73; −0,94]. Punkte-Rating gegen Baseline `/50,8`: −0,10 [−0,22; +0,02], also **kein belastbarer MAE-Unterschied**. Brier Punkte-Rating gegen Baseline: −0,0051 [−0,0085; −0,0013], also klein, aber knapp signifikant.
- **Konsequenz:** Die Wahl der Rating-Formel verbessert Genauigkeit nur um Zehntel Punkte. Der Zugewinn kommt aus (1) richtiger Skalierung, (2) richtiger Spreizung, (3) aktuellen Daten und (4) einem Anker, der Kaderänderungen kennt. Das Rating allein kann die Offseason-Lücke nicht schließen.
- **Rating-Spreizung nach Umstellung:** Punkte-Rating hat eine Spanne von ca. 20 Punkten (Knicks +13,6 / Spurs +13,2 / OKC +10,8 … Wizards −13,1 Ende 2025; nach r = 0,4: +8,2 / +7,9 / +6,5 … −7,8). Das ist realistisch.
- **Marktvergleich nicht möglich:** Im Projekt gibt es keine historischen Quoten. Wie gut Vegas-Spreads im Saisonstart sind, wurde nicht gemessen (geschätzt: deutlich besser als jedes reine Ergebnismodell, offen).

### 2.2 Bewertung der Optionen

| # | Option | Aufwand | Benötigte Daten | Risiken | Erwartete Wirkung |
|---|---|---|---|---|---|
| 1 | **Regression zum Mittelwert** beim Saisonwechsel (r ≈ 0,4) | klein (ca. 10 Zeilen in `build_model`; zusätzlich beim Laden/`predict` anwenden, siehe Hinweis) | vorhanden (Cache, Feld `season`) | globales r kennt keine Kaderänderungen; einmaliger Wert pro Team, nicht pro Team-Typ; bei alter MOV allein fast wirkungslos | gemessen: Brier −0,002 bis −0,003 in den ersten 10–20 Spielen, Spread-MAE −0,05…−0,1 (nur zusammen mit 2/8 sinnvoll) |
| 2 | **538-Dämpfung + kleineres K** | klein | vorhanden | Neu-Kalibrierung der Logistik nötig; K zu klein = träge | gemessen: Spanne 929 → ca. 460 ELO, Brier −0,004 (alle Spiele); MAE −0,15. Besser als Option 2 ist 8 |
| 3 | **K-Boost** in den ersten 10–20 Saisonspielen | klein | vorhanden | Rauschen im Saisonstart wird stärker gelernt; Gewinn nur in 3S sichtbar, nicht in 9S | gemessen: Brier −0,002 (3S), ±0 (9S) → **nicht belastbar**, erst nach sauberem Backtest, besser als Glicko-/Unsicherheits-K (Option 9) |
| 4 | **Markt-implizite Ratings** (Team-Stärke aus Spreads/Totals/Moneylines, z. B. regularisierte Kleinste-Quadrate über alle Spiele des Tages/der Woche) | mittel bis hoch | Odds API (`totals,spreads` liefert Spreads aller Spiele pro Aufruf, schon im Code); Historie fehlt im Projekt: Backtest nur mit Zukaufdaten (Odds-API-Historie ist kostenpflichtig und verbraucht Kontingent; freie Closing-Line-Datensätze existieren vermutlich, Verfügbarkeit **nicht geprüft**) | **Zirkularität:** Wenn das Modell den Markt wiedergibt, verschwindet jede Abweichung als Signal („Lineup Risk“, „Market Disagreement“). Teams ohne Spiel am Tag brauchen mehrere Tage Daten. Spreads enthalten Aufstellungsinfos des Tages (gut) und Wettmarkt-Verzerrungen (schlecht) | sehr hoch für Spread-Genauigkeit am Saisonstart (Kader, Verletzungen); aber Wert für Edge-Suche sinkt. Nur als **Prior für die ersten Wochen** einsetzen, nicht als Dauerersatz |
| 5 | **Blend Modell/Markt, Modellgewicht steigt mit Spielanzahl** | klein (nur `compute_projection`) | aktuell vorhanden (Markt-Spread und -Total werden schon geladen) | Gewichtskurve nicht backtestbar ohne historische Quoten; Gefahr, den Markt dauerhaft überzubewerten | hoch am Anfang, gegen null später. Heute: fester Anteil 25 % (Spread) bzw. 32–55 % (Total). Vorschlag Heuristik: Markt-Gewicht 0,7 bei 0 Spielen → 0,25 ab ca. 30 Spielen, danach konstant. Parameter zunächst Annahme, später mit gesammelten Schnappschüssen prüfen |
| 6 | **Kader-basierte Anpassung** | hoch (Tage) | BallDontLie: Spieler-/Box-Score-Daten sind im Code teils schon im Einsatz (Suche, Season Averages, Last Games); ob der aktuelle Plan Verletzungs- und Kader-Endpunkte liefert, **ist im Code nicht ersichtlich (offen)**. nba_api (inoffiziell, kann ausfallen) als Alternative | Minuten-Prognose, Trades, Rookies, Verletzungsstatus; Historie für Training/Backtest aufwendig; mehr API-Verbrauch | potenziell größte Verbesserung zum Saisonstart und für „Lineup Risk“; Messung erst nach Aufbau möglich |
| 7 | **Preseason-Win-Totals** als Prior | klein bis mittel | frei zugänglich sind Quellen vermutlich nur über Webseiten, nicht über eine stabile API (**nicht geprüft**); für 2026/27 reichen 30 manuell erfasste Zahlen in einer JSON-Datei. Backtest 2015–2025 verlangt 330 historische Werte, die erst beschafft werden müssten | Quelle/Stand der Linie (vor/nach Trades), manueller Pflegeaufwand | hoch am Saisonstart, weil Win-Totals Kaderänderungen enthalten. Umrechnung Siege → Punkte: Steigung aus den Daten **0,0289 Siege-Quote je Margin-Punkt = ca. 2,4 Siege pro Punkt/82 Spiele** (nicht 2,7), verwendbar für `Punkte-Prior = (Win-Total − 41)/2,4` |
| 8 | **Punktbasiertes Rating** (eigener Vorschlag): Rating in Punkten, Update `k × (min(±25, Margin) − Prognose)`, Prognose = Rating-Differenz + HCA ≈ 2,0 | klein bis mittel (neue Klasse neben `EloEngine`, `models/elo.py`, Pickle-Format) | vorhanden | Neu-Bau der Logistik-/Spread-Kette; `ELO_TO_SPREAD_FACTOR` entfällt; Form/Rest-Features müssen mitgezogen werden | gemessen: Spreizung ≈ 20 Punkte, Spread direkt in Punkten, Brier −0,005 (signifikant), beste Gesamtzahlen in 2.1 |
| 9 | **Unsicherheitsbasiertes K** (Glicko-/Kalman-Prinzip): K proportional zur Rating-Unsicherheit, nach Saisonwechsel hoch, mit Spielen fallend | mittel | vorhanden | mehr Parameter, kein Gewinn belegt | möglicherweise besser als fester K-Boost; erst nach 1/8 testen |
| 10 | **Wahrscheinlichkeit aus Spread per Normalverteilung** statt Isotonik: `p = Φ(Spread/σ)`, σ ≈ 12,8 (aus MAE 10,2, MAE ≈ 0,8·σ, geschätzt, zu prüfen) | klein | vorhanden | σ saisonweise prüfen; Form-/Rest-Features müssten in den Spread eingehen | beseitigt exakte 0 %/100 % und die Ränder-Überkonfidenz (siehe 1.4); zusätzlich Clipping auf ca. [3 %, 97 %] |
| 11 | **Sofortfixes**: Vorzeichen im Spread-Blend, `ELO_TO_SPREAD_FACTOR` ≈ 50, Anzeige „Team −x“ | sehr klein | vorhanden | `ELO_TO_SPREAD_FACTOR` danach nicht mehr gültig, sobald Option 8 greift | gemessen: Spread-MAE −1,3; behebt die Fehlanzeige |
| 12 | **Laufendes Fortschreiben** der Ratings: neue Final-Spiele täglich verarbeiten (`process_game`), ohne alles neu zu trainieren | mittel | BallDontLie-Abfrage der Spiele seit letztem Stand (wenige Requests/Tag) | Doppelverarbeitung (IDs speichern), Spielverschiebungen, App muss neu laden | **notwendig** für „zu jedem Zeitpunkt aktuell“; ohne dies sind alle Formeln folgenlos |

**Hinweis zu Option 1 (Implementierungsdetail):** Der Saisonwechsel darf nicht erst beim ersten Spiel der neuen Saison im Training passieren. Das gespeicherte Modell wird im Oktober ohne Saison-2026-Spiele geladen; dort wären die Ratings ungeregelt. Deshalb muss `predict` die Saison des Zielspiels kennen und die Rückführung beim ersten Zugriff anwenden (Rating-Saison im Modell speichern).

### 2.3 Empfehlung und Reihenfolge

Begründung: Gemessen sind Skalierung und Aktualität die großen Hebel; die Rating-Formel liefert Zehntel. Der Rest der Lücke zum Markt am Saisonstart ist Kader-Information, die nur ein Anker (Markt, Win-Totals, Kader) liefern kann.

| Phase | Schritte | Warum zuerst |
|---|---|---|
| **A: Sofort (klein, geringes Risiko)** | (11) Vorzeichen im Spread-Blend korrigieren; Anzeige „Team −x“ statt immer „−x“; `ELO_TO_SPREAD_FACTOR` auf ca. 50 (provisorisch bis B); Wahrscheinlichkeiten clippen. (12a) Vorab: Training-Fetch-Fehler beheben (Abschnitt 4) | größter gemessener Gewinn, kein neues Modell nötig, unabhängig vom Rest |
| **B: Kernumbau** | (8) Punkte-Rating mit (1) Saison-Rückführung r ≈ 0,4 und `k ≈ 0,05`, Margin-Cap 25; (10) Wahrscheinlichkeit per Normalverteilung; (12) tägliches Fortschreiben; vorher als Parallelmodell neben dem alten betreiben und im Backtest (Abschnitt 3) vergleichen | löst Spreizung, Skalierung, 0/100 % und Aktualität zugleich |
| **C: Anker für die ersten Wochen** | (5) spielanzahl-abhängiger Markt-Anteil (Heuristik, später prüfen); (7) Win-Totals für 2026/27 manuell als Prior (30 Werte, einmal pro Saison); Schnappschüsse von Quoten täglich speichern, um künftig Option 4/5 echt testen zu können | deckt Kaderänderungen ab, ohne Großprojekt |
| **D: Später, nur bei Bedarf** | (3)/(9) K-Boost bzw. Unsicherheits-K; (6) Kader-/Verletzungsdaten (setzt eine echte Verletzungsquelle voraus; NewsAPI ist ohne Key leer); (4) Markt-implizite Ratings, falls A–C nicht reichen | hoher Aufwand, Nutzen erst nach Messung |

Nicht empfohlen: reines Option 4 (Markt als Rating), weil es die Differenz zum Markt, die die App sucht, auslöscht.

---

## 3. Backtest-Plan (Schritt 3)

### 3.1 Aufbau

- **Test-Saisons:** 2023, 2024, 2025. Jeweils Regular Season, nur Spiele, bei denen **beide Teams höchstens 20 Saisonspiele absolviert** haben (je Saison ca. 290 Spiele, zusammen n ≈ 870). Ergänzend dieselbe Auswertung für die ersten 10 Spiele und für die gesamte Saison als Kontrolle.
- **Zusätzlich** (für Stabilität): Folds 2017–2022 mit gleicher Prozedur. Mit nur 3 Saisons ist die Unsicherheit groß: paired Bootstrap zeigt für MAE-Differenzen ca. ±0,2, also können nur Unterschiede ab ca. 0,2–0,3 Punkten belegt werden.
- **Ausschluss:** 2019/20 (abgebrochene und Blase-Saison) und die Playoffs aus der Bewertung, aber **im Training behalten**. Playoffs ändern Ratings; Entscheidung ob sie mit reduziertem K laufen (z. B. 0,5) gehört als eigener Parameter in den Test.
- **Vergleichsmodell:** immer das aktuelle Modell **unverändert** (inkl. `/25`, Spread-Blend ohne Rekalibrierung) als „Status quo“. Zusätzlich „Baseline rekalibriert“ (Skala und Logistik auf frühere Saisons gefittet), damit sichtbar bleibt, wie viel aus reiner Skalierung kommt.
- **Vorab-Check:** Die Replikation der Engine im Backtest muss das gespeicherte Modell für identische Eingaben auf die Dezimalstelle treffen (z. B. Knicks–76ers 619,0).

### 3.2 Metriken

| Metrik | Definition |
|---|---|
| Spread-MAE | Mittel von \|echte Heim-Margin − Prognose\| in Punkten |
| Total-MAE | Mittel von \|echter Total − Prognose-Total\| (Prognose nach dem Blend, wo Marktdaten existieren; sonst Modell-Total) |
| Brier Score | Mittel von (p_Heimsieg − Ergebnis)² |
| Extremquote | Anteil der Prognosen mit p > 90 % oder p < 10 % (zusätzlich: Anzahl exakt 0 oder 1) |
| Zusatz | Log-Loss, Reliability-Tabelle (10 Bins), Rating-Spanne am Saisonende, Anteil Sieger richtig |

Jede Variante bekommt zu jeder Metrik die Differenz zum Status quo mit **95 %-Konfidenzintervall (paired Bootstrap über Spiele)**; Aussage nur, wenn das Intervall die 0 nicht enthält.

### 3.3 Data-Leak-Regeln

1. Alle Features (ELO-Differenz, Form, Rest) werden **vor** dem Update des jeweiligen Spiels erzeugt (so macht es `process_game` bereits). Rating-Updates dürfen erst nach dem Spiel passieren.
2. Skalierung (Spread-Faktor), Logistik/Normal-σ, Isotonik und alle Parameter (r, K, k) werden für Test-Saison *S* **nur mit Daten aus Saisons < S** gewählt. Parameterwahl über verschachtelte Walk-forward-Folds (z. B. Auswahl der Saison S−1 mit Training auf < S−1), **nicht** auf den Test-Saisons selbst. Die Vorabwerte in 2.1 sind in dieser Hinsicht optimistisch.
3. Saisonübernahme: nur Ratings des Vorjahresendes. Das tatsächliche Kader- oder Win-Total-Wissen von damals darf nur verwendet werden, wenn es **vor dem ersten Saisonspiel** öffentlich war (Quelle und Datum festhalten).
4. Markt-Varianten (4, 5): nur **Eröffnungs- oder Closing-Linien vom Tag des Spiels** mit Zeitstempel vor Spielbeginn; Closing-Linien enthalten schon Verletzungsinfos des Tages und sind daher ein *Obergrenzen-Vergleich*, keine Prognose, die ein Modell vorab hätte. Ohne historische Quoten sind 4 und 5 **nicht** rückwirkend testbar: dann nur Vorwärts-Messung ab 2026/27 mit gespeicherten Schnappschüssen.
5. Form (letzte 10 Spiele) und letzte Spieldaten laufen über Saisongrenzen. Im Test darf `last_game` des Vorjahres keinen Ruhetage-Bonus auslösen, der im Live-Betrieb anders ausfiele; dafür den Ruhetage-Faktor am Saisonbeginn ausdrücklich definieren (z. B. neutral).
6. NBA-Cup-Spiele und Ortswechsel (Spiele in Paris/Mexiko) haben abweichenden Heimvorteil. Ausnahme-Liste führen oder bewusst ignorieren und dokumentieren.
7. Keine Information aus der Zukunft über `season`-Felder oder nachträglich korrigierte Spielstände. Der Cache enthält Endstände; das ist für Test-Spiele richtig.

### 3.4 Ablauf

1. Backtest-Skript neben dem Projekt (nicht im Produktivcode), liest nur den Cache.
2. Status quo reproduzieren (Prüfwerte aus 1.1–1.5).
3. Varianten in dieser Reihenfolge: A (Skala/Vorzeichen) → 8 + 1 → +10 → +5 (nur mit Marktdaten) → 3/9.
4. Ergebnisse in eine Tabelle je Saison und gesamt; Entscheidung nach Regel: Variante wird übernommen, wenn Brier und Spread-MAE nicht schlechter sind und mindestens eine Metrik signifikant besser ist; Extremquote muss sinken.
5. Zusätzlich Vorwärtstest ab Saisonstart 2026/27: tägliches Speichern von Prognose, Marktlinie und Ergebnis (heute fehlt jede Speicherung), nach ca. 20 Spielen pro Team Auswertung.

---

## 4. Nebenpunkt: Training während der laufenden Saison (Schritt 4)

Zusätzlich zur leeren `games_2026.json` (`[]`, zählt als „vorhanden“ und wird daher nie neu geladen) ist zu beachten:

1. **Zwischenstände werden als „Final“ gecacht.** `fetcher.fetch_all_games` filtert nur auf vorhandene Scores (`home_team_score` und `visitor_team_score` wahr). Laufende oder (Halbzeit-)Zwischenstände enthalten bereits Punkte und würden als Endergebnis in den Cache und ins Training gehen. Es braucht den Filter `status == "Final"` (und Ausschluss von `postponed`). Das ergibt sich aus der Code-Logik; ob die API laufende Spiele mit Teilständen liefert, habe ich nicht gegen die API geprüft.
2. **Cache-Regel für die laufende Saison:** Die aktuelle Saison nie als „fertig“ cachen. Entweder die Datei vor jedem Training löschen oder besser inkrementell laden: nur Spiele ab dem letzten gespeicherten Datum abrufen (`start_date`), zusammenführen und **nach Spiel-ID deduplizieren**. Das spart Requests (BallDontLie-Limit des gebuchten Plans ist im Code nicht vermerkt; der Code behandelt 429 mit Wartezeiten und 1 s Pause je Seite).
3. **Saison wird fest in `config/settings.py` geführt** (`SEASONS_TO_LOAD`). Besser aus dem Datum ableiten (ab Oktober die neue Saison), sonst vergisst man das Hochzählen. Der Kommentar „11 seasons“ ist veraltet.
4. **Modell wird nicht mit neuen Spielen fortgeschrieben.** Ohne Option 12 ist jedes Neutraining ein Vollauf über alle Spiele (ca. 14 000 Spiele; mein Nachbau der Rechnung läuft in Sekunden; API-Aufwand nur für die laufende Saison).
5. **Die laufende App merkt den Wechsel nicht.** `load_or_train_model` ist `@st.cache_resource`; nach `train.py` muss Streamlit neu gestartet oder der Cache geleert werden. Die Sidebar zeigt dabei nur „ELO Model loaded“, nicht den Stand der Daten (hilfreich: Stand = letztes verarbeitetes Spieldatum anzeigen).
6. **`train.py` überschreibt `data/elo_model.pkl` ohne Sicherung.** Vor jedem Training Kopie mit Datum anlegen (wie in der README-Regel 2 verlangt).
7. **Spieldatum ist US-Datum.** BallDontLie liefert für `date` das US-Datum; Spiele nach Mitternacht deutscher Zeit gehören zum US-Vortag. Beim inkrementellen Laden und beim Fortschreiben mit US-Datum arbeiten, nicht mit `date.today()` (deutsch). Das gleiche gilt für die Ruhetage-Berechnung.
8. **Pickle-Kompatibilität:** Das Modell ist ein Pickle der Klasse `EloEngine`. Eine neue Klasse (Option 8) macht alte Pickles unbrauchbar; Versionsfeld im Modell speichern und beim Laden prüfen.
9. **Playoffs/Play-In/NBA Cup:** Entscheiden, ob sie mit gleichem K laufen (aktuell ja). Die Playoff-Erkennung in `projection.py` ist ein fester Zeitraum (15.04.–25.06.), nicht das Feld `postseason`.
10. **Tägliche Reihenfolge, wenn Option 12 umgesetzt ist:** Spiele von gestern laden → nur neue IDs verarbeiten → Modell speichern → App neu laden → Prognosen für heute.

---

## 5. Offene Fragen an dich

1. **Zielbild:** Soll das Modell eher ein eigenständiges Ergebnismodell bleiben (Abweichung vom Markt als Signal) oder ein markt-verankertes Prognosemodell werden? Die Empfehlung (C) hält beides, der Markt-Anker wirkt nur am Saisonanfang.
2. **BallDontLie-Plan:** Welche Endpunkte (Verletzungen, Kader) und welches Request-Limit gelten? Das entscheidet Option 6.
3. **Historische Quoten:** Besteht Bereitschaft, welche zu beschaffen (Zukauf oder Datensatz)? Sonst bleibt 4/5 nur vorwärts messbar.
4. **Win-Totals:** Dürfen 30 Werte pro Saison manuell gepflegt werden?
5. **Freigabe** für Phase A (Sofortfixes) getrennt von B?

---

## Anhang: Methodik und Grenzen

- Die Engine wurde im Scratchpad nachgebaut (`process_game` identisch: Heimvorteil 100, Rest −1,5/0/+0,45, Form (Wert − 0,5) × 40, MOV-Update, Off/Def-EMA α = 0,1). Das nachgebaute Basismodell trifft das gespeicherte Modell exakt bei den Beispielen (z. B. 619,0).
- Logistik im Backtest: Standardisierung plus logistische Regression auf `[ELO-Diff, Form-Diff, Ruhe-Diff]`; für Abschnitt 1.4 zusätzlich Isotonik mit 5-fach-Kalibrierung wie im Original. Im Variantenvergleich (2.1) bewusst ohne Isotonik, damit Randeffekte nicht den Vergleich verzerren.
- Spread-Prognose im Backtest: lineare Skala aus früheren Saisons (mit Achsenabschnitt), außer wo „wie eingesetzt (`/25`)“ steht.
- Grenzen: Parameter in 2.1 wurden auf überlappenden Saisons ausgewählt; keine historischen Quoten; Total-Seite und Live-Modul wurden nicht verändert oder bewertet; Kader-Daten nicht ausgewertet; Aussagen zu Odds-API-Historie, BallDontLie-Endpunkten und freien Datensätzen sind ungeprüft.
