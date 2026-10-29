SEASONS_TO_LOAD = list(range(2015, 2027))  # 11 seasons for ELO training

ELO_K_FACTOR = 20
ELO_START = 1500
HOME_COURT_ADVANTAGE = 100
REST_DAYS_WEIGHT = 0.015
FORM_WINDOW = 10

# Tab "Value Bets" samt Moneyline-Abfrage (Odds API, Markt h2h). False = Tab ausgeblendet und keine h2h-Abfrage;
# der Code (engine/ev.py, Parser, Tab) bleibt erhalten. Totals/Spreads sind davon unabhaengig.
SHOW_VALUE_BETS = False

MIN_EV_THRESHOLD = 0.03  # 3% minimum EV to show
MIN_KELLY = 0.01  # 1% minimum Kelly fraction
MAX_KELLY = 0.03  # cap at 3% of bankroll

ODDS_MARKETS = ["h2h"]
ODDS_REGIONS = ["us", "eu"]
ODDS_SPORT = "basketball_nba"

SHARP_BOOKS = ["pinnacle", "betfair"]
SOFT_BOOKS = ["draftkings", "fanduel", "betmgm", "williamhill_us", "bovada"]
BET_TARGETS = ["pinnacle", "betfair"]

# Score projection: ELO diff / factor = expected spread
# Analyse 2026-10-20 (ELO_ANALYSE.md): Regression Margin ~ ELO-Diff ergibt ca. 50.8 ELO pro Punkt
# (je Saison 43-64). Vorher 25 = Spreads doppelt so gross wie die Realitaet.
ELO_TO_SPREAD_FACTOR = 50

# Win probabilities are clipped when read out of the model (the pickle itself is unchanged)
MIN_WIN_PROB = 0.03
MAX_WIN_PROB = 0.97

# Score-Projections-Karten: Abweichung Modell vs. Markt wird ab diesen Werten gelb (sonst neutral grau).
# Spread in Punkten, Total in Punkten (8.0 = bestehende Market-Disagreement-Schwelle). Nie gruen: siehe DESIGN_REGELN.md.
SPREAD_DEVIATION_YELLOW = 5.0
TOTAL_DEVIATION_YELLOW = 8.0

# Odds-API-Credits sparen (data/odds_client.py): Abrufe nur auf Knopfdruck, sonst Festplatten-Cache.
# Totals/Spreads kosten Maerkte x Regionen = 2 x 2 = 4 Credits, die Moneyline (h2h) 1 x 2 = 2 Credits.
ODDS_TOTALS_TTL_SECONDS = 20 * 60        # Quoten gelten 20 Min. als aktuell; danach nur Hinweis, kein automatischer Abruf
ODDS_MIN_CREDITS_RESERVE = 50            # darunter keine automatischen Abrufe, nur noch manuell (mit Warnung)
ODDS_CREDITS_WARN_YELLOW = 100           # Sidebar: gelb unter 100, rot unter 50
ODDS_FAILURE_BACKOFF_SECONDS = 300       # nach einem Fehler 5 Min. kein automatischer Wiederholungsversuch
ODDS_LIVE_AUTO_TTL_SECONDS = 300         # nur bei eingeschaltetem Auto-Refresh der Live-Linien: Cache-Alter, ab dem neu abgefragt wird
UPCOMING_GAMES_TTL_SECONDS = 10 * 60     # BallDontLie: kommende Spiele 10 Min. zwischenspeichern (Rate-Limit)

# --- Live-Modell (engine/live_model.py). Kalibriert mit analysis/live_calibration.py (Ergebnisse: analysis/results/live_calibration.json, Stand 22.10.2026).
# Viertelpunkte: 10 777 Regular-Season-Spiele 2017-2025, Vorab-Prognose wie die Engine. Tempo: 11 aufgezeichnete Spiele (~/NBAEdge_live_history), noch wenig Daten.
LIVE_OT_MINUTES = 5
LIVE_OT_SCORING_FACTOR = 0.93            # Punkte der 1. Verlaengerung (beide Teams) 21,7 gegen 23,4 nach Total * 5/48
# Erwarteter Anteil der Punkte bzw. der Marge bis Ende Viertel 0 (Anpfiff), 1, 2, 3, 4; innerhalb eines Viertels linear in der Zeit
LIVE_SHARE_POINTS = (0.0, 0.2533, 0.5057, 0.7575, 1.0)
LIVE_SHARE_MARGIN = (0.0, 0.3295, 0.5902, 0.8592, 1.0)   # Favoriten bauen ihren Vorsprung frueh auf und geben ihn spaeter (Garbage Time) teils ab
# Anteil der Vorab-Varianz, der zu Beginn des Viertels 1, 2, 3, 4 und am Ende (0) noch offen ist (gemessen; entspricht Restzeit-Anteil, bei der Marge etwas mehr)
LIVE_VAR_REST_TOTAL = (1.0, 0.7288, 0.4937, 0.2421, 0.0)
LIVE_VAR_REST_MARGIN = (1.0, 0.8292, 0.6077, 0.3218, 0.0)
LIVE_VAR_REST_TEAM = (1.0, 0.7595, 0.5206, 0.2616, 0.0)
# Tempo (Besitze je Team und 48 Minuten = FGA + 0,44 FTA - OREB + TOV). P0: Mittel der 11 Spiele (105,4, Standardfehler 1,3); K: Pseudo-Besitze der Bayes-Mischung
# n / (n + K) (aus den Daten nicht schaetzbar: Varianz zwischen den Spielen ~0 bis 4 gegen 56 Varianz innerhalb; K = Besitze je Viertel * 56 / (4 bis 9) = 150 bis 340).
LIVE_PACE_P0 = 105.0
LIVE_PACE_K = 150.0
LIVE_PACE_MULT_CLIP = (0.90, 1.10)
# Wettstatus (engine/bet_status.py): Auf Kurs ueber 65 %, Offen 35 bis 65 %, In Gefahr unter 35 %, Kaum noch moeglich unter 10 %
LIVE_STATUS_ON_TRACK = 0.65
LIVE_STATUS_DANGER = 0.35
LIVE_STATUS_HOPELESS = 0.10

# Sicherheitsstufen-Anzeige (Tab Score Projections, nur Anzeige; Grundlage: analysis/reports/threshold_test.txt, Stand 27.10.2026)
SAFETY_DISCOUNT = 0.03          # Mindestquote = 1 / (Chance - SAFETY_DISCOUNT): drei Prozentpunkte Sicherheitsabschlag
WINNER_MIN_PROB = 0.65          # Sieger-Zeichen "erfuellt" ab dieser Siegchance des Favoriten
WINNER_STRONG_PROB = 0.70       # zusaetzlich "(stark)" ab dieser Siegchance
# Spielerkarten (Tab Spieler, nur Anzeige; Grundlage: analysis/reports/threshold_test.txt, Spielerpunkte "Starter mit >= 10 bisherigen Spielen ab 80 %")
PLAYER_MIN_GAMES = 10           # weniger bisherige Spiele im Verlauf: Hinweis "Chance vermutlich zu hoch"; Starter-Zeichen erst ab so vielen Spielen
PLAYER_SAFE_MIN_PROB = 0.80     # Starter-Zeichen und Mindestquote erst ab dieser (ungerundeten) Roh-Chance
