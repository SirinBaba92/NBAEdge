"""SHOW_VALUE_BETS: Projektionen dasselbe mit/ohne Moneyline, nur Totals/Spreads-Abfrage bei False, Tabs im App-Lauf.
Alle HTTP-Zugriffe sind durch simulierte Antworten ersetzt (requests.get); jede nicht erlaubte URL bricht den Test ab.
Kein echter Odds-API-/BallDontLie-/NBA-Call. Das Pickle wird nur gelesen.
Aufruf: venv/bin/python tests/test_value_bets_switch.py"""
import ast, contextlib, datetime as dt, hashlib, json, sys, types, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, ".")
import requests
import config.settings as settings
from models.elo import EloEngine, MODEL_PATH

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()

# ---------------- simulierte Netzantworten (tests/fake_net.py; Caches/Logs in Temp-Verzeichnissen) ----------------
sys.path.insert(0, str(ROOT / "tests"))
import fake_net
fake_net.install(); fake_net.fresh_env()
SPIELE = fake_net.SPIELE
odds_markets_requested = fake_net.odds_markets_requested
other_urls = []

# ---------------- 1. refresh_data aus app.py (echter Quelltext) ----------------
src = (ROOT / "app.py").read_text()
tree = ast.parse(src)
funcs = {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
class _St:
    session_state = types.SimpleNamespace(bias_adjustments={})
    spinner = staticmethod(lambda *_a, **_k: contextlib.nullcontext())
    error = warning = staticmethod(lambda *_a, **_k: None)
from data.odds import parse_odds, parse_totals_spreads
from data.odds_client import get_odds
from data import market_lines, pre_match_store, pregame_lines
from data.fetcher import fetch_upcoming_games
from engine.projection import compute_projection
from engine.ev import find_value_bets
engine = EloEngine.load()

def run(flag):
    fake_net.fresh_env()
    settings.SHOW_VALUE_BETS = flag
    ns = dict(st=_St, OFFLINE_AUDIT_MODE=False, SHOW_VALUE_BETS=flag, parse_odds=parse_odds, parse_totals_spreads=parse_totals_spreads, get_odds=get_odds, pregame_lines=pregame_lines,
              fetch_upcoming_games=fetch_upcoming_games, compute_projection=compute_projection, find_value_bets=find_value_bets,
              date=dt.date, market_lines=market_lines, pre_match_store=pre_match_store, time=__import__("time"))
    for _fn in ("_resolve_lines", "_set_line_fields"):
        exec(funcs[_fn], ns)                       # Hilfsfunktionen der Marktlinien-Aufloesung (Schritt 9a)
    exec(funcs["match_lines"], ns); exec(funcs["refresh_data"], ns)
    bets, projs = ns["refresh_data"](engine)
    return bets, projs, list(odds_markets_requested)

bets_f, proj_f, req_f = run(False)
bets_t, proj_t, req_t = run(True)
check("False: genau EIN Odds-API-Request, nur Totals/Spreads", req_f == ["totals,spreads"], str(req_f))
check("True: wie bisher zwei Requests (h2h, Totals/Spreads)", req_t == ["h2h", "totals,spreads"], str(req_t))
check("False: keine Value Bets; True: Value Bets vorhanden (Moneyline wirkt nur dort)", bets_f == [] and len(bets_t) > 0, f"{len(bets_t)} Wetten bei True")
KEYS = ["exp_spread", "model_spread", "exp_total", "model_total", "market_total", "market_spread", "home_score", "away_score",
        "market_weight", "market_diff", "lineup_warning", "home_win_prob", "away_win_prob"]
same = len(proj_f) == len(proj_t) == 3 and all(a[k] == b[k] for a, b in zip(proj_f, proj_t) for k in KEYS)
check("Projektionen mit False == True (alle Schluessel)", same)
nick = lambda t: t.split()[-1]
print("\nSpiel | exp_spread (Heim +) | Modell-Total | finaler Total | Marktgewicht | Score Gast-Heim | False == True")
for a, b in zip(proj_f, proj_t):
    print(f"{nick(a['away_team'])} @ {nick(a['home_team'])} | {a['exp_spread']:+} | {a['model_total']} | {a['exp_total']} | {a['market_weight']} | "
          f"{a['away_score']}-{a['home_score']} | {all(a[k]==b[k] for k in KEYS)}")
print()

# ---------------- 2. echter App-Lauf (Streamlit AppTest): Tabs ----------------
from streamlit.testing.v1 import AppTest
def tabs(flag):
    fake_net.fresh_env(); settings.SHOW_VALUE_BETS = flag
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    return at, [t.label for t in at.tabs], list(odds_markets_requested)
def sidebar_state(at):
    sb = at.sidebar
    texts = [m.value for m in sb.markdown] + [c.value for c in sb.caption]
    return {
        "slider_min_ev": any(x.label == "Min EV %" for x in sb.slider),
        "min_max_odds": [x.label for x in sb.number_input],
        "bookmakers": any(x.label == "Bookmakers" for x in sb.multiselect),
        "bet_targets": any("Bet Targets only" in x.label for x in sb.checkbox),
        "filters_heading": any("Filters" in t for t in texts),
        "sharp_ref": any("Sharp ref" in t for t in texts),
        "refresh_button": any("Refresh Odds" in b.label for b in sb.button),
        "last_update": any(t.startswith("Last update") for t in texts),
        "ratings_bis": any(t.startswith("Ratings bis") for t in texts),
        "model_status": any("ELO Model loaded" in x.value for x in sb.success),
        "model_info": any("Model Info" in t for t in texts),
        "seasons": any(t.startswith("Seasons:") for t in texts),
        "self_corr": any(t.startswith("Self-correction teams") for t in texts),
        "dividers": len(sb.get("divider")),
    }

at_f, labels_f, req_af = tabs(False)
check("App ohne Fehler (False)", not at_f.exception, str([e.value for e in at_f.exception]))
check("False: Tab 'Value Bets' fehlt, 8 Tabs (inkl. neuem Spieltag-Tab, Pre-Match Eingabe am Ende)", not any("Value Bets" in l for l in labels_f) and len(labels_f) == 8 and labels_f[-1].endswith("Pre-Match Eingabe"), str(labels_f))
check("False: erster App-Lauf fragt nur Totals/Spreads ab", req_af and set(req_af) == {"totals,spreads"}, str(req_af))
# 'Last update' erscheint (wie schon vorher) erst nach dem ersten Lauf, daher ein Rerun ohne neue Abfrage
at_f.run()
sf = sidebar_state(at_f)
check("False: Filter-Widgets, 'Filters'-Ueberschrift und 'Sharp ref' ausgeblendet",
      not sf["slider_min_ev"] and sf["min_max_odds"] == [] and not sf["bookmakers"] and not sf["bet_targets"]
      and not sf["filters_heading"] and not sf["sharp_ref"], str(sf))
check("False: Refresh-Button, Last update, Ratings bis, Modellstatus, Model-Info-Zeilen bleiben",
      all(sf[k] for k in ("refresh_button", "last_update", "ratings_bis", "model_status", "model_info", "seasons", "self_corr")), str(sf))
check("False: keine doppelten Trennlinien (2 statt 3)", sf["dividers"] == 2, str(sf["dividers"]))
# Refresh-Button
btn = [b for b in at_f.button if "Refresh" in b.label][0]; odds_markets_requested.clear(); btn.click(); at_f.run()
check("False: 'Refresh Odds' fragt nur Totals/Spreads ab", set(odds_markets_requested) == {"totals,spreads"} and not at_f.exception, str(odds_markets_requested))
at_t, labels_t, req_at = tabs(True)
check("True: 9 Tabs inkl. 'Value Bets', beide Abfragen wie bisher", len(labels_t) == 9 and "🎯 Value Bets" in labels_t[0] and req_at[:2] == ["h2h", "totals,spreads"] and not at_t.exception, f"{labels_t} {req_at}")
at_t.run()
st_ = sidebar_state(at_t)
check("True: alle Filter, 'Filters' und 'Sharp ref' sichtbar wie bisher",
      st_["slider_min_ev"] and st_["min_max_odds"] == ["Min Odds", "Max Odds"] and st_["bookmakers"] and st_["bet_targets"]
      and st_["filters_heading"] and st_["sharp_ref"] and st_["dividers"] == 3, str(st_))
check("True: uebrige Sidebar-Elemente unveraendert",
      all(st_[k] for k in ("refresh_button", "last_update", "ratings_bis", "model_status", "model_info", "seasons", "self_corr")))
settings.SHOW_VALUE_BETS = False
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
