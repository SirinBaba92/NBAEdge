"""Test: Schalter config.settings.SHOW_TEAM_ADJUSTED. False = der Teamabgleich (Modell B) wird in der App nicht angezeigt (Hinweiszeile, Umschalter Modell,
Modell-% im Wettschein); True = Anzeige wie vorher. Berechnung und gespeicherte Daten sind in beiden Faellen identisch.
Nur Temp-Ordner, kein Netz, keine echten Dateien. Aufruf aus dem Projektordner: venv/bin/python tests/test_team_adjusted_switch.py"""
import hashlib, json, os, sys, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from streamlit.testing.v1 import AppTest
from config import settings
from data import live_feed as lf
from data import pre_match_store as ps
from ui import bet_slip as bs
from ui import player_bet_entry as pbe
from ui import player_view as pv

class _NoNet:
    class R:
        status_code = 200
        def json(self): return {"scoreboard": {"gameDate": "2000-01-01", "games": []}}
    def get(self, url, **kw): return self.R()
lf._feed = lf.LiveFeed(http_get=_NoNet().get)

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()
tree = lambda: {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(T.rglob("*")) if p.is_file()}

NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
D = time.strftime("%Y-%m-%d", time.gmtime(NOW)); FUT = iso(NOW + 5 * 3600)
K = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
line = lambda th, odds: {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00"}
(T / "tracking").mkdir(parents=True, exist_ok=True)
(T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": {
    K: {"game_date": D, "markets": {"player_points": {"players": [{"id": "p1", "person_id": 1, "name": "Anton Alt", "team": "Heim Falken", "team_abbreviation": "HEI", "mode": "milestones", "active": True,
                                                                     "lines": [line(24, 2.2)]}]}}}}}))
def pl(raw, adj):
    return {"person_id": 1, "name": "Anton Alt", "team": "Heim Falken", "team_abbreviation": "HEI", "ok": True, "reason": None, "quality": [], "warnings": [],
            "quotes": [{"milestone": 24, "odds": 2.2, "bookmaker": "Betano", "bookmaker_probability": 1 / 2.2, "bookmaker_percent": 45, "updated_at": "x"}],
            "minutes": {"mean": 34.0, "base": 34.0, "role": "Stamm"}, "minutes_adjusted": 30.0, "expected_points_raw": 26.0, "expected_points_adjusted": 22.0, "p_ge_raw": {"24": raw}, "p_ge_adjusted": {"24": adj}, "games_used": {"2025-26": 30}}
entry = {"game_key": K, "created_at": "2026-10-23T00:19:41+02:00", "created_after_start": False, "note": "vor Anpfiff erstellt", "history": "Spielverlauf: x",
         "teams": {"Heim Falken": {"matched": True, "player_sum": 144.1, "team_points": 115.0, "factor": 0.85, "note": ""}}, "players": [pl(0.60, 0.50)]}
(T / "snaps").mkdir(parents=True, exist_ok=True)
(T / "snaps" / f"{D}.json").write_text(json.dumps({"version": 1, "day": D, "games": {K: entry}}))
HARNESS = str(ROOT / "tests" / "_harness_player_tab.py")
def run(table_view=False):
    at = AppTest.from_file(HARNESS, default_timeout=60).run()
    at.selectbox(key="pl_day").set_value(D).run()
    at.selectbox(key=f"pl_game_{D}").set_value(K).run()
    if table_view: at.toggle(key="pl_table_view").set_value(True).run()
    return at
text = lambda at: " ".join([x.value for x in at.markdown] + [c.value for c in at.caption])
OPT = {"milestone": 20, "odds": 2.2, "bookmaker_percent": 45, "model_raw": 0.60, "model_team": 0.72}

before = tree()
shown = {}
for flag in (False, True):
    settings.SHOW_TEAM_ADJUSTED = flag
    at_c, at_t = run(), run(True)
    tc, tt = text(at_c), text(at_t)
    shown[flag] = (tc, tt, [r.key for r in at_t.radio], [r.options for r in at_t.radio if r.key == "pl_mode"])
    h = pv.build_table_model(entry, "team", "team")["players"][0]
    shown[flag] += ((h["minutes"], h["points"], h["rows"][0]["model_pct"]),)
    shown[flag] += ((pbe.option_label(OPT), bs.option_label(OPT, "team"), bs.option_label(OPT, "raw")),)
    no_exc = not at_c.exception and not at_t.exception
    if flag is False:
        check("Schalter False: Karten und Tabelle ohne Exception", no_exc)
        check("False: keine Hinweiszeile 'Teamabgleich: ... Faktor' in der Anzeige", "Teamabgleich:" not in tc and "Teamabgleich:" not in tt and "Faktor 0,85" not in tc + tt)
        check("False: Tabellenansicht ohne Umschalter 'Modell' (nur roh)", "pl_mode" not in shown[flag][2] and "Teamabgleich" not in tt)
        check("False: Tabelle zeigt Modell roh (60 % bei 24+), nicht den Teamabgleich (50 %)", "60 %" in tt and "50 %" not in tt, __import__("re").sub(r"<style>.*?</style>", "", tt, flags=__import__("re").S)[-900:])
        check("False: Wettschein-Texte (Spieler-Wette und Schein) nennen Modell roh 60 %, nie 72 %", "Modell 60 %" in shown[flag][5][0] and "Modell 60 %" in shown[flag][5][1] and "Modell 60 %" in shown[flag][5][2])
    else:
        check("Schalter True: Karten und Tabelle ohne Exception", no_exc)
        check("True: Hinweiszeile 'Teamabgleich: Heim Falken: Spieler-Summe 144,1 → Teampunkte 115,0, Faktor 0,85' wie vorher", "Teamabgleich: Heim Falken: Spieler-Summe 144,1" in tc.replace("&nbsp;", " ") and "Faktor 0,85" in tc)
        check("True: Tabellenansicht mit Umschalter Modell (Teamabgleich/roh)", shown[flag][3] == [["Teamabgleich", "roh"]])
        check("True: Tabelle zeigt Teamabgleich (50 % bei 24+)", "50 %" in tt)
        check("True: Wettschein-Texte wie vorher (Spieler-Wette 72 %, Schein team 72 % / roh 60 %)", "Modell 72 %" in shown[flag][5][0] and "Modell 72 %" in shown[flag][5][1] and "Modell 60 %" in shown[flag][5][2])
check("Berechnung/Daten identisch: Tabellenmodell im Modus team (Minuten 30, Punkte 22, Modell 50 %) bei False und True gleich", shown[False][4] == shown[True][4] == (30.0, 22.0, 50), str(shown[False][4]))
check("Gespeicherte Daten identisch: Snapshot- und Tracking-Dateien nach den Laeufen mit False und True Byte fuer Byte wie vorher (Anzeige schreibt nichts)", tree() == before)
settings.SHOW_TEAM_ADJUSTED = False
check("Standard in config/settings.py ist False", __import__("importlib").reload(settings).SHOW_TEAM_ADJUSTED is False)
check("echte Dateien (Tracking, Snapshots) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
