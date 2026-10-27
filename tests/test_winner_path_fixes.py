"""Tests der vier Korrekturen am Weg der Siegchance (Grundlage analysis/reports/winner_path_audit.txt):
1) vertauschte Heim/Gast-Rollen in engine/ev.py und data/pregame_lines.py, 2) US-Spieltag statt date.today() in app.py,
3) Spielfilter in data/fetcher.py (nur Final ausblenden), 4) sichtbare Hinweise bei altem BallDontLie-Cache / unlesbarem Odds-Cache.
Offline (tests/fake_net.py, Temp-Verzeichnisse). Aufruf aus dem Projektordner: venv/bin/python tests/test_winner_path_fixes.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.fetcher as fetcher
import data.game_updates as gu
import data.odds_client as oc
import data.pregame_lines as pl
from engine.ev import _match_game, find_value_bets
from models.elo import EloEngine, MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
REAL = ("odds_cache.json", "upcoming_cache.json", "pregame_lines.json")
real_before = {f: ((ROOT / "data" / f).stat().st_mtime_ns, (ROOT / "data" / f).stat().st_size) if (ROOT / "data" / f).exists() else None for f in REAL}

# ============================================================ 1a) engine/ev.py: _match_game
def odds_game(home, away, h, a, dk):
    return {"home_team": home, "away_team": away, "commence_time": "2026-10-28T00:00:00Z",
            "bookmakers": {"pinnacle": {"home_odds": h, "away_odds": a}, "draftkings": {"home_odds": dk[0], "away_odds": dk[1]}}}
# ohne Vertauschung: Boston ist Heim, Quote 1.50 auf Boston
g_ok = odds_game("Boston Celtics", "Brooklyn Nets", 1.50, 2.80, (1.80, 2.40))
m = _match_game("Boston Celtics", "Brooklyn Nets", [g_ok])
check("1a ohne Vertauschung: Spiel unveraendert", m["home_team"] == "Boston Celtics" and m["bookmakers"]["pinnacle"]["home_odds"] == 1.50)
# vertauscht: die Odds API fuehrt Brooklyn als Heim (Quote 2.80 gehoert zu Brooklyn!)
g_rev = odds_game("Brooklyn Nets", "Boston Celtics", 2.80, 1.50, (2.40, 1.80))
m = _match_game("Boston Celtics", "Brooklyn Nets", [g_rev])
check("1a vertauscht: Heim = Boston, home_odds = 1.50 (Quote von Boston)", m["home_team"] == "Boston Celtics" and m["bookmakers"]["pinnacle"]["home_odds"] == 1.50 and m["bookmakers"]["pinnacle"]["away_odds"] == 2.80)
check("1a Original-Eintrag der Odds-Liste bleibt unveraendert", g_rev["home_team"] == "Brooklyn Nets" and g_rev["bookmakers"]["pinnacle"]["home_odds"] == 2.80)
# Wirkung auf die Value Bets: Modell sieht Boston mit 70 %; die Quote auf Boston ist 1.50 (fair ~ 0.65), auf Brooklyn 2.80
pred = {"home_team": "Boston Celtics", "away_team": "Brooklyn Nets", "home_win_prob": 0.70, "away_win_prob": 0.30,
        "home_elo": 1600, "away_elo": 1450, "home_form": 0, "away_form": 0, "home_rest_days": 2, "away_rest_days": 2, "expected_total": 225}
def bets(game):
    return find_value_bets([pred], [game])
b_ok, b_rev = bets(g_ok), bets(g_rev)
key = lambda bs: sorted((b["bet_on"], b["side"], b["decimal_odds"], b["bookmaker"]) for b in bs)
check("1a Value Bets: es gibt eine Wette auf Boston @ 1.80", [(b["bet_on"], b["decimal_odds"]) for b in b_ok] == [("Boston Celtics", 1.80)], str(key(b_ok)))
check("1a Value Bets: vertauschte Quote liefert dasselbe Ergebnis wie die normale (vorher: Quote des Gegners)", key(b_ok) == key(b_rev), f"{key(b_ok)} / {key(b_rev)}")
check("1a keine Phantom-Wette 'Boston @ 2.80'", all(not (b["bet_on"] == "Boston Celtics" and b["decimal_odds"] == 2.80) for b in b_rev))

# ============================================================ 1b) data/pregame_lines.py: Vorzeichen
now = time.time(); H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def mk_event(home, away, home_point, commence, eid):
    ms = [{"key": "totals", "last_update": iso(now - 900), "outcomes": [{"name": "Over", "point": 225.5, "price": 1.9}, {"name": "Under", "point": 225.5, "price": 1.9}]},
          {"key": "spreads", "last_update": iso(now - 900), "outcomes": [{"name": home, "point": home_point, "price": 1.87}, {"name": away, "point": -home_point, "price": 1.95}]}]
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(now + 3 * H),
            "bookmakers": [{"key": "pinnacle", "last_update": iso(now - 900), "markets": ms}]}
fresh_env()
# Boston ist -6.5 Favorit. Normal: Boston Heim -> spread +6.5 (positiv = Heim stark)
ev_ok = mk_event("Boston Celtics", "Brooklyn Nets", -6.5, now, "ok")
lines, src = pl.line_for_game([ev_ok], now - 600, "Boston Celtics", "Brooklyn Nets")
check("1b ohne Vertauschung: Spread +6.5 fuer Boston als Heim", lines and lines["spread"] == 6.5 and src == "cache_vorab", str(lines and lines["spread"]))
# Vertauscht: Odds API fuehrt Brooklyn als Heim (+6.5 Handicap). Aus Sicht von Boston (Heim) muss der Spread +6.5 bleiben
ev_rev = mk_event("Brooklyn Nets", "Boston Celtics", 6.5, now, "rev")
lines, src = pl.line_for_game([ev_rev], now - 600, "Boston Celtics", "Brooklyn Nets")
check("1b vertauscht (Cache-Vorab): Spread aus Sicht Boston = +6.5 (vorher -6.5)", lines["spread"] == 6.5 and lines["home_team"] == "Boston Celtics", str(lines["spread"]))
check("1b vertauscht: Roh-Handicap und Spread-Quoten mitgedreht", lines["spread_home_point"] == -6.5 and lines["spread_home_odds"] == 1.95 and lines["spread_away_odds"] == 1.87)
check("1b vertauscht: Total unveraendert", lines["total"] == 225.5)
# gespeicherter Eintrag (Spiel laeuft schon, kein Cache-Vorab): gleiche Orientierung
pl.update_from_snapshot([ev_rev], now - 600, now=now)
lines, src = pl.line_for_game([], None, "Boston Celtics", "Brooklyn Nets")
check("1b vertauscht (gespeichert): Spread +6.5", src == "gespeichert" and lines["spread"] == 6.5, f"{src} {lines and lines['spread']}")
lines, src = pl.line_for_game([], None, "Brooklyn Nets", "Boston Celtics")
check("1b gespeichert, Anfrage aus Sicht Brooklyn als Heim: Spread -6.5, Original-Rolle", src == "gespeichert" and lines["spread"] == -6.5, f"{lines and lines['spread']}")

# ============================================================ 2) US-Spieltag
nach_mitternacht = dt.datetime(2026, 10, 27, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
check("2 us_today(00:30 Berlin am 27.10.) = 26.10. (US-Spieltag)", gu.us_today(nach_mitternacht) == dt.date(2026, 10, 26))
check("2 us_today(14:00 Berlin) = gleicher Tag", gu.us_today(dt.datetime(2026, 10, 27, 14, 0, tzinfo=ZoneInfo("Europe/Berlin"))) == dt.date(2026, 10, 27))
check("2 us_today() ohne Argument weiterhin heute (US)", isinstance(gu.us_today(), dt.date))

def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def restart():
    oc._mem.update(path=None, mtime=None, obj=None)
    import data.live_market as lm, data.nba_live as nl
    lm._CACHE.update(fetched_at=0.0, lines={}); nl._cache.clear()
def warnings_of(at): return [w.value for w in at.warning]

fresh_env(); restart()
seen = []
_orig_predict = EloEngine.predict
EloEngine.predict = lambda self, home, away, d=None, *a, **k: (seen.append(d), _orig_predict(self, home, away, d, *a, **k))[1]
_orig_us = gu.us_today
gu.us_today = lambda now=None: _orig_us(nach_mitternacht)
at = app(); at.run()
EloEngine.predict = _orig_predict; gu.us_today = _orig_us
check("2 App: Elo-Engine bekommt den US-Spieltag (26.10.), nicht das Berliner Systemdatum", seen and all(d == dt.date(2026, 10, 26) for d in seen) and not at.exception, f"{set(seen)} exc={[e.value for e in at.exception]}")

# ============================================================ 3) Spielfilter
def game(i, status, when):
    return {"id": i, "date": when[:10], "datetime": when, "status": status, "postponed": False,
            "home_team": {"full_name": f"H{i}"}, "visitor_team": {"full_name": f"V{i}"}}
fresh_env()
n_ = dt.datetime.now(dt.timezone.utc)
z = lambda h: (n_ + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
liste = [game(1, "Final", z(-6)), game(2, "Q3 4:12", z(-2)), game(3, "7:00 PM ET", z(2)), game(4, "7:00 PM ET", z(20)), game(5, "Halftime", z(-1.5)), game(6, "Final", z(-30))]
_orig_get = fetcher._get
fetcher._get = lambda path, params=None, retries=0: {"data": liste, "meta": {}}
res = fetcher.fetch_upcoming_games()
fetcher._get = _orig_get
check("3 nur beendete Spiele fliegen raus; laufende und kommende (auch in 20 h) bleiben", [g["id"] for g in res] == [2, 3, 4, 5], str([g["id"] for g in res]))
liste.append({"id": 7, "date": "2026-10-27", "status": "7:00 PM ET", "home_team": {"full_name": "H7"}, "visitor_team": {"full_name": "V7"}})
fetcher._get = lambda path, params=None, retries=0: {"data": liste, "meta": {}}
fresh_env(); res = fetcher.fetch_upcoming_games(); fetcher._get = _orig_get
check("3 Eintrag ohne Uhrzeit (nur Datum, nicht Final) bleibt sichtbar", [g["id"] for g in res] == [2, 3, 4, 5, 7], str([g["id"] for g in res]))

# ============================================================ 4a) Banner: alter BallDontLie-Cache
fresh_env(); restart()
_orig_sleep = time.sleep; time.sleep = lambda *_: None
at = app(); at.run()
check("4a normaler Lauf: kein Banner 'Spieldaten nicht aktuell'", not any("Spieldaten nicht aktuell" in w for w in warnings_of(at)) and not at.exception, str(warnings_of(at)))
p = Path(os.environ["NBAEDGE_UPCOMING_CACHE"]); d = json.loads(p.read_text()); stand = d["fetched_at"] - 3000; d["fetched_at"] = stand; p.write_text(json.dumps(d))
state["bdl_status"] = 429
restart(); at = app(); at.run()
w = [x for x in warnings_of(at) if "Spieldaten nicht aktuell" in x]
erwartet = dt.datetime.fromtimestamp(stand).strftime("%d.%m. %H:%M")
check("4a BallDontLie ausgefallen, alter Cache: gelbes Banner mit Stand-Uhrzeit des Caches", len(w) == 1 and erwartet in w[0] and not at.exception, f"{w} erwartet {erwartet}")
state["bdl_status"] = 200
d = json.loads(p.read_text()); d["fetched_at"] -= 1000; p.write_text(json.dumps(d))
restart(); at = app(); at.run()
check("4a danach wieder erreichbar: Banner weg", not any("Spieldaten nicht aktuell" in x for x in warnings_of(at)), str(warnings_of(at)))
time.sleep = _orig_sleep

# ============================================================ 4b) Hinweis: unlesbarer Odds-Cache
fresh_env(); restart(); oc._problem.update(at=None, path=None, error=None)
at = app(); at.run()
check("4b gesunder Odds-Cache: kein Hinweis", not any("Odds-Zwischenspeicher" in w for w in warnings_of(at)) and oc.cache_problem() is None)
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text("{kaputt")
restart(); at = app(); at.run()
w = [x for x in warnings_of(at) if "Odds-Zwischenspeicher" in x]
check("4b unlesbarer Odds-Cache: sichtbarer Hinweis statt stillem Leerlauf", len(w) == 1 and not at.exception, str(warnings_of(at)))
check("4b cache_problem() meldet Zeit und Pfad; nach einer Stunde wieder None", oc.cache_problem() and oc.cache_problem(time.time() + 3601) is None)
oc._problem.update(at=None, path=None, error=None)

# ============================================================ Echte Dateien
real_after = {f: ((ROOT / "data" / f).stat().st_mtime_ns, (ROOT / "data" / f).stat().st_size) if (ROOT / "data" / f).exists() else None for f in REAL}
check("Projekt-data/ (odds_cache, upcoming_cache, pregame_lines) unberuehrt", real_before == real_after)
check("Modelldatei unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
print("ENDE" if ok else "FEHLER")
sys.exit(0 if ok else 1)
