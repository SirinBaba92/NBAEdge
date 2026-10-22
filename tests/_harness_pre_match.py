"""Harness fuer tests/browser_fragment_check.py: rendert nur den Tab 'Pre-Match Eingabe' (ohne Netzwerk) und zaehlt
Skriptlaeufe und Zeilenaufbauten in einer Zaehlerdatei. Nicht direkt starten."""
import datetime as dt, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
st.set_page_config(layout="wide")
st.markdown("<style>html,body,[class*='css']{background:#0a0a0f;color:#e8e8f0}.stApp{background:#0a0a0f}</style>", unsafe_allow_html=True)
# dieselbe globale Knopfregel wie app.py (Zeile ~109): ohne sie zeigt der Browsertest die Knoepfe NICHT so, wie sie in der echten App aussehen
st.markdown("<style>.stButton > button { background:#f97316; color:#0a0a0f; font-family:'Space Mono',monospace; font-weight:700; border:none; border-radius:8px; padding:8px 20px; width:100%; } .stButton > button:hover { background:#ea6a10; }</style>", unsafe_allow_html=True)
CF = os.environ["NBAEDGE_COUNTER_FILE"]
def bump(name):
    d = json.load(open(CF)); d[name] = d.get(name, 0) + 1; json.dump(d, open(CF, "w"))
bump("script")                                            # +1 bei jedem VOLLEN Skriptlauf
import ui.pre_match_tab as pmt
if not getattr(pmt, "_counted", False):                    # nur einmal pro Prozess umhuellen
    def wrap(name, counter):
        orig = getattr(pmt, name)
        def counted(*a, **k):
            bump(counter); return orig(*a, **k)
        setattr(pmt, name, counted)
    for nm in ("_line_row", "_spread_compact_row"): wrap(nm, "line_row")      # +1 je aufgebauter Spread-Zeile (Arbeit im Eingabebereich)
    for nm in ("_ou_main", "_ou_compact_row"): wrap(nm, "total_row")          # +1 je aufgebauter Total-/Team-Total-Zeile
    pmt._counted = True
n = float(os.environ.get("NBAEDGE_HARNESS_T0") or time.time()); iso = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
day = dt.date.today().isoformat()
projs = [
    dict(home_team="New York Knicks", away_team="Philadelphia 76ers", game_date=day, game_start=iso(n + 3 * 3600), game_status="x", market_spread=4.3, market_total=232.0, market_source="cache_vorab"),
    dict(home_team="San Antonio Spurs", away_team="Oklahoma City Thunder", game_date=day, game_start=iso(n + 5 * 3600), game_status="x", market_spread=-0.2, market_source="gespeichert"),
    dict(home_team="Detroit Pistons", away_team="Boston Celtics", game_date=day, game_start=iso(n - 1800), game_status="Q2 5:00"),
]
pmt.render_pre_match_tab(projs)
