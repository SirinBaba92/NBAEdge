"""Tests: die uebrigen date.today()-Stellen in app.py meinen den US-Spieltag (us_today), nicht das Berliner Systemdatum.
Stellen: build_mock_projections (is_playoff, game_date), refresh_data (Rueckfall game_date), fetch_completed_games (Offline-Mock _display_date, Abfragetage dates[]).
Jede Pruefung laeuft mit dem alten Quelltext (git HEAD) und dem neuen: Zeitpunkt 27.10.2026 00:30 Berliner Zeit = 26.10. 18:30 in New York.
Offline (tests/fake_net.py, Temp-Verzeichnisse). Aufruf aus dem Projektordner: venv/bin/python tests/test_us_day_app.py"""
import ast, datetime as dt, os, subprocess, sys, types, warnings
from pathlib import Path
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.game_updates as gu
from engine.projection import is_playoff_date
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

BERLIN_NOW = dt.datetime(2026, 4, 20, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))      # 20.04. = Playoff-Zeit; in New York noch der 19.04.
BERLIN_DATE, US_DATE = dt.date(2026, 4, 20), dt.date(2026, 4, 19)
check("Ausgangslage: 00:30 Berlin ist in New York noch der Vortag", gu.us_today(BERLIN_NOW) == US_DATE and BERLIN_NOW.date() == BERLIN_DATE)

class FakeDate:
    @staticmethod
    def today(): return BERLIN_DATE                       # Berliner Systemdatum
new_src = (ROOT / "app.py").read_text()
old_src = subprocess.run(["git", "show", "HEAD:app.py"], capture_output=True, text=True, cwd=ROOT).stdout
def func(src, name):
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []                              # @st.cache_data weglassen
    mod = ast.Module(body=[node], type_ignores=[])
    return compile(ast.fix_missing_locations(mod), "app.py", "exec")

board = [{"home_city": "New York", "home_team": "Knicks", "away_city": "Boston", "away_team": "Celtics", "home_score": 110, "away_score": 100}]
def ns(**extra):
    d = dict(date=FakeDate, timedelta=dt.timedelta, datetime=dt.datetime, us_today=lambda: gu.us_today(BERLIN_NOW), is_playoff_date=is_playoff_date,
             load_mock_scoreboard=lambda: board, OFFLINE_AUDIT_MODE=True, os=os, time=types.SimpleNamespace(sleep=lambda *_: None))
    d.update(extra); return d

# ---------------------------------------------------------------- Zeile 301/304: Mock-Projektionen
for label, src in (("alt (HEAD)", old_src), ("neu", new_src)):
    n = ns(); exec(func(src, "build_mock_projections"), n)
    p = n["build_mock_projections"]()[0]
    want = BERLIN_DATE if label.startswith("alt") else US_DATE
    check(f"Mock-Projektion {label}: game_date = {want}", p["game_date"] == want.isoformat(), p["game_date"])
    check(f"Mock-Projektion {label}: is_playoff passend zum Datum", p["is_playoff"] == is_playoff_date(want.isoformat()))
# Stichtag, an dem es einen Unterschied macht: 1. Playoff-Tag in Berlin 00:30, in New York noch Regular Season
from engine import projection as pj
sd = dt.date(2026, *pj.PLAYOFF_START_MONTH_DAY)
PO = dt.datetime(sd.year, sd.month, sd.day, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
for label, src in (("alt (HEAD)", old_src), ("neu", new_src)):
    class FD:
        @staticmethod
        def today(): return PO.date()
    n = ns(date=FD, us_today=lambda: gu.us_today(PO)); exec(func(src, "build_mock_projections"), n)
    p = n["build_mock_projections"]()[0]
    want = label == "alt (HEAD)"                          # alt: Berliner Datum = Playoff-Start -> True (falsch); neu: Vortag in New York -> False
    check(f"Mock-Projektion {label}: am Playoff-Starttag 00:30 Berlin is_playoff = {want}", p["is_playoff"] is want, str(p["is_playoff"]))

# ---------------------------------------------------------------- Zeile 478/496: fetch_completed_games
for label, src in (("alt (HEAD)", old_src), ("neu", new_src)):
    n = ns(); exec(func(src, "fetch_completed_games"), n)
    g = n["fetch_completed_games"](2)
    want = BERLIN_DATE if label.startswith("alt") else US_DATE
    check(f"Offline-Mock {label}: _display_date = {want}", g[0]["_display_date"] == want.isoformat(), g[0]["_display_date"])
asked = {"old": [], "new": []}
class Resp:
    status_code = 200
    def json(self): return {"data": []}
for label, src in (("alt (HEAD)", old_src), ("neu", new_src)):
    key = "old" if label.startswith("alt") else "new"
    req = types.SimpleNamespace(get=lambda url, headers=None, params=None, timeout=None, k=key: (asked[k].append(params["dates[]"]), Resp())[1])
    n = ns(OFFLINE_AUDIT_MODE=False, requests=req); exec(func(src, "fetch_completed_games"), n)
    os.environ.setdefault("BALLDONTLIE_API_KEY", "x")
    n["fetch_completed_games"](2)
check("Abfragetage alt: 19.04. und 18.04. (ab Berliner Datum 20.04. - falsch, der 19.04. laeuft in New York noch)", asked["old"] == ["2026-04-19", "2026-04-18"], str(asked["old"]))
check("Abfragetage neu: 18.04. und 17.04. (nur abgeschlossene US-Tage)", asked["new"] == ["2026-04-18", "2026-04-17"], str(asked["new"]))

# ---------------------------------------------------------------- Zeile 422: Rueckfall game_date in refresh_data (App-Lauf)
import data.fetcher as fetcher
def run_app(src_text):
    fresh_env()
    games = [{"id": 1, "datetime": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "status": "7:00 PM ET", "postponed": False,
              "home_team": {"full_name": "New York Knicks"}, "visitor_team": {"full_name": "Philadelphia 76ers"}}]      # ohne Feld "date"
    orig_f, orig_u = fetcher.fetch_upcoming_games, gu.us_today
    fetcher.fetch_upcoming_games = lambda: games
    gu.us_today = lambda now=None: dt.date.today() - dt.timedelta(days=1)         # US-Tag hinkt dem Berliner Datum nach (00:00-06:00 Berlin)
    try:
        at = AppTest.from_string(src_text, default_timeout=120) if src_text is not None else AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
        at.run()
        projs = at.session_state["projections"]
        return at, [p.get("game_date") for p in projs]
    finally:
        fetcher.fetch_upcoming_games, gu.us_today = orig_f, orig_u
us_day = (dt.date.today() - dt.timedelta(days=1)).isoformat()
at, got = run_app(None)
check("refresh_data neu: Spiel ohne 'date' bekommt den US-Spieltag", got == [us_day] and not at.exception, f"{got} exc={[e.value for e in at.exception]}")
alt_text = new_src.replace('game.get("date") or us_today().isoformat()', 'game.get("date") or date.today().isoformat()')
try:
    at, got = run_app(alt_text)
    check("refresh_data alt (Rueckfall date.today): Berliner Datum - falsch", got == [dt.date.today().isoformat()] and got != [us_day], str(got))
except Exception as e:
    check("refresh_data alt konnte nicht aus Text gestartet werden", False, repr(e))
print("ENDE" if ok else "FEHLER")
sys.exit(0 if ok else 1)
