"""Tests fuer Punkt 3: Die Projektion nutzt nur Vorab-Linien (data/pregame_lines.py).
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls. Aufruf aus dem Projektordner:
  venv/bin/python tests/test_pregame_lines.py"""
import copy, datetime as dt, hashlib, json, os, re, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.pregame_lines as pl
import data.odds_client as oc
import config.settings as settings
from models.elo import EloEngine, MODEL_PATH
from engine.projection import compute_projection
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_pg = (ROOT / "data" / "pregame_lines.json")
real_before = (real_pg.stat().st_mtime_ns, real_pg.stat().st_size) if real_pg.exists() else None
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def mk_event(home, away, total, home_point, commence, last_update, eid=None, books=("pinnacle", "draftkings")):
    bms = []
    for bk in books:
        ms = [{"key": "totals", "last_update": iso(last_update), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(last_update), "outcomes": [{"name": home, "point": home_point, "price": 1.9}, {"name": away, "point": -home_point, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(last_update), "markets": ms})
    return {"id": eid or f"ev-{home.split()[-1].lower()}-{int(commence)}", "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}

now = time.time(); H = 3600
# ================================================================== A) Erkennung Live-Linie
ev = mk_event("New York Knicks", "Philadelphia 76ers", 232.0, -4.5, now + H, now - 60)
check("Abruf VOR Anpfiff, last_update vor Anpfiff -> Vorab", not pl.is_live_snapshot(ev, now))
check("Abruf NACH Anpfiff -> live", pl.is_live_snapshot(ev, now + 2 * H))
ev_l = mk_event("New York Knicks", "Philadelphia 76ers", 245.5, -9.5, now - 1800, now - 60)
check("last_update nach dem Anpfiff -> live (auch wenn fetched_at unklar frueher liegt)", pl.is_live_snapshot(ev_l, now - 3600))
check("ungueltige commence_time -> vorsichtshalber live", pl.is_live_snapshot({"commence_time": "kaputt"}, now))

# ================================================================== B) Speicher
tmp = fresh_env()
e1 = mk_event("New York Knicks", "Philadelphia 76ers", 232.0, -4.5, now + H, now - 60)
e_far = mk_event("Boston Celtics", "Miami Heat", 220.0, -2.0, now + 10 * 24 * H, now - 60)
e_live = mk_event("Detroit Pistons", "Boston Celtics", 227.0, 1.0, now - 600, now - 60)
n = pl.update_from_snapshot([e1, e_far, e_live], now)
st = json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text())
check("Speicher: nur Vorab-Schnappschuss des Spiels in den naechsten 72 Std. (nicht live, nicht 10 Tage entfernt)", n == 1 and len(st) == 1 and next(iter(st.values()))["lines"]["total"] == 232.0, str(list(st)))
check("gespeicherte Linie: Total 232,0, Spread +4,5 (positiv = Heim-Favorit), gleiche Mittelung wie parse_totals_spreads", next(iter(st.values()))["lines"]["spread"] == 4.5)
check("zweiter identischer Aufruf aendert nichts", pl.update_from_snapshot([e1], now) == 0)
e1b = mk_event("New York Knicks", "Philadelphia 76ers", 233.5, -5.5, now + H, now - 30)
check("neuerer Vorab-Schnappschuss ersetzt die Linie", pl.update_from_snapshot([e1b], now + 10) == 1 and next(iter(json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text()).values()))["lines"]["total"] == 233.5)
e1_live = mk_event("New York Knicks", "Philadelphia 76ers", 250.0, -12.5, now + H, now + 2 * H)   # last_update nach Anpfiff
check("Live-Schnappschuss ueberschreibt die gespeicherte Vorab-Linie NICHT", pl.update_from_snapshot([e1_live], now + 3 * H) == 0 and next(iter(json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text()).values()))["lines"]["total"] == 233.5)
old = {"x": {"commence": now - 20 * 24 * H, "home_team": "A B", "away_team": "C D", "fetched_at": 1, "lines": {"total": 1, "spread": 1}}}
Path(os.environ["NBAEDGE_PREGAME_LINES"]).write_text(json.dumps({**json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text()), **old}))
pl.update_from_snapshot([e1b], now + 20)
check("Eintraege aelter als 14 Tage werden verworfen", "x" not in json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text()))

# ================================================================== C) line_for_game
tmp = fresh_env()
K, P = "New York Knicks", "Philadelphia 76ers"
pre = mk_event(K, P, 232.0, -4.5, now - 1800, now - 2400, eid="knicks-1")        # Vorab-Schnappschuss (40 Min. her), Spiel laeuft seit 30 Min.
live = mk_event(K, P, 245.5, -9.5, now - 1800, now - 60, eid="knicks-1")         # Live-Schnappschuss (vor 1 Min.)
future = mk_event(K, P, 231.0, -4.0, now + 3 * H, now - 60, eid="knicks-2")
lines, src = pl.line_for_game([future], now, K, P, game_start=now + 3 * H)
check("Spiel noch nicht gestartet: Linien aus dem Cache (cache_vorab)", src == "cache_vorab" and lines["total"] == 231.0 and lines["spread"] == 4.0)
lines, src = pl.line_for_game([pre], now - 2400, K, P, game_start=now - 1800, now=now)
check("laufendes Spiel, Cache stammt von VOR dem Anpfiff: Cache-Linie wird genutzt", src == "cache_vorab" and lines["total"] == 232.0)
check("... und diese Linie wurde nicht gespeichert, solange update_from_snapshot nicht lief", not Path(os.environ["NBAEDGE_PREGAME_LINES"]).exists())
pl.update_from_snapshot([pre], now - 2400, now=now - 2400)
lines, src = pl.line_for_game([live], now - 60, K, P, game_start=now - 1800, now=now)
check("laufendes Spiel, Live-Linie im Cache, Vorab-Linie gespeichert: gespeicherte Vorab-Linie (232,0 / +4,5), NICHT die Live-Linie (245,5)", src == "gespeichert" and lines["total"] == 232.0 and lines["spread"] == 4.5, f"{src} {lines and (lines['total'], lines['spread'])}")
tmp = fresh_env()
lines, src = pl.line_for_game([live], now - 60, K, P, game_start=now - 1800, now=now)
check("laufendes Spiel, Live-Linie im Cache, KEINE Vorab-Linie: (None, None) = ohne Marktlinie", lines is None and src is None)
pl.update_from_snapshot([pre], now - 2400, now=now - 2400)
lines, src = pl.line_for_game([], None, K, P, game_start=now - 1800, now=now)
check("Event fehlt im Cache (z. B. beendet): gespeicherte Vorab-Linie", src == "gespeichert" and lines["total"] == 232.0)
lines, src = pl.line_for_game([], None, "Detroit Pistons", "Boston Celtics", game_start=now - 600, now=now)
check("anderes Spiel ohne Eintrag: ohne Marktlinie", lines is None)
# Rematch / Zeitfenster
tmp = fresh_env()
near = mk_event(K, P, 232.0, -4.5, now + 2 * H, now - 60, eid="a"); far = mk_event(K, P, 240.0, -8.0, now + 10 * 24 * H, now - 60, eid="b")
lines, src = pl.line_for_game([far, near], now, K, P, game_start=now + 2 * H)
check("zwei Spiele derselben Teams: das zum Anpfiff passende wird gewaehlt (nicht das spaetere)", lines["total"] == 232.0)
lines, src = pl.line_for_game([far], now, K, P, game_start=now + 2 * H)
check("nur ein Spiel 10 Tage spaeter vorhanden: wird NICHT zugeordnet", lines is None)
lines, src = pl.line_for_game([mk_event(P, K, 232.0, 4.5, now + 2 * H, now - 60)], now, K, P, game_start=now + 2 * H)
check("vertauschte Heim/Auswaerts-Angabe wird wie bisher akzeptiert", src == "cache_vorab")

# ================================================================== D) odds_client speichert nach jedem Abruf
tmp = fresh_env(); fake_net.state["commence_offsets"] = {}
oc.get_odds("totals_spreads", caller="test")
st = json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text())
check("jeder echte Abruf (simuliert) speichert die Vorab-Linien der kommenden Spiele", len(st) == 3 and sorted(v["lines"]["total"] for v in st.values()) == [219.8, 230.7, 232.0], str(sorted(v["lines"]["total"] for v in st.values())))

# ================================================================== E) App-Lauf: Projektionen
engine = EloEngine.load()
def reference(home, away, total, spread):
    pred = engine.predict(home, away, dt.date.today())
    r = compute_projection(pred, market_total=total, market_spread=spread, game_date=dt.date.today().isoformat(), bias_adjustments={})
    r["market_total"], r["market_spread"] = total, spread
    return r
def setup(cache_fetched_ago, store_events=None, store_ago=2400, live_cache=True):
    tmp = fresh_env(remaining=400)
    state["commence_offsets"] = {"New York Knicks": -1800, "Detroit Pistons": -600, "San Antonio Spurs": 3 * H}
    n = time.time()
    k_cache = mk_event(K, P, 245.5 if live_cache else 232.0, -9.5 if live_cache else -4.5, n - 1800, n - cache_fetched_ago + (0 if live_cache else -30), eid="knicks")
    p_cache = mk_event("Detroit Pistons", "Boston Celtics", 227.2 if live_cache else 219.8, 1.5, n - 600, n - cache_fetched_ago + (0 if live_cache else -30), eid="pistons")
    s_cache = mk_event("San Antonio Spurs", "Oklahoma City Thunder", 230.7, 0.2, n + 3 * H, n - cache_fetched_ago, eid="spurs")
    Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - cache_fetched_ago, "markets": "totals,spreads", "regions": "us,eu", "data": [k_cache, p_cache, s_cache]}},
                                                                   "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
    oc._mem.update(path=None, mtime=None, obj=None)
    if store_events:
        pl.update_from_snapshot(store_events, n - store_ago, now=n - store_ago)
    return n
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
by_home = lambda at: {p["home_team"]: p for p in at.session_state["projections"]}
same = lambda p, r: all(p[k] == r[k] for k in ("exp_spread", "exp_total", "home_score", "away_score", "market_weight", "market_total", "market_spread"))

# E1: Live-Linien im Cache (vor 1 Min.), fuer Knicks gibt es eine gespeicherte Vorab-Linie, fuer Pistons nicht
n = setup(60, store_events=[mk_event(K, P, 232.0, -4.5, time.time() - 1800, time.time() - 2400, eid="knicks")])
at = app().run(); pr = by_home(at)
check("E1 keine Exception, Odds-Abrufe beim Start: 0 (Cache vorhanden)", not at.exception and len(state["odds_calls"]) == 0)
check("E1 Knicks (laeuft, Live-Linie im Cache): Projektion == Rechnung mit gespeicherter Vorab-Linie 232,0 / Knicks -4,5", same(pr[K], reference(K, P, 232.0, 4.5)) and pr[K]["market_source"] == "gespeichert", f"{pr[K]['exp_total']} {pr[K]['market_total']}")
check("E1 ... und NICHT == Rechnung mit der Live-Linie 245,5 / -9,5", not same(pr[K], reference(K, P, 245.5, 9.5)))
check("E1 Pistons (laeuft, Live-Linie, keine Vorab-Linie): reines Modell, market_total/market_spread None", pr["Detroit Pistons"]["market_total"] is None and pr["Detroit Pistons"]["market_spread"] is None and pr["Detroit Pistons"]["market_source"] is None and same(pr["Detroit Pistons"], reference("Detroit Pistons", "Boston Celtics", None, None)))
check("E1 Spurs (noch nicht gestartet): Cache-Linie 230,7 / +0,2 wie bisher", same(pr["San Antonio Spurs"], reference("San Antonio Spurs", "Oklahoma City Thunder", 230.7, -0.2)) and pr["San Antonio Spurs"]["market_source"] == "cache_vorab")
cards = [m.value for m in at.tabs[0].markdown if 'class="pc-card' in m.value]
pist = [c for c in cards if "Pistons" in c][0]; knick = [c for c in cards if "Knicks" in c][0]
check("E1 Karte Pistons: Hinweis 'ohne Marktlinie' in beiden Chips, Marktzeilen '—'", pist.count("ohne Marktlinie") == 2 and pist.count("—") >= 2)
check("E1 Karte Knicks: Marktzeile mit der Vorab-Linie (Knicks −4,5 / 232,0), kein Hinweis", "Knicks −4,5" in knick and "232,0" in knick and "ohne Marktlinie" not in knick and "245,5" not in knick)

# E2: dieselbe Lage ohne gespeicherte Vorab-Linie fuer Knicks
n = setup(60)
at = app().run(); pr = by_home(at)
check("E2 Knicks laeuft, nur Live-Linie, keine Vorab-Linie: reines Modell (ohne Marktlinie)", pr[K]["market_total"] is None and same(pr[K], reference(K, P, None, None)))

# E3: Cache wurde VOR dem Anpfiff abgerufen (vor 40 Min.), Spiel laeuft inzwischen
n = setup(2400, live_cache=False)
at = app().run(); pr = by_home(at)
check("E3 Cache stammt von vor dem Anpfiff: Linie wird genutzt (cache_vorab), Projektion == Rechnung mit 232,0 / -4,5", pr[K]["market_source"] == "cache_vorab" and same(pr[K], reference(K, P, 232.0, 4.5)))
st = json.loads(Path(os.environ["NBAEDGE_PREGAME_LINES"]).read_text())
check("E3 die Vorab-Linie wurde dabei gespeichert (fuer spaetere Live-Staende)", any(v["home_team"] == K and v["lines"]["total"] == 232.0 for v in st.values()))

# E4: danach kommt per Knopf ein Live-Schnappschuss -> Projektion bleibt bei der Vorab-Linie
LIVE_SPIELE = [(K, P, -9.5, 245.5), ("San Antonio Spurs", "Oklahoma City Thunder", 0.2, 230.7), ("Detroit Pistons", "Boston Celtics", 1.5, 227.2)]
fake_net.install(spiele=LIVE_SPIELE)
b = [b for b in at.button if "Refresh Odds" in b.label][0]; b.click().run(); pr = by_home(at)
check("E4 'Refresh Odds' waehrend das Spiel laeuft (Live-Schnappschuss): Knicks-Projektion bleibt auf der gespeicherten Vorab-Linie", not at.exception and len(state["odds_calls"]) == 1 and same(pr[K], reference(K, P, 232.0, 4.5)) and pr[K]["market_source"] == "gespeichert", f"{pr[K]['market_total']}")
check("E4 Pistons: in E3 lag ebenfalls ein Vorab-Schnappschuss vor, daher gespeicherte Linie 219,8 statt Live 227,2", pr["Detroit Pistons"]["market_total"] == 219.8 and pr["Detroit Pistons"]["market_source"] == "gespeichert")
fake_net.install()

# ================================================================== F) Rahmen
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
real_after = (real_pg.stat().st_mtime_ns, real_pg.stat().st_size) if real_pg.exists() else None
check("Projekt-data/pregame_lines.json durch die Tests weder angelegt noch veraendert", real_before == real_after)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
