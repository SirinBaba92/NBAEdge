# 🏀 NBAEdge

Streamlit-Dashboard zur systematischen Analyse von NBA-Spielen: findet **Value Bets**, projiziert **Spielstände und Totals**, analysiert **Live-Spiele** (Quarter-Over/Under, Team Totals, Player Props) und lernt aus vergangenen Fehlern (**Self-Correction**).

> **Nur für Recherche- und Analysezwecke. Kein Anlageversprechen. Verantwortungsvoll wetten.**

---

## ⚠️ Wichtig: Welcher Ordner ist der richtige? (Stand 26.09.2026)

**Dieser Ordner (`Desktop/NBAEdge`) ist der Hauptstand.** Er wurde am 26.09.2026 aus `Ordnung bringen/NBAEdge 6` kopiert (`app.py` vom 14.06.2026, 90 856 Bytes, 2175 Zeilen).

- Arbeite **nur hier** weiter. Keine neuen Kopien mit Namen wie `NBAEdge 7 neu final` anlegen.
- `Desktop/Ordnung bringen/NBAEdge 6` ist unverändert und dient als **Backup** dieses Stands.
- Erkennungsmerkmal der richtigen Version: `app.py` hat **7 Tabs**, darunter **„🎯 Live Bet Tracker“**. Hat eine `app.py` nur 5 Tabs, ist es eine alte Version.

### Versionsgeschichte (aus den Änderungsdaten rekonstruiert)

| Version / Ordner | Stand | Merkmale |
|---|---|---|
| `NBA Prediction App Backup` | 05.05.2026 | 5 Tabs (Value Bets, Score Projections, Live, Gestern, ELO Rankings), Google-Sheets-Export, `app.py` ca. 560 Zeilen |
| `nbaedge` / `NBA Prediction App` | 13.05.2026 | Umbau, `compute_projection` ausgelagert |
| `NBAEdge 4` | 16.05.2026 | 6 Tabs |
| `NBAEdge 5` | 18.05.2026 | 6 Tabs, ca. 1360 Zeilen |
| `NBAEdge 6` (älterer Stand) | 03.06.2026 | 6 Tabs, ca. 1980 Zeilen (identisch mit `NBAEdge 6 v2`) |
| **`NBAEdge 6` (aktuell)** | **14.06.2026** | **7 Tabs, `Live Bet Tracker`, `live_bet_tracker.py`, Market-History, `nba_player_stats.py`** |

Gegenüber den ganz alten Versionen (05.05.) sind **weggefallen**:
- der **Google-Sheets-Export** (`gspread` wird nicht mehr benutzt),
- der Tab „Live“ auf Basis von BallDontLie (ersetzt durch „Live Projection“ über die NBA-Live-Daten),
- der feste „2-Tage Hit Rate“ im Gestern-Tab (ersetzt durch „History“ mit einstellbarem Zeitraum).

### Andere Projekte auf dem Desktop (gehören NICHT zu NBAEdge)
`Prognostico-main`, `Sportwetten/...` und die `sportwetten-analyse`-Ordner in `Ordnung bringen` sind eigene Projekte mit eigener `app.py`. Bitte nicht mit NBAEdge vermischen.

---

## 🚀 Schnellstart

Voraussetzung: Python 3.11 (getestet mit 3.11.9).

```bash
cd ~/Desktop/NBAEdge

# 1. Virtuelle Umgebung anlegen (nur beim ersten Mal, der Ordner venv/ existiert seit 26.09.2026)
python3 -m venv venv
source venv/bin/activate

# 2. Abhängigkeiten installieren
pip install -r requirements.txt

# 3. API-Keys in .env eintragen (siehe unten)

# 4. Starten
streamlit run app.py
```

Das ELO-Modell (`data/elo_model.pkl`) liegt bereits im Ordner, ein Training ist nicht nötig. Nur wenn die Datei fehlt oder du neu trainieren willst:

```bash
python train.py
```

> **Hinweis zu scikit-learn:** Das Modell (`data/elo_model.pkl`) ist eine Pickle-Datei und wurde mit **scikit-learn 1.4.0** gespeichert. `requirements.txt` nutzt aber **1.6.1**. Beim Laden erscheint deshalb die Warnung `InconsistentVersionWarning`. Die App läuft trotzdem, und die Vorhersagen sind plausibel. Manche wirken aber sehr extrem (z. B. 100 % Heimsieg für OKC gegen Utah). Ob das an der Versionsdifferenz liegt, ist nicht geprüft. Sauberste Lösung: einmal `python train.py` ausführen. Dann passt das Modell zur installierten Version.

---

## 🔑 API-Keys (`.env`)

Die Datei `.env` liegt im Projektordner. **Niemals veröffentlichen oder in ein Git-Repository einchecken.**

| Variable | Pflicht? | Wofür |
|---|---|---|
| `BALLDONTLIE_API_KEY` | ja | Spielpläne, Ergebnisse, Training der ELO-Historie, Spieler-Stats (BallDontLie) |
| `ODDS_API_KEY` | ja | Quoten, Totals, Spreads (The Odds API) |
| `NEWS_API_KEY` | optional | Lineup-/Verletzungs-News (NewsAPI). Ohne Key bleibt der News-Tab leer |

---

## 🧭 Was die App macht (Tabs)

| Tab | Inhalt |
|---|---|
| **🎯 Value Bets** | Vergleicht die Modell-Wahrscheinlichkeit mit den Quoten der Buchmacher und zeigt Wetten mit positivem Erwartungswert (EV) samt Kelly-Einsatz. Gruppiert nach Spiel |
| **📊 Score Projections** | Projizierter Endstand pro Spiel (Home/Away), Spread und Total, verglichen mit den Markt-Linien. Warnung, wenn Modell und Markt stark abweichen (mögliche Verletzung prüfen) |
| **🔴 Live Projection** | Live-Analyse laufender Spiele: Team-Total-Projektion, Quarter Over/Under, Quarter Team Total, Player Props (Pre-Game), Live-Bet-Log. Quelle `LIVE` (NBA-Daten) oder `MOCK` (Testdaten, mit Replay-Modus) |
| **🎯 Live Bet Tracker** | Eigene „Points Over“-Wetten auf Spieler eintragen und live gegen die Boxscore-Punkte verfolgen |
| **📰 Lineup News** | Aktuelle Verletzungs-/Lineup-News je Team (nur mit `NEWS_API_KEY`) |
| **📅 History** | Vergleicht vergangene Projektionen mit echten Ergebnissen (1–14 Tage), zeigt Hit Rate, Team-Bias-Tracking, CSV-Download und die Self-Correction |
| **📈 ELO Rankings** | Balkendiagramm der Team-ELO-Werte |

**Sidebar:** Refresh Odds, Filter (Min EV %, Min/Max Odds, Buchmacher, „nur Bet Targets“) und Modell-Infos.

---

## 🧮 Wie es rechnet

### 1. ELO-Modell (`models/elo.py`)
- Trainiert auf den Saisons **2015–2025** (`config/settings.py`).
- ELO mit **Margin-of-Victory-Multiplikator**, **Heimvorteil** (100 Punkte), **Rest-Days-Faktor** (Back-to-Back = Malus, 3+ Ruhetage = kleiner Bonus) und **Form** (gewichtete Siegquote der letzten 10 Spiele).
- Zusätzlich Offense-/Defense-Ratings (rollierender Punkteschnitt) für den erwarteten Total.
- Siegwahrscheinlichkeit: **logistische Regression** (kalibriert, isotonisch, 5-fach CV) auf ELO-Differenz, Form-Differenz und Rest-Differenz.

### 2. Score-Projektion (`engine/projection.py`)
- **Spread** = ELO-Differenz / 50 (`ELO_TO_SPREAD_FACTOR`; bis 20.10.2026 25). Konvention überall: positiv = Heimteam ist Favorit. Der Odds-API-Spread wird beim Einlesen umgedreht (`data/odds.py`).
- **Total**: Modell-Total wird mit dem Markt-Total gemischt. Der Markt-Anteil steigt mit der Abweichung:

  | Abweichung Modell ↔ Markt | Markt-Gewicht |
  |---|---|
  | < 7 Punkte | 32 % |
  | ≥ 7 | 40 % |
  | ≥ 10 | 48 % (dazu `lineup_warning`) |
  | ≥ 14 | 55 % |

- Spread wird zu 25 % mit dem Markt-Spread gemischt (falls vorhanden).
- **Playoff-Anpassung** (15.04.–25.06.): Total −4, Spread × 0,96.
- **Team-Bias** (Self-Correction): pro Team ein Punkte-Zuschlag/-Abschlag aus vergangenen Fehlern, maximal ±6 Punkte, erst ab 2 Spielen.

### 3. Value Bets (`engine/ev.py`)
- Sharp-Referenz: **Pinnacle / Betfair** (faire Quoten ohne Marge).
- Gemischte Wahrscheinlichkeit = **30 % Modell + 70 % Sharp-Buch** (ohne Sharp-Quote nur Modell).
- **EV** = `p · (Quote − 1) − (1 − p)`.
- **Kelly** = `(p · Quote − 1) / (Quote − 1)`, gedeckelt bei **3 %** der Bankroll, nie negativ.
- Angezeigt wird ab **3 % EV** (Slider in der Sidebar änderbar). Gewettet werden soll bei den „Bet Targets“ (Pinnacle, Betfair), gerechnet wird gegen die Soft-Books.

### 4. Live-Engine (`engine/live.py` und Helfer)
Projiziert den Endstand aus dem aktuellen Spielstand und korrigiert mit Faktoren:
- Tempo (Pace) und Spielstand-Situation (knapp, Blowout),
- Momentum/Runs (`engine/momentum.py`),
- Ballbesitze und Offense-/Defense-Rating (`engine/possessions.py`),
- Team-Fouls und Bonus, Play-by-Play-Signale,
- Marktbewegung (`data/live_market.py`).

Ergebnis: Projektion, Lean (Over/Under), Über-Wahrscheinlichkeit und Edge-Erkennung gegen die Live-Linie.

### 5. Player Props (`engine/player_props.py`)
Punkte-Projektion aus Saison- und Letzte-5-Schnitt (55 % / 45 %), erwarteten Minuten, Pace, gegnerischer Defense, Blowout-Risiko und True Shooting.

---

## 🗂️ Ordnerstruktur

```
NBAEdge/
├── app.py                  Streamlit-App (alle 7 Tabs, Sidebar, Datenladen)
├── train.py                ELO-Modell einmalig trainieren
├── save_mock_data.py       Testdaten (Mock) aus echten Spielen speichern
├── test_replay.py          Kleines Replay-Beispiel
├── requirements.txt        Python-Abhängigkeiten
├── .env                    API-Keys (geheim!)
├── config/
│   ├── settings.py         Alle Stellschrauben (ELO, EV, Kelly, Buchmacher, Saisons)
│   └── runtime.py          OFFLINE_AUDIT_MODE an/aus
├── models/
│   └── elo.py              ELO-Engine, Training, Speichern/Laden
├── engine/
│   ├── ev.py               EV, Kelly, Value-Bet-Suche
│   ├── projection.py       Score-Projektion (Modell + Markt + Playoff + Bias)
│   ├── bias.py             Self-Correction (Team-Bias laden/speichern/berechnen)
│   ├── live.py             Live-Projektionen (Total, Quarter, Quarter-Team-Total)
│   ├── live_context.py     Baut den Live-Kontext aus Boxscore/Play-by-Play
│   ├── momentum.py         Runs, Droughts, Volatilität
│   ├── possessions.py      Ballbesitz-Schätzung, Off-/Def-Rating
│   ├── replay.py           Replay: Spielzustand zu einer bestimmten Spielminute
│   ├── player_props.py     Player-Props-Projektion
│   └── live_bet_tracker.py Live-Status der eigenen Spieler-Wetten
├── data/
│   ├── elo_model.pkl       Trainiertes Modell
│   ├── cache/              Spielhistorie pro Saison (games_2015.json ... games_2025.json)
│   ├── mock/               Testdaten (Scoreboard, Boxscore, Play-by-Play)
│   ├── market_history/     Aufgezeichnete Live-Marktlinien je Spiel (.jsonl)
│   ├── live_bets.json      Deine Live-Bet-Tracker-Wetten
│   ├── bias_adjustments.json  (entsteht erst, wenn Self-Correction gespeichert wird)
│   ├── fetcher.py          BallDontLie: Spiele/Saisons
│   ├── odds.py             The Odds API: Quoten, Totals, Spreads
│   ├── live_market.py      Live-Marktlinien + Bewegungssignal
│   ├── nba_live.py         NBA-Live-Daten (Scoreboard, Boxscore, Play-by-Play)
│   ├── player_stats.py     Spieler-Stats über BallDontLie
│   ├── nba_player_stats.py Spieler-Stats über nba_api
│   ├── injuries.py         NewsAPI: Lineup-/Verletzungs-News
│   └── mock_loader.py      Lädt die Mock-Daten
├── ui/
│   └── live_dashboard.py   Darstellung des Live-Trading-Dashboards
└── tests/                  Regressionstests und Audit (siehe tests/README.md)
```

---

## ⚙️ Wichtige Stellschrauben (`config/settings.py`)

| Einstellung | Wert | Bedeutung |
|---|---|---|
| `SEASONS_TO_LOAD` | 2015–2025 | Trainingssaisons |
| `ELO_K_FACTOR` | 20 | Lerngeschwindigkeit des ELO |
| `HOME_COURT_ADVANTAGE` | 100 | Heimvorteil in ELO-Punkten |
| `FORM_WINDOW` | 10 | Spiele für die Form |
| `MIN_EV_THRESHOLD` | 0.03 | Mindest-EV (3 %) |
| `MAX_KELLY` | 0.03 | Maximaler Einsatz (3 % der Bankroll) |
| `SHARP_BOOKS` | Pinnacle, Betfair | Referenz für faire Quoten |
| `BET_TARGETS` | Pinnacle, Betfair | Wo gewettet werden soll |
| `SOFT_BOOKS` | DraftKings, FanDuel, BetMGM, Caesars, Bovada | Werden gegen Sharp geprüft |
| `ELO_TO_SPREAD_FACTOR` | 50 | ELO-Differenz → Spread (Analyse: 50,8) |
| `MIN_WIN_PROB` / `MAX_WIN_PROB` | 0,03 / 0,97 | Begrenzung der Siegwahrscheinlichkeit beim Auslesen |

`config/runtime.py` enthält `OFFLINE_AUDIT_MODE`. Bei `True` nutzt die App nur Testdaten aus `data/mock/` und ruft keine externen APIs auf.

---

## 🌐 Externe Datenquellen

| Quelle | Genutzt für |
|---|---|
| BallDontLie (`api.balldontlie.io`) | Spielplan, Ergebnisse, Training, Spieler-Stats |
| The Odds API (`api.the-odds-api.com`) | Moneyline, Totals, Spreads, Live-Marktlinien |
| NBA CDN (`cdn.nba.com`) | Live-Scoreboard, Boxscore, Play-by-Play |
| `nba_api` (Python-Paket) | Spieler-Stats (alternative Quelle) |
| NewsAPI (`newsapi.org`) | Lineup-/Verletzungs-News (optional) |

Die Odds API hat ein Anfragen-Limit. Nach jedem Abruf wird die Restanzahl im Terminal ausgegeben.

---

## 🧪 Tests und Offline-Modus

Details in `tests/README.md`. Kurz:

```bash
python3 tests/test_replay_regression.py   # Replay-Regressionstests
python3 tests/run_full_audit.py           # Tabellarischer Voll-Audit (Minuten 5/10/15/20/30/40)
```

Offline testen: in `config/runtime.py` `OFFLINE_AUDIT_MODE = True` setzen. **Danach wieder auf `False` zurückstellen**, sonst zeigt die App nur Testdaten.

---

## 🏀 Neue Saison starten (Oktober)

Die Saison 2025/26 endete im Juni 2026. Sobald die neue Saison 2026/27 im Oktober beginnt, **vor dem ersten echten Einsatz** folgende drei Schritte durchführen. Ohne sie rechnet das Modell weiter mit dem Stand vom Juni.

**1. Alten Cache der laufenden Saison löschen**

Der Cache-Ordner speichert die Saisons einzeln (`games_2015.json` … `games_2025.json`). Die Datei der zuletzt gecachten, jetzt aber noch nicht abgeschlossenen Saison muss weg, damit `train.py` sie mit den fehlenden Spielen (Playoffs etc.) neu lädt:

```bash
cd ~/Desktop/NBAEdge
source venv/bin/activate
rm data/cache/games_2025.json
```

**2. Neue Saison in `config/settings.py` eintragen**

```python
# vorher:
SEASONS_TO_LOAD = list(range(2015, 2026))  # 11 seasons for ELO training

# nachher:
SEASONS_TO_LOAD = list(range(2015, 2027))  # 12 seasons for ELO training
```

**3. Modell neu trainieren**

```bash
python train.py
```

Das Skript fragt „Model already exists. Retrain? [y/N]“ – mit `y` bestätigen. Es lädt dann alle Saisons aus `SEASONS_TO_LOAD` (die meisten aus dem Cache, 2025 und 2026 neu von BallDontLie) und schreibt ein frisches `data/elo_model.pkl`.

**Danach kontrollieren:**
- `config/runtime.py`: `OFFLINE_AUDIT_MODE = False` (falls zum Testen zwischenzeitlich auf `True` gestellt).
- App starten (`streamlit run app.py`) und in der Sidebar „✓ ELO Model loaded“ sowie ein aktuelles Team in **📈 ELO Rankings** prüfen.
- Tab **🎯 Value Bets** → **🔄 Refresh Odds** klicken. Sobald die Saison läuft, sollten hier wieder Spiele und ggf. Value Bets erscheinen.

> Dieselben drei Schritte gelten für **jede** neue Saison, nicht nur 2026/27. Immer die Datei der letzten (jetzt abgeschlossenen) Saison löschen und die Jahreszahl in `SEASONS_TO_LOAD` um eins erhöhen.

---

## 🛠️ Typische Aufgaben

| Ich will ... | Dann ... |
|---|---|
| die App starten | `streamlit run app.py` |
| das Modell neu trainieren | `python train.py` (antwortet `y` bei der Rückfrage) |
| aktuelle Quoten laden | in der Sidebar **🔄 Refresh Odds** |
| Mindest-EV ändern | Slider „Min EV %“ (Sidebar) oder `MIN_EV_THRESHOLD` in `config/settings.py` |
| Self-Correction aktivieren | Tab **📅 History** → **💾 Self-Correction aus History speichern**, danach **Refresh Odds** |
| Self-Correction zurücksetzen | Tab **📅 History** → **🧹 Self-Correction löschen** |
| eine Spieler-Wette live verfolgen | Tab **🎯 Live Bet Tracker** → Name und Linie eintragen |
| ohne Internet/API testen | `OFFLINE_AUDIT_MODE = True` |
| neue Saison startet (Oktober) | Abschnitt **🏀 Neue Saison starten** oben befolgen: alten Cache löschen, `SEASONS_TO_LOAD` erweitern, `python train.py` |

---

## 📌 Bekannte Stolpersteine

- **`venv` aktivieren:** Vor dem Start `source venv/bin/activate` ausführen. Das globale Python hat andere Paketversionen (z. B. scikit-learn 1.8.0, streamlit 1.32.0) und ist nicht getestet.
- **Saisonpause:** Zwischen Juni und Oktober gibt es keine Spiele. Dann sind Value Bets, Projektionen, History und der Live-Tab (`LIVE`) leer, und der Live-Tab meldet `403 Forbidden` von der NBA-Adresse. Das ist normal. Zum Testen die Quelle **MOCK** wählen.
- **Live-Bet-Tracker** liest `data/live_bets.json` mit relativem Pfad. Die App deshalb immer **aus dem Projektordner** starten (`cd ~/Desktop/NBAEdge`).
- **Live-Bet-Tracker** unterstützt aktuell nur den Typ `points_over`.
- **Lineup-Warnung**: Weicht das Modell um 10+ Punkte vom Markt-Total ab, fehlt meist ein Spieler im Modell. Vor einer Wette Verletzungen prüfen.
- **Backtest-Trefferquote**: Frühere Versionen zeigten „57,8 %“ in der Sidebar. Dieser Wert war fest eingetragen und ist in der aktuellen Version nicht mehr enthalten. Die tatsächliche Trefferquote zeigt der Tab **History**.

---

## 📋 Regeln, damit wir nicht wieder durcheinanderkommen

1. **Ein Hauptordner:** `Desktop/NBAEdge`. Nur hier entwickeln.
2. **Vor größeren Änderungen** einen Backup-Ordner mit Datum anlegen, zum Beispiel `NBAEdge_backup_2026-09-26`. Nicht `final`, `neu` oder `v2` im Namen.
3. **Jede Änderung unten im Änderungsprotokoll eintragen** (Datum, was, warum).
4. **Keine Kopie des Projekts zwischen Ordnern hin- und herschieben**, ohne vorher zu prüfen, welche `app.py` neuer ist (`ls -l` oder Änderungsdatum).
5. **`.env` und `data/bias_adjustments.json`** gehören zu deinem lokalen Stand und werden bei einer Neu-Kopie nicht automatisch mitgenommen.

---

## 📝 Änderungsprotokoll

| Datum | Änderung |
|---|---|
| 21.10.2026 | Schritt 9b: (1) Korrektur 9a: eigene Linien gelten auch für laufende/beendete Spiele (Vorab-Linien), Cache für gestartete Spiele nur die gespeicherte Vorab-Linie; (2) Score Projections: unter jeder Karte vier Expander SPREAD / TOTAL / TEAM TOTAL Gast / Heim mit Wahrscheinlichkeits-Balken je Linie (`engine/line_probabilities.py`, reine Anzeige, Normalverteilung, eigene Linien oder feste Staffel); (3) Fund im echten Browser: der erste Rerun nach dem Laden baute alle Tab-Inhalte neu auf (Expander wieder zu) – behoben durch `_boot_slot` in `app.py` (gilt auch für die Expander der Pre-Match Eingabe aus Schritt 8); Tests `test_line_probabilities.py`, `browser_score_check.py` |
| 21.10.2026 | Schritt 9b-2: Zeilen der Expander größer (16 px, Balken 14 px, ≥ 44 px) und einheitliche Hervorhebung: wahrscheinlichere Seite orange mit Plakette (Over/Under, Gast/Heim), andere gedämpft, 50 : 50 ohne Plakette; schmale Ansicht zweizeilig (< 1200 px); Fund: Expander-Zustand wanderte bei geänderter Kartenreihenfolge zum falschen Spiel – behoben mit festem Container je Spiel + CSS-`order`; Test in `browser_score_check.py` |
| 21.10.2026 | Schritt 9c: Plaketten mit weißer Fettschrift (Hintergrund `#ea580c`, Kontrast 3,56 : 1); Schnappschuss der Projektion vor dem Anpfiff (`data/projection_snapshots.py`, `data/tracking/projection_snapshots.json`, nur bei geändertem Inhalt, ab Anpfiff gesperrt); Endergebnis durch `update_model.py` (Fehler → `WARN`, Modell-Update läuft weiter) bzw. aus `upcoming_cache.json`; Chips „eingetreten / nicht eingetreten / Push“ in den Expander-Zeilen beendeter Spiele (Karte aus dem Schnappschuss, 24 Std.); Auswertung `analysis/eval_snapshots.py`; Tests `test_snapshots.py`, `browser_score_check.py` erweitert |
| 21.10.2026 | Schritt 10: Terminal-Eingabe `eingabe.py` (`venv/bin/python eingabe.py`) für Pre-Match-Linien und Quoten, Betano-Reihenfolge Heim vor Gast, eine Frage pro Eingabe (Sieger, Spread bis 5 Linien mit Betano-Vorzeichen, Total mit automatischer Leiter ±3, Team Totals mit Schleife, Spieler-Meilensteine Start-/End-Linie); Enter = behalten, `x` entfernen, `z` zurück, `q` beenden; speichert über `pre_match_store.save_card` (Revisionen, atomar, Tageskopie), liest vor dem Speichern frisch und schreibt nur geänderte Zeilen (App/Tab darf parallel laufen); keine API-Abrufe (Spieleliste aus `upcoming_cache.json`, Kader aus `rosters.json`); Spread-Limit im Tab von 3 auf 4 weitere Linien (5 wie die Leiter), `MAX_SPREAD_EXTRA` im Store; Test `tests/test_eingabe.py` |
| 21.10.2026 | Schritt 11: Spieler-Limit je Spiel von 10 auf 20 (`MAX_PLAYERS` im Store, Tab und `eingabe.py` lesen es von dort; `eingabe.py` fragt die Spielerzahl je Team nur bis zu den noch freien Plätzen ab); Hilfsskript `eingabe_wiederholen.py <Protokoll> <Spielnummer> [--korrektur "Frage=Antwort"]` spielt die Eingaben eines `eingabe.py`-Terminalprotokolls bis zur Zusammenfassung ein und übergibt die letzte Bestätigung („Speichern?“) an die Tastatur (Fragen werden mit dem Protokoll verglichen, Abbruch bei Abweichung, Datei wird nur gelesen); Tests `test_eingabe_wiederholen.py`, `test_eingabe.py`/`test_pre_match_players.py`/`browser_fragment_check.py` (20 Spieler) erweitert |
| 21.10.2026 | Schritt 12: `eingabe.py` – am „Speichern?“-Prompt springt `s` per nummeriertem Menü (1 Sieger, 2 Spread, 3 Total, 4/5 Team Total Heim/Gast, 6/7 Spieler Heim/Gast) in einen einzelnen Bereich und kehrt danach direkt zur Zusammenfassung zurück (die Antworten werden je Bereich gemerkt; `z` am Bereichsanfang bricht den Sprung ab); Total-Duplikate behoben: gespeicherte Zusatzlinien auf einer neuen Leiter-Linie werden überschrieben, auf der neuen Hauptlinie ersetzt, bei geänderter Richtung neu angelegt; nur wirklich nicht passende lösen die Rückfrage aus (Vorgabe jetzt Enter = entfernen, `n` = behalten); Entfernungen laufen erst nach einer erfolgreichen Prüfung (`save_card(..., assume_removed, dry_run)`), ein abgelehntes Speichern entfernt nichts mehr; Fehlermeldungen nennen `s` mit der Menünummer; Tests in `test_eingabe.py` |
| 22.10.2026 | Betano-Import: `betano_import.py [Spielnummer]` holt die Quoten direkt bei Betano (Tab „Alle“, `bt=6`; Mitschnitt zum Testen: `--datei`) und beantwortet damit die Fragen von `eingabe.py` (Sieger; Spread Hauptlinie ±2 Linien; Total Hauptlinie ±3 Linien; Team Totals; Spieler-Meilensteine aller im Kader gefundenen Spieler, höchstens 10 Linien je Spieler); gespeichert wird erst nach deinem Enter bei „Speichern?“; Abruf: Spielliste + 1 Abruf je Spiel, 3 s Pause (nur mit Erlaubnis von Betano, im Test nie ausgeführt); Verbindungstests `betano_test.py`, `betano_test_spiel.py`; Tests `tests/test_betano_import.py` mit Testdaten `tests/fixtures/betano_magic_hawks.har.json` |
| 22.10.2026 | Roh-Recorder und `game_clock`: `record_live.py` (Alias `aufzeichnen`) zeichnet NBA-Live-Daten von cdn.nba.com auf (Scoreboard alle 30 s, Roh-Boxscore je laufendem Spiel etwa jede Minute, nach Spielende finaler Boxscore, komplettes Play-by-Play und `result.json`, beim ersten Sehen `context.json` mit Modell-Schnappschuss und Hauptlinien, `events.jsonl` je Spiel und Tag; bei 403/429 Wartezeit 30 → 300 s) nach `~/NBAEdge_live_history/<US-Spieltag>/<game_id>/` (außerhalb des Projekts, `NBAEDGE_LIVE_DIR`); `engine/game_clock.py` (ein Zustand für Phase und Uhr, leere Uhr = Periodenende statt 12:00, noch nicht im alten Tab verwendet); `data/nba_headers.py` (Chrome-Version aus dem installierten Browser); Tests `tests/test_game_clock.py`, `tests/test_record_live.py` |
| 21.10.2026 | Schritt 9a: eigene Linien aus der Pre-Match Eingabe als Marktlinie (`data/market_lines.py`: neuere Linie gewinnt gegen den Cache, Gleichstand eigene Eingabe, laufende Spiele nur Cache), Herkunftszeile und gelber Abweichungshinweis in den Score-Projections-Karten, Projektionen werden bei geänderter Pre-Match-Datei ohne API-Abruf für das betroffene Spiel neu berechnet; Tests `test_market_lines.py` |
| 21.10.2026 | Pre-Match Eingabe Schritt 8: Karte kompakt, jeder Markt ist ein Expander (standardmäßig zu, fester Titel, Zustand bleibt bei Reruns erhalten), „Weitere Linien (n)“ als Zwischenüberschrift statt verschachteltem Expander; Backups liegen jetzt in `~/Desktop/NBAEdge_Backups/ordner` und `/pickle`; Tests und Browsertest angepasst |
| 21.10.2026 | Pre-Match Eingabe Schritt 7c: Kaderliste `data/rosters.json` (nba_api PlayerIndex, ein Abruf, nur per `fetch_rosters.py` oder Knopf „Kader aktualisieren“; erste Datei aus dem Probeabruf), neuer Markt „Spielerpunkte“ (Spielerblöcke mit Meilensteinen oder Einzellinie, Dateiversion 5 mit byte-genauer Sicherung der Version 4, ein Speichern-Knopf für fünf Märkte), Zähler „Weitere Linien (n)“ zählt sichtbare Zeilen; Tests `test_pre_match_players.py`, Klick- und Browsertest erweitert |
| 21.10.2026 | Pre-Match Eingabe Schritt 6: weitere Linien (Spread, Total) als kompakte Einzeiler mit einer Kopfzeile, Buchmacher folgt der Hauptlinie; neuer Markt „Team Totals“ (je Team, Vorschlag rechnerisch aus Total und Spread, Dateiversion 4 mit byte-genauer Sicherung der Version 3), ein Speichern-Knopf für vier Märkte; gemeinsame Over/Under-Komponente; Tests `test_pre_match_team.py`, Klick- und Browsertest erweitert |
| 21.10.2026 | Pre-Match Eingabe Schritt 5: neuer Markt „Total“ (Über/Unter, Hauptlinie + bis zu 3 höhere und 3 niedrigere Linien, Vorschlag aus der Vorab-Linie, Dateiversion 3 mit byte-genauer Sicherung der Version 2), ein Speichern-Knopf für drei Märkte; Knopfstil: Orange nur für „Speichern“ (vorher war jeder Knopf durch die globale Regel in `app.py` orange), Tests `test_pre_match_total.py`, Klick- und Browsertest um Total erweitert |
| 21.10.2026 | Pre-Match Eingabe Schritt 4: Streamlit-Warnung „default value … Session State API“ behoben (Startwerte nur noch im Session State, nie zusätzlich `value=`), neue Anordnung (Marktnamen mittig, Quote Gast \| Buchmacher \| Quote Heim, Linie Gast \| −/+ \| Linie Heim), Eingabebereich pro Karte als `st.fragment` (−/+ und Eingaben laden nur die Karte neu), Tests prüfen jeden AppTest-Lauf auf Warnungen/Exceptions |
| 21.10.2026 | Pre-Match Eingabe Schritt 3: ein Speichern-Knopf pro Karte (alle ausgefüllten Märkte, alles oder nichts, `save_card`), Marktnamen als Überschrift, Spread nur mit ganzen/halben Linien, beide Linienfelder gespiegelt, bis zu 3 weitere Linien automatisch (1,0 Richtung Favorit, −/+ 0,5). `market_suggestion` speichert ungerundeten und auf 0,5 gerundeten Wert (`line_home_rounded`) |
| 21.10.2026 | Pre-Match Eingabe Schritt 2: Quotenfelder links Gast / rechts Heim, Status-Chip oben rechts (offen / gespeichert HH:MM / gesperrt), neuer Markt „Spread“ (Hauptlinie + weitere Linien, Marktvorschlag aus der Vorab-Linie, `market_suggestion` wird mitgespeichert). Datei `pre_match_entries.json` jetzt Version 2 (Version 1 bleibt lesbar und wird beim ersten Schreiben in `data/tracking/history/` gesichert) |
| 21.10.2026 | Neuer Tab „Pre-Match Eingabe“ (Grundgerüst): eigene Quoten pro Spiel vor dem Anpfiff erfassen, erster Markt „Sieger inkl. OT“. Speicherung in `data/tracking/pre_match_entries.json` (atomar, Tageskopie in `data/tracking/history/`, Versionsfeld, Zeitstempel je Eintrag und Änderung). Eingaben nur vor dem Anpfiff |
| 21.10.2026 | Score Projections: Karten über die volle Inhaltsbreite (bis 1400 px) mit größeren Schriften. Die Projektion nutzt nur noch Vorab-Linien (`data/pregame_lines.py`, `data/pregame_lines.json`): bei laufenden Spielen die zuletzt gespeicherte Linie vor dem Anpfiff, sonst „ohne Marktlinie“ (reines Modell) |
| 21.10.2026 | Automatik vorbereitet, nicht aktiviert (`automation/`): `fetch_odds_daily.py` (22:00, ein Abruf nur bei genug Credits und Cache älter als 60 Min.), `update_model.py` protokolliert in `data/automation.log`, launchd-plist und Installationsskripte. App lädt `data/elo_model.pkl` bei Änderung selbst neu; Sidebar zeigt den letzten Automatik-Lauf |
| 20.10.2026 | Odds-API-Credits sparen: zentrale Abrufe in `data/odds_client.py` mit Festplatten-Cache (`data/odds_cache.json`), Abruf nur per Knopf (beim Start nur ohne Cache), Credit-Reserve 50, Protokoll `data/odds_calls.log`, Credits in der Sidebar; Live-Linien nur per Knopf im Live-Tab; BallDontLie-Cache für kommende Spiele 10 Min. (`data/upcoming_cache.json`). Einstellungen in `config/settings.py` (`ODDS_*`) |
| 20.10.2026 | Phase A aus `ELO_ANALYSE.md`: Vorzeichenfehler im Spread-Blend behoben (Konvention positiv = Heim-Favorit, Umdrehen in `data/odds.py`), Spread-Anzeige mit Teamname, `ELO_TO_SPREAD_FACTOR` 25 → 50, Siegwahrscheinlichkeit auf [0,03; 0,97] begrenzt (in `EloEngine.predict`, Pickle unverändert), Training-Fetch nur mit `status == "Final"`, laufende Saison nie aus dem Cache, leere Cache-Dateien zählen nicht. Backup: `Desktop/NBAEdge_backup_2026-10-20`, Pickle: `Desktop/elo_model_2026-10-20.pkl` |
| 26.09.2026 | Abschnitt „Neue Saison starten (Oktober)“ ergänzt: Cache löschen, `SEASONS_TO_LOAD` auf 2027 erweitern, `python train.py` |
| 26.09.2026 | Ordner `nbaedge_2` (aus der Web-Besprechung, Stand Mai mit 5 Tabs) gelöscht, weil `NBAEdge` alles Neuere enthält. **Nicht übernommen** wurden drei kleine Ideen daraus: (1) `engine/ev.py` `model_weight` 0,5 statt 0,3, (2) `models/elo.py` `self.ratings = defaultdict(lambda: 1500.0)` statt `{}`, (3) `data/fetcher.py` Zeitfenster für kommende Spiele „heute bis morgen“ ohne 12-Stunden-Grenze |
| 26.09.2026 | `venv/` angelegt (Pakete aus `requirements.txt`). Test: alle 7 Tabs laden ohne Fehler, Offline-Tests 6/6 bestanden. Live-Daten (Value Bets, History, `LIVE`) wegen Saisonpause nicht testbar |
| 26.09.2026 | README korrigiert: Modell wurde mit scikit-learn 1.4.0 gespeichert, nicht 1.6.1 |
| 26.09.2026 | `nba_api==1.11.4` in `requirements.txt` ergänzt (wurde im Code benutzt, fehlte aber) |
| 26.09.2026 | Ordner `Desktop/NBAEdge` aufgeräumt. Alte Unterordner `NBA Prediction App` und `NBAEdge 6` (Stand 03.06.) entfernt, neuester Stand aus `Ordnung bringen/NBAEdge 6` (14.06.) hierher kopiert. README erstellt |
| 14.06.2026 | Letzte Änderung an `app.py` (Stand des Hauptstands): Live Bet Tracker, Market-History |
| 03.06.2026 | `NBAEdge 6` (älterer Stand) |
| 18.05.2026 | `NBAEdge 5` |
| 16.05.2026 | `NBAEdge 4` |
| 13.05.2026 | Umbau zu `nbaedge` / `NBA Prediction App` |
| 05.05.2026 | `NBA Prediction App Backup`: erste Version mit 5 Tabs und Google-Sheets-Export |
| 23.10.2026 | Streuung (Sigma) korrigiert, `sigmas_version` 2: `SPREAD_SIGMA` 13,2 (vorher 10,5), `TOTAL_SIGMA` 18,6 (18,0), `TEAM_TOTAL_SIGMA` 11,6 (12,5) nach `analysis/sigma_check.py` (10 777 Regular-Season-Spiele 2017–2025, Walk-forward, Messwerte in `analysis/results/sigma_check.json`; das alte 10,5 war an die Logistik-Siegwahrscheinlichkeit angepasst und gegen die Ergebnisse zu klein, Kalibrierungs-Steigung 0,78); die Werte sind eher eine Obergrenze (produktiv wird mit der Marktlinie gemischt), Nachmessen nach ca. 300 Schnappschuss-Spielen. **Siegchance und Spread aus derselben Verteilung:** Der Siegbalken ist jetzt `engine/line_probabilities.win_prob_home` (Normalverteilung um den angezeigten Spread, begrenzt 3–97 %) statt der Elo-Logistik (bleibt als `home_win_prob_elo` erhalten); Spread-Balken bei Linie 0 und Siegbalken stimmen exakt überein, die Karte zeigt „Siegchance und Spread aus derselben Verteilung (Sigma 13,2)“. Schnappschüsse tragen `sigmas_version` (fehlt = 1: 10,5 / 18,0 / 12,5, Siegchance aus der Logistik); begonnene Spiele bleiben unverändert, `analysis/eval_snapshots.py` wertet je Version getrennt aus (`--alle` zusätzlich gemischt). Live-Modell: bei Version 2 ist die Siegchance live dieselbe Verteilung wie der Spread bei Linie 0 (beim Anpfiff exakt gleich); ältere Schnappschüsse rechnen weiter mit der effektiven Marge. Tests angepasst/ergänzt (`test_line_probabilities`, `test_snapshots`, `test_score_cards`, `test_live_model`) |
