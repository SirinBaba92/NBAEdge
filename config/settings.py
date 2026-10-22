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
