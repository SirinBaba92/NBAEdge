# Phase B – Bericht (Stand 20.10.2026)

Grundlage: `ELO_ANALYSE.md`, Abschnitt 3. Alle Rechnungen lesen nur `data/cache` (keine API-Calls, kein Training mit API). Das alte Modell, sein Pickle (`data/elo_model.pkl`, Prüfsumme unverändert) und das Dashboard sind unverändert. Backup vor Beginn: `~/Desktop/NBAEdge_backup_2026-10-20_phaseB`, Pickle zusätzlich `~/Desktop/elo_model_2026-10-20_phaseB.pkl`.

## 1. Ergebnis in Kürze

**Übernahmeregel: im Primärfenster nicht erfüllt. Ich empfehle das neue Modell für den Saisonstart nicht als Ersatz und baue deshalb nicht weiter um** (kein Dashboard-Schalter, kein API-Update, kein v2-Pickle, siehe Abschnitt 5).

| | Ergebnis |
|---|---|
| Erste 20 Spiele je Team (2023–25, n = 873) gegen **(b) altes Modell, Faktor 50** (aktueller Dashboard-Stand) | Brier −0,0003 [−0,0046; +0,0042], Spread-MAE −0,03 [−0,16; +0,12], Log-Loss +0,002 [−0,008; +0,012]: **keine Metrik signifikant besser**. Extremquote 3,2 % → 0,1 %. |
| dasselbe gegen **(a) altes Modell unverändert** | Spread-MAE −1,35 [−1,79; −0,91], das ist aber die Wirkung des Faktors 25 → 50, den (b) schon enthält |
| Kontrolle alle Regular-Season-Spiele (2023–25, n = 3711) gegen (b) | Brier −0,0037 [−0,0059; −0,0016], Log-Loss −0,0076 [−0,0130; −0,0028], Spread-MAE −0,21 [−0,30; −0,13], Extremquote 3,0 % → 1,4 %: **signifikant besser, aber klein** (Brier ca. 1,7 %) |
| Zusatz-Folds 2021–25 (n = 1457 bzw. 6177) | gleiches Bild: früh kein signifikanter Gewinn, über die ganze Saison signifikant |

Lesart: Das Punkte-Rating ist **nicht schlechter** und über die ganze Saison **messbar etwas besser** (kalibrierter, weniger Extremwerte). In den ersten 20 Spielen, wo es der Phase wichtig war, lässt sich mit den vorhandenen Daten kein Vorteil gegenüber „altes Modell mit Faktor 50“ belegen. Der große Gewinn des Dashboards kam aus Phase A (Faktor 50, Vorzeichen).

**Totals:** Deine Vermutung stimmt, aber der Effekt zeigt sich im **Bias**, nicht im MAE. Playoffs ziehen die Off/Def-Werte der Playoff-Teams am Saisonende um ca. 9 Punkte nach unten. Der Fix „Playoffs aus Off/Def ausnehmen“ senkt den Fehler-Bias in den ersten 20 Spielen von +2,5 auf +0,7 (signifikant); der Total-MAE ändert sich kaum (siehe Abschnitt 4).

## 2. Was gebaut wurde (nichts davon ist im Dashboard aktiv)

- `models/points_rating.py`: neue Klasse `PointsRatingModel` mit Versionsfeld (`version = 2`, `load()` lehnt andere Pickles ab). Punkte-Rating, Saisonübernahme beim ersten Zugriff in neuer Saison (`ensure_season`, Saison steht im Modell), Siegwahrscheinlichkeit per Normalverteilung auf [0,03; 0,97], hca und sigma automatisch aus den letzten 4 abgeschlossenen Saisons, zwei Total-Modi, `update_with_games()` (Final-Filter, Dedupe nach Spiel-ID, gespeicherte IDs, Reihenfolge nach Datum/ID), `save()` mit Datumskopie.
- `analysis/`: Nachbau des alten Modells (geprüft: Ratings stimmen mit dem Pickle auf 6 Nachkommastellen überein), Backtest, Totals-Analyse, Tests, Ergebnisse in `analysis/results/`.

## 3. Backtest

**Aufbau:** Test-Saisons 2023, 2024, 2025 (zusätzlich 2021, 2022 als Stabilitätsprüfung). Fenster „früh“ = Regular Season, beide Teams < 20 Saisonspiele; Kontrolle = alle Regular-Season-Spiele. Alle Features sind kausal (nur Daten vor dem Spiel, Ratings werden erst nach dem Spiel aktualisiert).

**Parameterwahl (verschachtelt):** Für Test-Saison S werden r, k, Margin-Cap nur aus den inneren Walk-forward-Folds 2017 bis S−1 gewählt (Kriterium: Brier, je 50 % erste 20 Spiele / 50 % alle Spiele; Gitter 5 × 5 × 5 = 125 Läufe). Total-Parameter (Modus, α, Saisonübernahme, Playoffs ja/nein, Liga-Niveau-Rate; 200 Läufe) analog über die Total-MAE. hca und sigma stammen aus den 4 Saisons vor S. Das alte Modell bekommt seine Wahrscheinlichkeit wie die Engine-Pipeline (Logistik + Isotonik), je Saison nur auf frühere Saisons trainiert.

**Gewählte Parameter:**

| Test-Saison | r | k | Margin-Cap | Total (Modus, α, Übernahme, Playoffs) |
|---|---|---|---|---|
| 2021 | 0,4 | 0,04 | 35 | EMA, 0,10, 0,0, ja |
| 2022 | 0,4 | 0,04 | 50 | EMA, 0,15, 0,5, ja |
| 2023 | 0,5 | 0,04 | 50 | EMA, 0,15, 0,5, ja |
| 2024 | 0,4 | 0,04 | 35 | EMA, 0,15, 0,3, ja |
| 2025 | 0,4 | 0,04 | 35 | EMA, 0,15, 0,3, ja |
| alle Daten bis 2025 (für ein Endmodell) | **0,4** | **0,05** | **35** | EMA, 0,15, 0,5, ja |

Rating-Parameter sind stabil und liegen im Inneren des Gitters (r 0,4–0,5; k 0,04–0,05; Cap 35–50). Die Startwerte aus der Analyse (r 0,4, k 0,05, Cap 25) liegen praktisch gleichauf (Zeile „v0“).

### 3.1 Erste 20 Spiele je Team, 2023–25 (n = 873)

| Modell | Spread-MAE | Total-MAE | Total-Bias | Brier | Log-Loss | Extremquote (>90 % oder <10 %) | exakt 0/1 | Trefferquote |
|---|---|---|---|---|---|---|---|---|
| (a) alt, unverändert (`/25`, kein Clip) | 11,60 | 14,93 | +2,54 | 0,2109 | 0,6076 | 3,21 % | 1 | 66,2 % |
| (b) alt, Faktor 50 + Clip (Dashboard heute) | 10,27 | 14,93 | +2,54 | 0,2109 | 0,6079 | 3,21 % | 0 | 66,2 % |
| **v2 (verschachtelt gewählt)** | **10,24** | 14,90 | +1,56 | 0,2106 | 0,6097 | **0,11 %** | 0 | 65,9 % |
| v2 mit Startwerten (nicht verschachtelt) | 10,21 | 14,90 | +1,56 | 0,2095 | 0,6073 | 0,00 % | 0 | 66,8 % |

Differenz v2 − Vergleich, paired Bootstrap (2000 Ziehungen), 95 %-CI:

| Metrik | v2 − (a) | v2 − (b) |
|---|---|---|
| Spread-MAE | −1,35 [−1,79; −0,91] | −0,03 [−0,16; +0,12] |
| Total-MAE | −0,03 [−0,17; +0,10] | −0,03 [−0,17; +0,10] |
| Brier | −0,0003 [−0,0046; +0,0042] | −0,0003 [−0,0046; +0,0042] |
| Log-Loss | +0,0020 [−0,0081; +0,0124] | +0,0018 [−0,0083; +0,0122] |
| Extremquote (Prozentpunkte) | −3,09 [−4,35; −1,95] | −3,09 [−4,35; −1,95] |

Je Saison (erste 20 Spiele): 

| Saison | n | Spread-MAE (b / v2) | Brier (b / v2) | Extremquote (b / v2) | Total-Bias (b / v2) |
|---|---|---|---|---|---|
| 2023 | 293 | 10,29 / 10,29 | 0,2170 / 0,2186 | 1,7 % / 0,0 % | +1,28 / +0,82 |
| 2024 | 289 | 10,04 / 9,96 | 0,2126 / 0,2122 | 2,8 % / 0,0 % | +2,56 / +1,20 |
| 2025 | 291 | 10,48 / 10,48 | 0,2032 / 0,2011 | 5,2 % / 0,3 % | +3,77 / +2,68 |

### 3.2 Kontrolle: alle Regular-Season-Spiele 2023–25 (n = 3711)

| Modell | Spread-MAE | Total-MAE | Total-Bias | Brier | Log-Loss | Extremquote | exakt 0/1 | Trefferquote |
|---|---|---|---|---|---|---|---|---|
| (a) | 12,30 | 14,94 | +0,58 | 0,2129 | 0,6189 | 2,96 % | 5 | 66,0 % |
| (b) | 11,34 | 14,94 | +0,58 | 0,2129 | 0,6132 | 2,96 % | 0 | 66,0 % |
| **v2** | **11,13** | 14,94 | +0,33 | **0,2092** | **0,6056** | **1,40 %** | 0 | 66,7 % |
| v2 Startwerte | 11,14 | 14,94 | +0,33 | 0,2092 | 0,6058 | 1,02 % | 0 | 67,0 % |

| Metrik | v2 − (a) | v2 − (b) |
|---|---|---|
| Spread-MAE | −1,17 [−1,37; −0,98] | −0,21 [−0,30; −0,13] |
| Total-MAE | −0,00 [−0,05; +0,04] | −0,00 [−0,05; +0,04] |
| Brier | −0,0037 [−0,0059; −0,0016] | −0,0037 [−0,0059; −0,0016] |
| Log-Loss | −0,0133 [−0,0246; −0,0046] | −0,0076 [−0,0130; −0,0028] |
| Extremquote (pp) | −1,56 [−2,05; −1,08] | −1,56 [−2,05; −1,08] |

### 3.3 Zusatz-Folds 2021–25

| Fenster | n | Spread-MAE (b / v2) | Brier (b / v2) | Extremquote (b / v2) | v2 − (b) Brier [CI] | v2 − (b) Spread-MAE [CI] |
|---|---|---|---|---|---|---|
| erste 20 Spiele | 1457 | 10,38 / 10,35 | 0,2193 / 0,2175 | 3,64 % / 0,07 % | −0,0018 [−0,0053; +0,0016] | −0,03 [−0,13; +0,07] |
| alle Spiele | 6177 | 11,16 / 10,94 | 0,2194 / 0,2152 | 2,70 % / 0,94 % | −0,0042 [−0,0059; −0,0024] | −0,22 [−0,28; −0,15] |

### 3.4 Reliability (Siegwahrscheinlichkeit Heim, 2023–25)

Alle Spiele (n = 3711): p-Bereich → n, mittleres p, reale Quote

| p von | (b) n | (b) p̄ | (b) real | v2 n | v2 p̄ | v2 real |
|---|---|---|---|---|---|---|
| 0,0 | 21 | 0,054 | 0,048 | 7 | 0,076 | 0,000 |
| 0,1 | 56 | 0,158 | 0,089 | 85 | 0,164 | 0,094 |
| 0,2 | 240 | 0,262 | 0,204 | 260 | 0,256 | 0,235 |
| 0,3 | 457 | 0,352 | 0,368 | 450 | 0,352 | 0,300 |
| 0,4 | 477 | 0,456 | 0,407 | 620 | 0,451 | 0,461 |
| 0,5 | 865 | 0,547 | 0,547 | 783 | 0,550 | 0,554 |
| 0,6 | 668 | 0,661 | 0,614 | 690 | 0,649 | 0,651 |
| 0,7 | 589 | 0,739 | 0,747 | 515 | 0,747 | 0,775 |
| 0,8 | 249 | 0,850 | 0,847 | 256 | 0,841 | 0,859 |
| 0,9 | 89 | 0,950 | 0,921 | 45 | 0,921 | 0,911 |

Erste 20 Spiele (n = 873, grobe Bins):

| p von | (b) n | (b) p̄ | (b) real | v2 n | v2 p̄ | v2 real |
|---|---|---|---|---|---|---|
| 0,0 | 22 | 0,121 | 0,136 | 8 | 0,163 | 0,250 |
| 0,2 | 171 | 0,320 | 0,333 | 143 | 0,331 | 0,266 |
| 0,4 | 309 | 0,513 | 0,537 | 395 | 0,510 | 0,524 |
| 0,6 | 281 | 0,701 | 0,701 | 293 | 0,688 | 0,771 |
| 0,8 | 90 | 0,875 | 0,867 | 34 | 0,837 | 0,824 |

Lesart: v2 hat deutlich weniger Prognosen in den Rändern (konstante Normalverteilung, keine Isotonik-Plateaus). In den ersten 20 Spielen ist es im Bereich 0,6–0,8 eher zu vorsichtig (p̄ 0,69 gegen real 0,77); die Streuung ist dort kleiner als die Saison-Gesamt-sigma. Das ist ein möglicher Ansatz für eine spätere Verbesserung (sigma abhängig von der Spielanzahl), aber in diesem Test nicht belegt.

### 3.5 Prüfung der Übernahmeregel

Festgelegt vor der Auswertung: Entscheidungsfenster = erste 20 Spiele (Primärziel der Phase), Vergleich gegen (a) **und** (b); Kontrolle = alle Spiele.

| Bedingung | Erste 20 vs (a) | Erste 20 vs (b) | Alle Spiele vs (a) / (b) |
|---|---|---|---|
| Brier nicht schlechter | ja (−0,0003) | ja (−0,0003) | ja |
| Spread-MAE nicht schlechter | ja (−1,35) | ja (−0,03) | ja |
| mind. eine Metrik signifikant besser | ja (Spread-MAE; durch Faktor 25) | **nein** | ja (Brier, Spread-MAE, Log-Loss) |
| Extremquote sinkt | ja | ja | ja |
| **Regel erfüllt** | ja | **nein** | ja |

Gegen den aktuell eingesetzten Stand (b) ist die Regel im Primärfenster nicht erfüllt. „Extremquote sinkt“ ist übrigens weitgehend mechanisch (Normalverteilung ohne Plateau, harter Clip), nicht automatisch ein Güte-Beleg.

## 4. Totals: Playoff-Effekt und Fix

Skript: `analysis/totals_analysis.py`, Rohausgabe `analysis/results/totals_analysis.txt`.

**Ligamittel je Spiel (Regular Season → Playoffs):** 2021 221,2 → 212,9 (−8,4); 2022 229,3 → 219,2 (−10,1); 2023 228,4 → 211,2 (−17,1); 2024 227,6 → 217,5 (−10,0); 2025 231,2 → 215,9 (−15,3).

**Effekt auf die Off/Def-Werte (Off + Def = Team-Total-Niveau, EMA α = 0,1, wie im alten Modell):**

| Saison | Mittel aller 30 Teams: RS-Ende | nach Playoffs | Differenz | nur Playoff-Teams | Liga-Mittel RS |
|---|---|---|---|---|---|
| 2021 | 228,7 | 222,7 | −6,0 | −9,0 (20 Teams) | 221,2 |
| 2022 | 230,8 | 226,7 | −4,1 | −7,6 | 229,3 |
| 2023 | 224,0 | 219,7 | −4,3 | −8,1 | 228,4 |
| 2024 | 228,5 | 224,7 | −3,8 | −7,2 | 227,6 |
| **2025** | 233,0 | **228,1** | **−4,9** | **−9,1 (16 Teams)** | 231,2 |

Das gespeicherte Modell steht bei 228,1 (Liga-Mittel Regular Season 2025: 231,2). Der Stand nach den Playoffs liegt also ca. 3 Punkte unter dem Saisonniveau; bei den 16 Playoff-Teams, zu denen Knicks, Spurs und OKC gehören, liegt der Wert ca. 9 Punkte unter dem Stand vom Ende der Regular Season. Deine Vermutung ist damit bestätigt.

**Wirkung auf die ersten 20 Spiele (2023–25, n = 873), gleiche Spiele, feste Varianten ohne Auswahl:**

| Variante | Total-MAE | Bias (echt − Prognose) | MAE-Differenz zu A [CI] | Bias-Differenz zu A [CI] |
|---|---|---|---|---|
| A alt (EMA α 0,1, inkl. Playoffs, keine Übernahme) | 14,93 | +2,54 | | |
| **B EMA ohne Playoffs** | **14,79** | +0,71 | −0,14 [−0,33; +0,06] | **−1,83 [−1,99; −1,68]** |
| C B + Übernahme 50 % zum Ligamittel | 14,87 | +0,57 | −0,06 [−0,27; +0,15] | −1,97 [−2,14; −1,79] |
| D Liga-Niveau + Team-Abweichung, ohne Playoffs, Übernahme 50 % | 15,02 | +0,12 | +0,10 [−0,15; +0,35] | −2,42 [−2,62; −2,22] |
| E wie D, aber mit Playoffs | 15,01 | +0,97 | +0,08 [−0,10; +0,27] | −1,57 [−1,73; −1,42] |
| F wie D, keine Team-Übernahme | 14,93 | +0,18 | −0,00 [−0,24; +0,24] | −2,36 [−2,55; −2,18] |
| G verschachtelt gewählt (EMA, α 0,15, mit Playoffs) | 14,90 | +1,56 | −0,03 [−0,17; +0,10] | −0,97 [−1,09; −0,87] |

Alle Spiele (n = 3711): MAE 14,91–14,97 für alle Varianten, Bias A +0,58, B +0,09, D +0,02.

Aussagen:
- **Playoffs ausnehmen wirkt auf den Bias** (−1,8 Punkte, signifikant), kaum auf den Total-MAE (−0,14, nicht signifikant). Der Total-MAE ist von der Spielstreuung dominiert (Std eines Totals ca. 21 Punkte); jede getestete Variante landet bei 14,8–15,0.
- Die verschachtelte Wahl bevorzugt „mit Playoffs, α 0,15“, weil der MAE die Varianten nicht trennt. Ich folge dafür nicht der automatischen Wahl, sondern schlage B vor, da es als einzige Änderung eine klare, signifikante Bias-Korrektur ohne MAE-Verlust liefert. Das ist eine Entscheidung nach Bias, nicht nach dem vorab festgelegten Kriterium, und als solche gekennzeichnet.
- **Heute Abend (Roh-Totals ohne Markt-Blend):**

| Spiel | Markt | alt (Pickle) | B | C | D | G |
|---|---|---|---|---|---|---|
| Knicks – 76ers | 232,0 | 217,9 (−14,1) | 223,1 (−8,9) | 227,1 (−4,9) | 228,7 (−3,3) | 223,8 (−8,2) |
| Spurs – OKC | 230,7 | 219,9 (−10,8) | 232,4 (+1,7) | 231,8 (+1,1) | 233,2 (+2,5) | 224,3 (−6,4) |
| Pistons – Celtics | 219,8 | 216,2 (−3,6) | 227,2 (+7,4) | 229,2 (+9,4) | 230,6 (+10,8) | 223,1 (+3,3) |

Der Fix erklärt einen großen Teil der Lücke bei Spurs–OKC (−10,8 → +1,7) und einen Teil bei Knicks–76ers (−14,1 → −8,9). Bei Pistons–Celtics überschießt er (Markt 219,8, also ein ungewöhnlich niedriger Marktwert, den kein Modell ohne Kader- oder Tempo-Information erklärt). Der Rest sind spielspezifische Marktinformationen (Aufstellung, Tempo), die das Modell nicht kennt.

**Vorschlag (nicht umgesetzt, da du dort nichts ändern wolltest):** Im alten `EloEngine.process_game` die Off/Def-Aktualisierung nur für Regular-Season-Spiele ausführen (`postseason == False`). Eine Zeile plus Neutraining aus dem Cache. Eine Saisonübernahme zum Ligamittel (C/D) bringt dagegen keinen belegbaren Zusatznutzen.

## 5. Nicht umgesetzt, weil die Übernahmeregel nicht erfüllt ist

Gemäß deiner Vorgabe habe ich nach dem Backtest nichts weiter gebaut:

- kein `data/game_updates.py` (Abruf der Final-Spiele ab dem letzten Stand per US-Datum),
- kein Update-Skript, kein v2-Pickle (`data/points_rating_v2.pkl` existiert nicht),
- **keine** Änderung an `app.py` (der Sidebar-Schalter „Modell v2 (Test)“ ist nicht eingebaut).

Die Kernfunktionen sind dagegen schon in der Klasse vorhanden und mit simulierten Daten getestet (`analysis/test_points_rating.py`, 15 von 15 bestanden): Saisonübernahme beim ersten Zugriff (nur einmal, Saison im Modell), Final-Filter, Dedupe nach ID, Reihenfolge, inkrementelles Fortschreiben liefert exakt das gleiche Modell wie ein Gesamtlauf, Datumskopie, Versionsprüfung (das alte ELO-Pickle wird abgelehnt). Das Netzwerk wird dabei nicht benutzt.

**Wichtig unabhängig vom Modell:** Auch das alte Modell wird nicht fortgeschrieben (Ratings, Form, Ruhetage stehen auf dem 13.06.2026). Das tägliche Fortschreiben ist unabhängig von dieser Entscheidung der größte offene Punkt für aktuelle Ratings. Dieselbe Update-Logik ließe sich auch für `EloEngine` bauen.

## 6. Mögliche nächste Schritte (zur Entscheidung)

1. **Totals-Fix im alten Modell** (Playoffs aus Off/Def): klein, belegter Bias-Gewinn.
2. **Fortschreiben** (US-Datum, Final-Filter, Dedupe, Datumskopie) für das alte Modell, sobald du es freigibst. Der Code dafür ist mit `update_with_games` bereits entworfen und getestet.
3. **v2 trotzdem als Test-Schalter einbauen**, wenn du den signifikanten, kleinen Vorteil über die ganze Saison (Brier −0,004, weniger Extremwerte) für ausreichend hältst. Das widerspricht der Regel im Primärfenster; es wäre deine Entscheidung. Aufwand: Pickle aus dem Cache bauen, Abruf-Modul, Sidebar-Schalter (ca. ein Arbeitsgang).
4. Sigma abhängig von der Spielanzahl (Reliability zeigt Unterkonfidenz in den ersten Wochen), Phase C (Markt-Anker, Win-Totals) bleibt der Hebel für Kaderänderungen.

## 7. Grenzen

- Nur 3 Test-Saisons mit ca. 290 Spielen je Saison im Frühfenster; Bootstrap-CIs für MAE-Differenzen etwa ±0,15, daher sind kleine Unterschiede nicht nachweisbar. Die Zusatz-Folds 2021–22 bestätigen das Bild, ersetzen aber keine Vorwärtsmessung.
- Parameter des Gitters sind verschachtelt gewählt; die Gittergrenzen wurden nach einem ersten Lauf erweitert (Cap 50/80, α 0,2/0,3), damit keine Wahl am Rand liegt. Der Erstlauf mit engerem Gitter ergab dieselben Schlussfolgerungen.
- Total-Auswahl nach MAE trennt die Varianten nicht; der Fix-Vorschlag beruht auf dem Bias.
- Kein Markt-Vergleich (keine historischen Quoten), Playoff-Spiele werden im Rating mit vollem k gelernt (nicht getunt), Rest/Form-Features fehlen im neuen Modell (altes Modell enthält sie, Wirkung klein).
- Kleine Zahl exakt-0/1-Fälle im alten Modell (1 bzw. 5), daher ist die Extremquote kein starker Gütebeleg.

## 8. Dateien

Neu:
- `models/points_rating.py`: neue Klasse `PointsRatingModel` (Versionsfeld, Saisonübernahme, Normalverteilung, Fortschreiben, Speichern mit Datumskopie).
- `analysis/bt_common.py`: Laden der Cache-Spiele, Metrik-Helfer, Bootstrap.
- `analysis/bt_v2.py`: Backtest-Lauf der neuen Klasse mit Vorhersagen vor jedem Spiel.
- `analysis/old_engine_replica.py`: Nachbau des alten Modells (mit Selbsttest gegen das Pickle).
- `analysis/backtest_phase_b.py`: verschachtelter Walk-forward-Backtest, Bootstrap, Übernahmeregel.
- `analysis/totals_analysis.py`: Playoff-Effekt auf Off/Def und Totals-Varianten.
- `analysis/test_points_rating.py`: Tests mit simulierten Daten (15 Prüfungen).
- `analysis/results/phase_b_results.json`, `analysis/results/totals_analysis.txt`: Rohergebnisse.
- `PHASE_B_BERICHT.md`: dieser Bericht.
- Backups: `~/Desktop/NBAEdge_backup_2026-10-20_phaseB`, `~/Desktop/elo_model_2026-10-20_phaseB.pkl`.

Geändert: keine Projektdatei. (`app.py`, `config/`, `data/`, `engine/`, `models/elo.py` und das Pickle sind unverändert.)

Neu starten: `venv/bin/python analysis/backtest_phase_b.py` (ca. 3,5 Minuten), `venv/bin/python analysis/totals_analysis.py`, `venv/bin/python analysis/test_points_rating.py`.
