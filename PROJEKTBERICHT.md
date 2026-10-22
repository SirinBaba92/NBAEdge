# NBAEdge – Projektbericht (Stand 20.10.2026)

Zweck: Claude im Chat auf den aktuellen Stand bringen. Der Bericht basiert ausschließlich auf dem Lesen des Ordners `~/Desktop/NBAEdge` (keine Trainings, keine API-Calls, keine Änderungen an anderen Dateien). Keine API-Keys enthalten. Die `.env` enthält `BALLDONTLIE_API_KEY` und `ODDS_API_KEY`, aber **keinen** `NEWS_API_KEY`.

## 0. Das Wichtigste vorab

1. **Der Code ist seit dem 14.06.2026 praktisch unverändert.** `app.py` stammt vom 14.06.2026 (2175 Zeilen, 90 856 Bytes). Die Engine-/Data-Dateien sind von Mai bis Anfang Juni. Seit der Pause geändert wurden nur: `README.md` (26.09.), `config/settings.py` (20.10.), `data/elo_model.pkl` (20.10., neu trainiert) und `data/cache/games_2025.json` (20.10., neu geladen). `games_2026.json` ist ein leerer Cache (`[]`).
2. **Es gibt keinen Google-Sheets-Export mehr.** In keiner `.py`-Datei kommt `gspread`/Sheets vor, `requirements.txt` enthält es nicht. Der Export gehörte zur Version vom 05.05.2026 und ist später entfallen.
3. **Einen „Gestern“-Tab gibt es nicht mehr.** Er wurde durch den Tab **History** (1–14 Tage wählbar) ersetzt. Der frühere „Live“-Tab auf BallDontLie-Basis wurde durch „Live Projection“ (NBA.com-CDN) ersetzt.
4. **Das ELO-Modell hat keine Saison-Übernahme-Logik** (kein Mean-Reversion, kein Reset). Ratings sind dadurch stark gespreizt (siehe Abschnitt 3.5 und 8). Das ist das größte inhaltliche Risiko.
5. **Das Projekt ist kein Git-Repo.** Versionierung läuft nur über Ordnerkopien. Backup des Stands vom 14.06.: `Desktop/Ordnung bringen/NBAEdge 6`.

---

## 1. Projektstruktur

Technik: Python 3.11, Streamlit-Dashboard (`streamlit run app.py`), `venv/` im Projektordner.

```
NBAEdge/
├── app.py                    Streamlit-App, 7 Tabs + Sidebar (2175 Zeilen, alles in einer Datei)
├── train.py                  ELO-Modell trainieren (fragt „Retrain? [y/N]“)
├── save_mock_data.py         Speichert Boxscore/Play-by-Play eines echten Spiels als Mock-Daten
├── test_replay.py            Kleines Replay-Beispiel (kein echter Test)
├── requirements.txt          streamlit 1.45.0, pandas 2.2.3, numpy 2.2.5, requests, scikit-learn 1.6.1,
│                             plotly, scipy, python-dotenv, schedule (ungenutzt), nba_api 1.11.4
├── README.md                 Ausführliche Doku + Änderungsprotokoll (Stand 26.09.2026)
├── .env                      API-Keys (geheim)
├── config/
│   ├── settings.py           Alle Modell-/EV-Parameter (Werte in Abschnitt 3.6)
│   └── runtime.py            OFFLINE_AUDIT_MODE (aktuell False)
├── models/
│   └── elo.py                EloEngine: ELO, Offense/Defense, Rest, Form, Logistic Regression, Save/Load
├── engine/
│   ├── projection.py         compute_projection: Score/Spread/Total (Modell + Vegas + Playoff + Bias)
│   ├── ev.py                 EV, Kelly, find_value_bets, Team-Matching
│   ├── bias.py               Self-Correction: Bias-Datei laden/speichern/berechnen
│   ├── live.py               Live-Projektionen (Team Total, Quarter O/U, Quarter Team Total), Edge-Erkennung
│   ├── live_context.py       Baut aus Boxscore/Play-by-Play (LIVE, MOCK oder Replay) den Live-Kontext
│   ├── momentum.py           Runs, Scoring Drought, Lead Changes, Volatilität, Momentum-Signal
│   ├── possessions.py        Ballbesitz-Schätzung, Pace/48, Off-Rating, leere Possessions
│   ├── replay.py             Spielzustand zu einer Spielminute aus Play-by-Play rekonstruieren
│   ├── player_props.py       Punkte-Props-Projektion (Modell „v2“)
│   └── live_bet_tracker.py   Status eigener „Points Over“-Spielerwetten gegen Live-Boxscore
├── data/
│   ├── elo_model.pkl         Trainiertes Modell (Pickle, 20.10.2026)
│   ├── cache/                games_2015.json … games_2026.json (BallDontLie-Spielhistorie je Saison)
│   ├── mock/                 mock_scoreboard/boxscore/playbyplay.json (Playoff-Spiel Pistons @ Cavaliers)
│   ├── market_history/       *.jsonl – aufgezeichnete Live-Marktlinien je Spiel (5 Dateien, Mai/Juni)
│   ├── live_bets.json        Eigene Live-Bet-Tracker-Wetten (4 Einträge, Stand 14.06.)
│   ├── fetcher.py            BallDontLie: Saison-Historie, kommende Spiele
│   ├── odds.py               The Odds API: Moneyline, Totals, Spreads, Team Totals; Sharp-Fair-Odds
│   ├── live_market.py        Live-Marktlinien (aus Odds-API-Totals abgeleitet), Marktbewegungs-Signale, History
│   ├── nba_live.py           NBA.com-CDN: Scoreboard, Boxscore, Play-by-Play, Foul-Trouble
│   ├── player_stats.py       Spieler-Stats via BallDontLie
│   ├── nba_player_stats.py   Spieler-Stats via nba_api (NBA.com)
│   ├── injuries.py           NewsAPI: Verletzungs-/Lineup-News
│   └── mock_loader.py        Lädt die Mock-Dateien
├── ui/
│   └── live_dashboard.py     „LIVE TRADING DASHBOARD“ (aufklappbar im Tab Live Projection)
└── tests/                    audit_helpers.py, run_full_audit.py, test_replay_regression.py, README.md
```

Nicht vorhanden (aber in README/Chat eventuell erwähnt): `data/bias_adjustments.json` (entsteht erst nach „Self-Correction speichern“) und `data/live_bets_log.csv` (entsteht erst beim ersten Speichern eines Live-Bet-Logs).

---

## 2. Datenquellen und Limits

| Quelle | Genutzt in | Endpoints / Märkte | Zweck |
|---|---|---|---|
| **BallDontLie** `api.balldontlie.io/v1` (Key) | `fetcher.py`, `player_stats.py`, `app.py` (History) | `/games` (Saison-Download mit Cursor, 100/Seite; Datumsabfrage `dates[]`; `start_date/end_date`), Spieler-Suche/-Stats | Training, kommende Spiele, History, Spieler-Props |
| **The Odds API** `api.the-odds-api.com/v4` (Key) | `odds.py`, `live_market.py` | `/sports/basketball_nba/odds`, Regionen `us,eu`, dezimale Quoten. Märkte: `h2h`; zweiter Call `totals,spreads` | Value Bets, Vegas-Total/-Spread, Live-Linien |
| **NBA.com CDN** `cdn.nba.com/static/json/liveData/…` (kein Key) | `nba_live.py` | `todaysScoreboard_00.json`, `boxscore_{id}.json`, `playbyplay_{id}.json`; Browser-Header gesetzt | Live-Projektion, Live Bet Tracker |
| **nba_api** (Python-Paket, NBA.com-Stats) | `nba_player_stats.py` | `playerdashboardbygeneralsplits`, `playergamelog`, `static.players` | Spieler-Props (Season/Last 5, FGA, FTA, TS%) |
| **NewsAPI** `newsapi.org/v2/everything` | `injuries.py` | Suche `"<Team>" NBA injury OR out OR …`, letzte 4 Tage, 3–5 Treffer | Tab Lineup News – **ohne `NEWS_API_KEY` leer (Key fehlt aktuell)** |

**Rate Limits / Caching / Verbrauch**

- BallDontLie: `fetcher._get` wartet bei HTTP 429 `10 s × Versuch` (bis 5 Versuche); beim Saison-Download 1 s Pause pro Seite. History: pro Tag 1 Request (3 Versuche, 8 s × n bei 429) plus 0,7 s Pause; Ergebnis `@st.cache_data(ttl=3600)`. Das konkrete Kontingent des Plans ist im Code nicht hinterlegt.
- Saison-Cache: `data/cache/games_<jahr>.json`. Ist die Datei vorhanden, wird **nie** nachgeladen (siehe Falle in Abschnitt 8).
- The Odds API: **2 Requests pro „Refresh Odds“** (`h2h` und `totals,spreads`; der `team_totals`-Parser existiert, der Markt wird aber nicht angefragt – Team-Total-Linien erscheinen daher meist nicht). Zusätzlich holt `live_market._load_market_cache` die Totals/Spreads mit **90 s TTL** pro Python-Prozess – jedes Öffnen des Live-Dashboards kann also weitere Requests verbrauchen. Restkontingent wird nur im **Terminal** ausgegeben (`x-requests-remaining`), nicht im Dashboard. Das Limit des Plans ist nicht im Code dokumentiert.
- Beim ersten Seitenaufruf lädt die App automatisch einmal Odds (wenn `last_refresh` leer ist), also auch bei jedem Neustart der Streamlit-Session → Request-Verbrauch.
- NBA.com CDN: kein Key, kein Caching, jede Interaktion im Tab Live Projection kann neue Requests auslösen. Außerhalb der Saison `403 Forbidden`.

---

## 3. Modell

### 3.1 ELO-Engine (`models/elo.py`)

- **Rating:** ELO je Team, Start 1500, Update pro Spiel mit `k = K × MOV`, `K = 20`, `MOV = ln(|Margin| + 1) × 2.2` (kein Autokorrelations-Dämpfer wie bei 538, kein Favoriten-Korrektiv). Effektives k liegt bei ca. 50–130.
- **Heimvorteil:** +100 ELO auf das Heimteam (fix, `HOME_COURT_ADVANTAGE`; „calibrated from data“ im Docstring stimmt nicht – fester Wert).
- **Rest Days** (`_rest_factor`): Back-to-Back (1 Tag) = −1,5 ELO (`−0,015 × 100`), 2 Tage = 0, ≥3 Tage = +0,45 ELO (`0,015 × 30`). Wirkung auf den ELO-Wert minimal; zusätzlich geht `h_rest − a_rest` als eigenes Feature in die Regression.
- **Form** (`_form_score`): gewichtete Siegquote der letzten 10 Spiele (Gewichte 1…10, neuere höher), Basis 0,5; geht mit `(form − 0,5) × 40` (max. ±20 ELO) in den Spiel-ELO ein und als Differenz in die Regression.
- **Offense/Defense:** exponentiell gleitender Durchschnitt (α = 0,1) der erzielten/kassierten Punkte je Team (Heim/Auswärts nicht getrennt). Start bei 0.
- **Win-Wahrscheinlichkeit:** `CalibratedClassifierCV(LogisticRegression, cv=5, isotonic)` auf drei standardisierten Features: `[ELO-Differenz, Form-Differenz, Rest-Differenz]`. Fallback ohne Regression: klassische ELO-Formel.
- **Training:** alle Spiele aus `SEASONS_TO_LOAD` chronologisch durchlaufen, Features vor dem Update je Spiel gesammelt (kein Leakage), danach Regression gefittet und als Pickle gespeichert. Aktuell 14 168 Spiele, 30 Teams.

### 3.2 Projektionen (`engine/projection.py::compute_projection`)

1. `model_spread = (home_elo − away_elo) / 25` (home_elo enthält Heimvorteil, Rest, Form).
2. `model_total = expected_total` aus Off/Def-Ratings: `(Off_H + Def_A)/2 + (Off_A + Def_H)/2` (Fallback 225, wenn ≤ 0).
3. **Model + Vegas blend (Total)**, Marktgewicht nach Abweichung `|model_total − market_total|`:

   | Abweichung | Marktgewicht |
   |---|---|
   | < 7 | 0,32 |
   | ≥ 7 | 0,40 |
   | ≥ 10 | 0,48 (+ `lineup_warning`) |
   | ≥ 14 | 0,55 |

   `exp_total = model_total × (1 − w) + market_total × w`. Ohne Markt-Total: reines Modell.
4. **Spread-Blend:** wenn Markt-Spread vorhanden, `exp_spread = 0,75 × Modell + 0,25 × Markt`.
5. **Playoff-Modifier:** automatisch per Datum (15.04. – 25.06. eines Jahres, `is_playoff_date`): Total −4,0, Spread × 0,96.
6. **Team-Bias-Adjustment** (Self-Correction, Datei `data/bias_adjustments.json`): je Team ein Punkt-Offset, der direkt zum Team-Score addiert wird (nicht zum Total).
7. **Scores:** `home = (exp_total + exp_spread)/2 + home_bias`, `away = (exp_total − exp_spread)/2 + away_bias`, jeweils gerundet; `exp_total` im Ergebnis = Summe der gerundeten Scores.

**Bias-Berechnung** (`engine/bias.py`, ausgelöst im Tab History): pro Spiel wird das Team mit dem größeren Score-Fehler als „worst team“ gewertet (OVERVALUED, wenn Projektion > Ergebnis). Je Team: Spiele, Summe Fehler, Anzahl over/under. Adjustment = `Richtung × min(6, round(Ø-Fehler × 0,35, 1))`; Richtung ist Mehrheit over/under (Gleichstand → 0). Nur ab `min_games = 2`. Das Adjustment wird **nicht** vorzeichenrichtig am Fehler gemessen, sondern nur nach Häufigkeit gerichtet (siehe Schwachstellen).

### 3.3 Value Bets (`engine/ev.py`)

- Sharp-Referenz: Pinnacle, sonst Betfair (Marge entfernt: proportional `p / (1 + vig)`).
- `blended_prob = 0,3 × Modell + 0,7 × Sharp` (ohne Sharp-Quote nur Modell – dann ist der „Edge“ rein modellbasiert).
- `EV = p × (Quote − 1) − (1 − p)`; angezeigt ab `MIN_EV_THRESHOLD` 3 %.
- Kelly `(p·Quote − 1)/(Quote − 1)`, gedeckelt bei 3 %, Mindest-Kelly 1 %.
- Es werden nur die **SOFT_BOOKS** geprüft (DraftKings, FanDuel, BetMGM, Caesars, Bovada). Pinnacle/Betfair sind Referenz und „BET_TARGETS“; sie tauchen in der Value-Bets-Liste deshalb de facto nie als Buchmacher auf (der Filter „Bet Targets only“ liefert dadurch leer).

### 3.4 Live-Engine (`engine/live.py`)

Drei Rechner, alle mit gleichem Aufbau: Pregame-Rate und Live-Rate werden gemischt (Live-Gewicht steigt mit der Spielzeit: Team Total 0,35/0,50/0,62; Quarter 0,35/0,50/0,65/0,78), dann Multiplikatoren:

- Pace-Modus (slow 0,94 … fast 1,07, chaotic 1,13), Game-State (close/blowout je nach Viertel), Team-Fouls/Bonus (+1,2 % je Foul, +7 % im Bonus), Runs und leere Possessions (0,86–1,16), Foul Trouble (+2,5 %).
- Drei „Signalfaktoren“: PBP-Signal (`FREE_THROW_HEAVY` 1,055, `SCORING_BURST` 1,045, `OFFENSE_STUCK` 0,94), Possession-Faktor (Pace/Off-Rating/leere Possessions, 0,88–1,12), Momentum-Faktor (0,90–1,10, team-spezifisch 0,88–1,12).
- **Master Live Factor** = 0,45 × PBP + 0,35 × Possession + 0,20 × Momentum.
- **Stability** (Start 100, −15/−10/−10 bei Faktor-Differenzen > 0,08, min. 40) und **Confidence** (Start 50, +20 wenn alle Faktoren > 1,02 bzw. < 0,98, +10 bei Stability ≥ 85, −10 bei ≤ 60).
- **Edge-Signale** (`edge_value = Projektion − Linie`): `UNSTABLE` (Stability ≤ 55), `TRAP_OVER` (Master > 1,03 und Possession < 0,96), `STRONG_OVER/UNDER_EDGE` (|Edge| ≥ 8, Confidence ≥ 65, Stability ≥ 75), `OVER/UNDER_EDGE` (|Edge| ≥ 4, Confidence ≥ 55), sonst `NO_EDGE`.
- `over_probability` ist eine **feste Treppe** (88/78/66/55/44/32/20 %), keine echte Wahrscheinlichkeit. `lean_from_margin`: ±3 / ±7 Schwellen.

### 3.5 Übernahme der Ratings zwischen Saisons

**Es gibt keine.** `build_model` verarbeitet alle Saisons als eine durchgehende Spielfolge; `ratings`, `off_ratings`, `def_ratings`, `form`, `last_game` laufen ohne Reset oder Regression zum Mittelwert über Saisongrenzen. Folgen, am aktuellen Modell geprüft (Stand Training vom 20.10.2026):

- ELO-Spanne: New York Knicks ≈ 2148, San Antonio ≈ 2010, OKC ≈ 1897 … Brooklyn ≈ 1105, Memphis ≈ 1007, Washington ≈ 960. Die Differenz Knicks–Wizards von ~1190 ELO ergäbe über `/25` einen Modell-Spread von ~47 Punkten.
- Ursache: hoher effektiver K-Wert (MOV-Multiplikator ohne Dämpfung) plus keine Saison-Rückführung. Das passt zur Beobachtung in der README („100 % Heimsieg für OKC gegen Utah“) – die Annahme „liegt an der sklearn-Version“ ist damit unwahrscheinlich; das Modell wurde inzwischen mit sklearn 1.6.1 neu trainiert, die Spreizung bleibt strukturell.
- Form und letztes Spieldatum stammen noch aus den Playoffs (letztes Spiel 13.06.2026). Zu Saisonbeginn zeigt „Rest Days“ deshalb für alle Teams ≥ 3 Tage (kleiner Bonus für alle).
- Neue Teams/Namen: `predict` greift mit `self.ratings[home]` direkt zu → `KeyError` bei unbekanntem Team (kein `defaultdict`). Off/Def-Ratings starten bei 0 (EMA-Anlaufverzerrung nur zu Beginn der ersten Saison relevant).

### 3.6 Konfiguration (`config/settings.py`, `config/runtime.py`) – aktuelle Werte

| Parameter | Wert |
|---|---|
| `OFFLINE_AUDIT_MODE` | `False` |
| `SEASONS_TO_LOAD` | `range(2015, 2027)` → 2015–2026 (12 Saisons; Kommentar im Code sagt noch „11 seasons“) |
| `ELO_K_FACTOR` | 20 |
| `ELO_START` | 1500 |
| `HOME_COURT_ADVANTAGE` | 100 |
| `REST_DAYS_WEIGHT` | 0,015 |
| `FORM_WINDOW` | 10 |
| `MIN_EV_THRESHOLD` | 0,03 |
| `MIN_KELLY` | 0,01 |
| `MAX_KELLY` | 0,03 |
| `ODDS_MARKETS` | `["h2h"]` (wird von `odds.py` nicht benutzt, dort fest verdrahtet) |
| `ODDS_REGIONS` | `["us", "eu"]` |
| `ODDS_SPORT` | `basketball_nba` |
| `SHARP_BOOKS` | pinnacle, betfair |
| `SOFT_BOOKS` | draftkings, fanduel, betmgm, williamhill_us, bovada |
| `BET_TARGETS` | pinnacle, betfair |
| `ELO_TO_SPREAD_FACTOR` | 25 |

Hart im Code (nicht in `settings.py`): Blend-Gewichte und Schwellen in `projection.py`, `model_weight=0,3` in `ev.py`, Playoff-Zeitraum und −4/×0,96, Bias-Parameter (Faktor 0,35, Max ±6, min. 2 Spiele), alle Live-Faktoren, Player-Prop-Gewichte (55 % Season / 45 % Last 5).

---

## 4. Dashboard (`app.py`, 7 Tabs)

**Sidebar:** Modellstatus („✓ ELO Model loaded“), Button **🔄 Refresh Odds**, Filter (Min EV % 1–15, Min/Max Odds 1,5/3,5, Bookmaker-Mehrfachauswahl, „Bet Targets only“), Modell-Info (Saisons, Anzahl Self-Correction-Teams).

| Tab | Funktion | Datenquelle |
|---|---|---|
| **🎯 Value Bets** | Value Bets gruppiert je Spiel: Quote, Blended Prob, EV-Badge, Kelly; Metriken (Anzahl, Ø-/Best-EV, Bet Targets) | `refresh_data` → Odds API (`h2h`), BallDontLie (kommende Spiele), ELO-Modell, `find_value_bets` |
| **📊 Score Projections** | Projizierter Endstand, Win-%, Modell vs. Markt für Spread/Total, Team-Total-Linie falls vorhanden, aufklappbare „MODEL DETAILS“ (Raw-Total, Gewicht, Playoff, Bias) | wie oben + Odds API (`totals,spreads`) |
| **🔴 Live Projection** | Datenquelle `LIVE` (NBA.com) oder `MOCK`; Replay-Modus (nur MOCK, Spielminute 0–48); aufklappbares Live Trading Dashboard; drei Rechner (Team Total Over, Quarter Over/Under, Quarter Team Total) mit automatischer Vorbefüllung aus dem Live-Kontext; Foul-Trouble- und PBP-Signal-Box; **Player Props Pre-Game** (Suche per NBA.com bzw. BallDontLie, alle Felder manuell überschreibbar); **Live Bet Log** (CSV) | NBA.com CDN, `data/mock/`, Odds API (Live-Linien), nba_api, BallDontLie |
| **🎯 Live Bet Tracker** | Eigene „Points Over“-Wetten (Name + Linie) hinzufügen; Tabelle mit aktuellen Punkten, Rest, Status `IN_PROGRESS`/`WON`/`LOST` | `data/live_bets.json` + Live-Boxscore des im Live-Tab gewählten Spiels |
| **📰 Lineup News** | Teamauswahl, Button „News laden“, bis zu 5 Artikel | NewsAPI (ohne Key leer) |
| **📅 History** | 1–14 Tage zurück: Projektion vs. Ergebnis je Spiel, Winner-Hit, Total-Fehler, Qualitätsstufe, Team Bias Tracking, Hit Rate, Buttons „Self-Correction speichern/löschen“, CSV-Download | BallDontLie (`dates[]`), ELO-Modell; zählt nur abgeschlossene Spiele |
| **📈 ELO Rankings** | Balkendiagramm der Team-ELO-Werte (nur Teams mit Form-Historie) mit Form-L10 | `engine.ratings` aus dem Pickle |

Footer: Hinweis „For research purposes only“. UI: dunkles Custom-CSS (Space Mono / DM Sans).

### Warnlogik und Schwellenwerte

- **⚠️ LINEUP RISK** (Score Projections): wenn `|model_total − market_total| ≥ 10` (Rohmodell vs. Vegas, vor dem Blend). Bedeutung: vermutlich fehlt ein Spieler im Modell.
- **⚠️ MARKET DISAGREEMENT** (Score Projections): wenn `|finaler exp_total − market_total| ≥ 8`.
- **Foul Trouble** (`nba_live.detect_foul_trouble`): 5+ Fouls = CRITICAL, 4 Fouls + Starter = HIGH, 4 Fouls = MEDIUM.
- **PBP-Signal** (letzte 20 Aktionen): `FREE_THROW_HEAVY` (≥ 4 FT oder ≥ 4 Fouls), `OFFENSE_STUCK` (≥ 3 Turnover oder ≥ 5 Fehlwürfe), `SCORING_BURST` (≥ 10 Punkte), sonst `NORMAL`.
- **Momentum-Signal** (`momentum.py`): `HOME_SURGE`/`AWAY_SURGE` (Run ≥ 10), `OFFENSE_COLLAPSE` (Drought ≥ 3,5 min), `HIGH_VOLATILITY` (Volatilität ≥ 8), sonst `STABLE`.
- **Live-Faktor-Labels:** „🔥 Strong live signal“ bei Confidence ≥ 80, „⚠️ Unstable projection“ bei ≤ 35. Edge-Labels für STRONG_OVER/UNDER, TRAP_OVER, UNSTABLE.
- **Live Trading Dashboard** (`ui/live_dashboard.py`): Marktsignal aus Delta = Projektion − Quarter-Linie: `HIGH_CONVICTION_EDGE` (Confidence ≥ 80, Stability ≥ 85, |Δ| ≥ 6), `MARKET_DISAGREEMENT` (|Δ| ≥ 8, Confidence ≥ 70), `POSSIBLE_FAKE_LINE` (NO_EDGE und |Δ| ≥ 10). Marktbewegung (`live_market.build_market_movement_signal`): `MARKET_LAG`, `MARKET_OVERREACTION`, `LINE_FREEZE`, `REVERSE_STEAM`, `STEAM_MOVE` (Schwellen 1–6 Punkte, Confidence/Stability 70–75).
- **History-Qualität:** Total-Fehler ≤ 6 = 🔥 ELITE, ≤ 12 = ✓ SOLID, sonst ⚠️ OFF.
- **Player Props:** Lean OVER/UNDER ab ±2,5 Punkten Differenz, sonst NO_EDGE; Confidence aus Edge, FGA-/FTA-Volumen und TS%-Volatilität (0–100).

---

## 5. Tracking und Export

| Was | Wo | Format | Anmerkung |
|---|---|---|---|
| Live-Bet-Tracker-Wetten | `data/live_bets.json` | JSON-Liste `{player, bet_type: "points_over", line}` | relativer Pfad → App immer aus dem Projektordner starten; aktuell 4 Wetten (Brunson 27,5; Wembanyama 28,5; Harper 15,5; Anunoby 17,5) – Stand Juni, vermutlich veraltet; kein Löschen in der UI |
| Live Bet Log | `data/live_bets_log.csv` | CSV: timestamp, game, market, line, odds, model_prob, result, note | wird beim ersten Speichern angelegt (existiert noch nicht); Ergebnis nur manuell, kein Nachtragen/Bearbeiten in der UI |
| Self-Correction | `data/bias_adjustments.json` | JSON je Team: adjustment, games, avg_error, over/under | existiert aktuell nicht (also keine aktive Korrektur) |
| History-Export | Browser-Download `nbaedge_history.csv` | CSV: date, away, home, actual_total, proj_total, total_error, winner_hit, worst_team, worst_error, bias | nur manuell, nicht dauerhaft gespeichert |
| Marktverlauf | `data/market_history/<game_id>.jsonl` | je Zeile: timestamp (UTC), market_line, projection, delta, movement_signal | wird beim Rendern des Live Trading Dashboards angehängt; 5 Dateien aus den Playoffs |
| Modell | `data/elo_model.pkl` | Pickle | |
| Spielhistorie | `data/cache/games_*.json` | JSON | |

**Google Sheets:** nicht mehr vorhanden (siehe Abschnitt 0). Es gibt weder Wett-Historie mit Ergebnissen noch Bankroll-Tracking für die Value Bets – Value Bets werden nirgends gespeichert.

---

## 6. Workflow

```bash
cd ~/Desktop/NBAEdge
source venv/bin/activate

python train.py                 # Training; bei vorhandenem Modell Rückfrage, mit "y" bestätigen
streamlit run app.py            # Dashboard starten
python3 tests/test_replay_regression.py   # Offline-Regressionstest (6 Replay-Minuten)
python3 tests/run_full_audit.py           # Tabellarischer Audit
```

**Tägliche Nutzung:** App starten → beim ersten Laden werden Odds/Projektionen automatisch einmal geholt → bei Bedarf „🔄 Refresh Odds“ → Tabs durchgehen. Nach Spielende Tab History öffnen und optional „Self-Correction speichern“, danach „Refresh Odds“ (Bias wird nur in `st.session_state` und Datei übernommen).

**Neue Saison (laut README, am 20.10.2026 anscheinend so durchgeführt):** `games_<letzte Saison>.json` löschen → `SEASONS_TO_LOAD` um 1 erhöhen → `python train.py`. Der Zustand der Dateien passt dazu (`games_2025.json` neu geladen mit Spielen bis 13.06.2026, `settings.py` auf 2015–2026, Pickle neu).

**Testmodus:** `OFFLINE_AUDIT_MODE = True` in `config/runtime.py` – nur Mock-Daten, keine externen Requests; danach wieder auf `False`.

**Datum / Zeitzone**

- Es gibt **keine explizite Zeitzonen-Behandlung** (kein `zoneinfo`/`pytz` im Code). Es gilt gemischt:
  - `fetch_upcoming_games`: UTC-Zeitfenster (gestern bis heute, Spiele zwischen −3 h und +12 h ab jetzt). BallDontLie liefert für das Feld `date` das US-Spieldatum.
  - `refresh_data`: ruft `engine.predict(home, away, date.today())` auf – **lokales Systemdatum** (Deutschland). Rest-Tage werden damit ab Mitternacht deutscher Zeit relativ zum deutschen Datum berechnet, nicht zum US-Spieldatum.
  - Playoff-Erkennung nutzt das `date`-Feld des Spiels (US-Datum), im Mock-Modus `date.today()`.
  - History: `date.today() − n` (lokal, deutsch) als Abfragedatum an BallDontLie (US-Datum). Nachts/morgens deutscher Zeit kann „gestern“ dadurch um einen Tag verrutschen; Spiele aus der US-Nacht erscheinen je nach Uhrzeit unter einem anderen Tag.
  - Anzeige der Anpfiffzeit in Value Bets: `commence_time` ist UTC und wird **ohne Umrechnung** per `strftime` angezeigt (also UTC, nicht deutsche Zeit).
  - Market-History-Zeitstempel: UTC.
  - Spielersaison für Props: `date.today().year` (ab Oktober neue Saison).
- Praktischer Effekt: In den US-Spielnächten (deutsche Nacht) stimmen „heute“ in Deutschland und „heute“ in den USA nicht überein. Das ist ein bekanntes Risiko, aber (noch) nicht gelöst.

---

## 7. Änderungen seit der Grundversion

Grundversion (05.05.2026): 5 Tabs (Value Bets, Score Projections, Live auf BallDontLie-Basis, Gestern, ELO Rankings), Google-Sheets-Export, `app.py` ca. 560 Zeilen. Heute: 7 Tabs, 2175 Zeilen.

**Neu dazugekommen**

- `engine/projection.py` ausgelagert (13.05.): Model + Vegas Blend mit gestaffelten Gewichten, Spread-Blend, `lineup_warning`, **Playoff-Modifier**, Bias-Einbau.
- **Self-Correction / Team-Bias** (`engine/bias.py`) inkl. Speichern/Löschen im Tab History.
- Tab **History** (ersetzt „Gestern“): wählbarer Zeitraum 1–14 Tage, Qualitätsstufen, Team Bias Tracking, CSV-Download.
- **Live Projection** komplett neu auf NBA.com-CDN: drei Rechner, Live-Kontext aus Boxscore/Play-by-Play, Foul Trouble, Team-Fouls/Bonus, Possession-Engine, Momentum-Engine, Master Live Factor mit Stability/Confidence, Edge-Erkennung (19.05.).
- **Replay-Modus** + Mock-Daten (`save_mock_data.py`, `engine/replay.py`) und **Offline-Audit-Modus** + Tests (`tests/`).
- **Live Trading Dashboard** (`ui/live_dashboard.py`) mit Marktsignalen, Marktbewegung und persistenter Market-History (`data/market_history/`).
- **Player Props Pre-Game** (`engine/player_props.py`, Modell v2: Minuten-, Usage-, FTA-, TS-, Blowout-Faktor), Datenquellen BallDontLie und nba_api (Juni).
- **Live Bet Log** (CSV) und **Live Bet Tracker** (Tab, `live_bets.json`) (14.06.).
- Tab **Lineup News** (NewsAPI, optional).
- Team-Totals aus der Odds-API-Antwort im Parser (Anzeige „TT Line“ wenn vorhanden).
- Value Bets: Sharp-Blend (30 % Modell / 70 % Sharp), Pinnacle/Betfair als Referenz und „Bet Targets“.
- Ordner-Aufräumen und README (26.09.), `nba_api` in `requirements.txt` (26.09.), `venv` angelegt.
- 20.10.2026: `SEASONS_TO_LOAD` auf 2015–2026, Cache 2025 neu geladen, Modell neu trainiert.

**Weggefallen:** Google-Sheets-Export, „Gestern“-Tab mit festem 2-Tage-Hit-Rate, BallDontLie-Live-Tab, fest eingetragene „57,8 %“-Backtest-Quote in der Sidebar.

**Hinweis zur Verlässlichkeit:** Das README-Änderungsprotokoll ist die einzige schriftliche Historie; die Stände davor wurden dort „aus den Änderungsdaten rekonstruiert“. Ob zwischen 14.06. und 20.10. Arbeit an Dateien lief, die nicht mehr im Ordner liegt (z. B. in anderen Ordnern/Backups), lässt sich aus dem Projekt nicht ablesen.

---

## 8. Offene Punkte, Bugs und Schwachstellen

**Modell / Daten (hoch)**

1. **Keine Saison-Übernahme** (Abschnitt 3.5): extreme ELO-Spreizung, unrealistische Spreads/Win-Wahrscheinlichkeiten, Form/Rest-Daten aus den Playoffs. Vorschlag für den Chat: Regression zum Mittelwert beim Saisonwechsel (z. B. 25–33 % zurück Richtung 1500), MOV-Dämpfung (538-Formel) und Neukalibrierung von `ELO_TO_SPREAD_FACTOR`.
2. **Leere Cache-Datei `games_2026.json` (`[]`)**: `fetch_all_games` gibt gecachte Dateien immer zurück, auch leere. Sobald die Saison 2026/27 läuft, wird sie beim nächsten Training **nicht** nachgeladen, solange die Datei existiert. Vor dem Training in der laufenden Saison löschen (gilt generell für die jeweils laufende Saison). Außerdem filtert der Download Spiele mit Score 0 heraus.
3. Das Modell berücksichtigt **keine Verletzungen/Aufstellungen**, keine Trades/Offseason-Änderungen, keine Spielerdaten. Die Lineup-Warnung ist nur ein Indikator. Nach der Offseason sind die Ratings vom Juni besonders unzuverlässig.
4. `expected_total` aus EMA-Punkten (α = 0,1, Start 0) ist grob; keine Pace- und keine Heim/Auswärts-Trennung, Saisonübergang ebenfalls ohne Reset.
5. Modell-Wahrscheinlichkeit aus isotonischer Kalibrierung auf überhitzten ELO-Differenzen kann 0 %/100 % liefern; EV-Berechnung nutzt dann das Modell mit 30 % Gewicht ungefiltert.
6. Pickle-Modell: keine Versionsbindung; Warnungen bei anderer sklearn-Version möglich (Modell wurde am 20.10. mit installiertem sklearn neu erzeugt, aktuelle `venv`-Version nicht geprüft).

**Value Bets / Projektion**

7. Pinnacle/Betfair werden nie als Wettziel ausgegeben, weil nur `SOFT_BOOKS` geprüft werden – der Filter „Bet Targets only“ bleibt praktisch leer. Das widerspricht der README-Beschreibung („gewettet werden soll bei den Bet Targets, gerechnet wird gegen die Soft-Books“) nur dann nicht, wenn das so gewollt ist – bitte klären.
8. `_match_game` matcht nur über das letzte Namenswort (z. B. „Trail Blazers“ → „blazers“) und liefert bei vertauschter Heim/Auswärts-Reihenfolge das Spiel ohne Seitentausch zurück (Kommentar „handled by caller“, wird aber nicht behandelt). Gleiche Logik in `match_lines`/`_normalize`.
9. Bias-Adjustment: Richtung nur nach Anzahl over/under, Betrag nach Ø-Absolutfehler; wirkt additiv auf Teamscores und wird aus einer Stichprobe von meist 2–4 Spielen abgeleitet (hohes Rauschen). Das Verfahren bewertet immer nur das „schlechteste“ Team je Spiel. Auch der Playoff-Modifier ist ein fester Wert ohne Validierung.
10. History-Auswertung bewertet nur die Siegerquote und den Total-Fehler der **Modell-Projektion ohne Markt** (`compute_projection` ohne Market-Total) – nicht die Value Bets selbst. Es gibt kein Tracking von Profit/ROI.
11. `ODDS_MARKETS` in `settings.py` wird nicht benutzt. `team_totals` werden zwar geparst, aber nie angefragt (Markt fehlt im Request). `schedule` in `requirements.txt` ist ungenutzt.
12. `fetch_upcoming_games` benutzt ein hartes 12-Stunden-Fenster ab UTC-Jetzt; Spiele später am Tag fehlen (schon in der README als verworfene Idee erwähnt).

**Zeit / Datum**

13. Keine Zeitzonenlogik (Abschnitt 6): lokales deutsches `date.today()` für Rest-Tage und History, UTC-Anzeige der Anpfiffzeit.

**Live-Bereich**

14. **Possession- und Momentum-Faktoren wirken nur im Replay-Modus**: In `app.py` werden `possession_summary` und `momentum_summary` nur bei `replay_mode` an die Rechner übergeben (sonst `{}`) – bei echten LIVE-Spielen laufen die Rechner dadurch ohne diese Signale. Ob das Absicht ist, ist nicht dokumentiert. Das Live Trading Dashboard nutzt sie dagegen immer.
15. Das Dashboard rechnet mit festen Annahmen: `pregame_game_total = 225`, `pace_mode = "normal"`, `game_state = "close"`; die Quarter-Linie ist nur `Spieltotal / 4` (kein echter Quarter-Markt). Bei fehlenden Marktdaten fällt es auf MOCK-Linien (225 / 55,5 / 112,5) zurück – das sieht im UI wie eine echte Linie aus; nur `market_source` unterscheidet es.
16. Live-Wettwahrscheinlichkeit `over_probability` ist eine feste Treppe, keine kalibrierte Wahrscheinlichkeit; Schwellen (Faktoren, Confidence, Edge) sind nirgends backgetestet.
17. Die Marktverlaufs-Historie (`market_history/*.jsonl`) wächst unbegrenzt, und `append_market_history_snapshot` wird bei **jedem** Streamlit-Rerun geschrieben (nicht nur bei neuen Daten). Außerdem schlucken viele Funktionen Fehler stumm (`except Exception: return`).
18. NBA.com-CDN kann `403` liefern (Saisonpause/Blockierung); keine Wiederholung/Backoff. `save_mock_data.py` nutzt feste Playoff-Game-IDs von 2026.
19. Live Bet Tracker: nur `points_over`; Spielersuche per exaktem Namensvergleich (Akzente/Schreibweise, z. B. „OG Anunoby“ vs. „O.G. Anunoby“ → Punkte 0); nur das im Live-Tab gewählte Spiel liefert den Boxscore (Spieler aus anderen Spielen zeigen 0); `LOST` erst, wenn `game_finished` gesetzt ist – das Flag wird nirgends gesetzt, daher wird nie `LOST` angezeigt. Status `WON` gilt bei `points > line`. Liegt die Datei `live_bets.json` nicht im Arbeitsverzeichnis, bricht der Tab mit einer Exception ab.
20. Die Bet-Add-Funktion ist ohne Eingabe-Validierung (leerer Name möglich), Löschen nur durch manuelle Dateibearbeitung.

**Code-Qualität / Tests**

21. `app.py` ist ein 2175-Zeilen-Monolith mit viel UI-Logik, geschachtelten Hilfsfunktionen und Duplikaten; keine Unit-Tests für `projection`, `ev`, `bias`, `elo`, `odds`, Player Props, Live Bet Tracker oder Datenfetcher. Die vorhandenen Tests prüfen nur Replay-/Live-Plausibilität anhand eines einzelnen Mock-Spiels (6 Zeitpunkte) und prüfen auf NaN/ungültige Signale, nicht auf Richtigkeit. `test_replay.py` im Wurzelordner ist nur ein Beispiel-Skript.
22. Die Tests laufen nicht über pytest (eigene `main()`); `test_replay_regression.py` importiert `audit_helpers` ohne Paketpfad und läuft nur, wenn das Skript direkt aus `tests/` bzw. mit dem README-Befehl gestartet wird (nicht verifiziert – in dieser Analyse nicht ausgeführt).
23. Hardcodierte Magic Numbers überall (siehe Abschnitt 3.6), Kommentar in `settings.py` („11 seasons“) und Docstring in `elo.py` („HCA calibrated from data“) sind inzwischen falsch.
24. Streamlit führt bei **jeder** Interaktion das ganze Skript aus. In Tab 3 (Live) werden bei jeder Änderung Boxscore/Play-by-Play und Live-Dashboards neu geladen; die Odds-API-Anfragen im Dashboard sind nur durch den 90-s-Cache gebremst.
25. README-Hinweis: Bei Mock-Betrieb (`OFFLINE_AUDIT_MODE = True`) muss danach wieder auf `False` gestellt werden – sonst zeigt die App nur Testdaten.
26. `.env` wird im Projektordner im Klartext gespeichert; kein Git, daher kein `.gitignore` nötig, aber beim Weitergeben/Kopieren des Ordners Vorsicht.

**Sinnvolle nächste Schritte (Vorschlag, nicht umgesetzt)**

1. Saison-Übernahme und K-Faktor/MOV-Dämpfung im ELO einbauen, Modell neu kalibrieren und Spreads/Probabilities gegen History prüfen.
2. Cache-Logik anpassen (leere/laufende Saison nicht dauerhaft cachen).
3. Zeitzonenlogik zentralisieren (`America/New_York` für Spieltag, `Europe/Berlin` für Anzeige).
4. Value Bets persistent speichern (Datei/Sheets) und Ergebnis/ROI tracken.
5. Fehlt: Verletzungs-/Lineup-Datenquelle statt NewsAPI-Stichwortsuche.
6. Unit-Tests für `projection`, `ev`, `bias`, `elo`.
