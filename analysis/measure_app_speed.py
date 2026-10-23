"""
Messung der App-Geschwindigkeit bei laufendem Spiel (nur lesend, kein Netz). Stellt aus den echten Aufzeichnungen (~/NBAEdge_live_history, letzter Boxscore des Spiels 0022600006) einen
LAUFENDEN Zustand nach, speist ihn ueber eine Attrappe in den Live-Feed und misst per AppTest die Zeit je Fragment und je Tab, die Zahl der run_every-Fragmente, die Groesse der Spielertabelle und
die Zahl der Neuberechnungen pro Minute. Tracking-Dateien werden in einen Temp-Ordner KOPIERT (die echten werden nie geschrieben).
Aufruf:  venv/bin/python analysis/measure_app_speed.py [Wiederholungen, Standard 3] [--ohne-app]
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

N = int(next((a for a in sys.argv[1:] if a.isdigit()), 3))
WITH_APP = "--ohne-app" not in sys.argv

TMP = Path(tempfile.mkdtemp(prefix="nbaedge_measure_"))
(TMP / "tracking").mkdir()
for f in glob.glob(str(ROOT / "data" / "tracking" / "*.json")):
    shutil.copy(f, TMP / "tracking")
os.environ["NBAEDGE_TRACKING_DIR"] = str(TMP / "tracking")
os.environ["NBAEDGE_AUTOMATION_LOG"] = str(TMP / "automation.log")
os.environ["NBAEDGE_ODDS_CACHE"] = str(ROOT / "data" / "odds_cache.json")
os.environ["NBAEDGE_ODDS_LOG"] = str(TMP / "odds_calls.log")
os.environ["NBAEDGE_UPCOMING_CACHE"] = str(ROOT / "data" / "upcoming_cache.json")

import page_checks  # noqa: E402
page_checks.install()
os.environ["NBAEDGE_ALL_TABS"] = "0"                                  # Standardverhalten der App: nur der aktive Bereich rechnet
from streamlit.testing.v1 import AppTest  # noqa: E402
from data import day_bets_store as ds  # noqa: E402
from data import live_feed as lf  # noqa: E402
from data import pre_match_store as ps  # noqa: E402

LIVE = Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")
DAY = "2026-10-22"
GID = "0022600006"


class R:
    def __init__(self, payload): self.status_code, self._p, self.text = 200, payload, ""
    def json(self): return self._p


def latest_box() -> dict:
    files = sorted((LIVE / DAY / GID / "box").glob("*.json.gz"))
    return json.loads(gzip.decompress(files[len(files) // 2 if len(files) > 2 else -1].read_bytes()))["game"]       # ein Boxscore aus der Mitte des Spiels


BOX = latest_box()


def row(gid, status, game):
    t = lambda side: {"teamCity": game[side]["teamCity"], "teamName": game[side]["teamName"], "teamTricode": game[side]["teamTricode"], "score": game[side]["score"], "periods": []}
    return {"gameId": gid, "gameStatus": status, "gameStatusText": "", "period": game["period"], "gameClock": game["gameClock"], "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": game["gameTimeUTC"],
            "homeTeam": t("homeTeam"), "awayTeam": t("awayTeam")}


class Net:
    calls = 0
    def get(self, url, headers=None, params=None, timeout=None):
        Net.calls += 1
        if "espn.com" in url:
            return R({"events": []})
        if "scoreboard" in url:
            return R({"scoreboard": {"gameDate": DAY, "games": [row(GID, 2, BOX)]}})
        return R({"game": BOX})


def fresh_feed():
    lf._feed = lf.LiveFeed(http_get=Net().get)
    return lf._feed


# eigene Spieler-Wetten (nur in der Temp-Kopie), damit die Karten gefuellt sind
KEY = next((k for k in ps.game_key.__globals__["json"].loads((TMP / "tracking" / "pre_match_entries.json").read_text())["entries"] if k.startswith(DAY) and k.endswith("Cleveland Cavaliers")), None)
if KEY:
    d, start, home, away = KEY.split("|")
    from engine import player_odds as po
    entries = ps.load()["entries"]
    for p in po.game_player_odds(entries, KEY)[:4]:
        ds.set_player_bet(d, start, home, away, p["person_id"], p["name"], p["team"], p["rows"][len(p["rows"]) // 2]["milestone"], odds=2.0, stake=10, now=time.time() - 86400)

results: dict[str, list[float]] = {}


def timeit(name, fn, n=N):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    results[name] = ts
    return ts


def script_run(name, script, n=N):
    """Ein Streamlit-Lauf (AppTest.from_string) des Skripts, Mittel von n Laeufen; liefert den letzten Lauf zurueck."""
    ts, at = [], None
    for _ in range(n):
        fresh_feed()
        t = time.perf_counter()
        at = AppTest.from_string(script, default_timeout=180).run()
        ts.append(time.perf_counter() - t)
        if at.exception:
            print("  !", name, [str(e.value)[:100] for e in at.exception])
    results[name] = ts
    return at


def fmt(ts): return f"{statistics.mean(ts):6.2f} s (min {min(ts):.2f}, max {max(ts):.2f})"


def main() -> None:
    print(f"Messung mit {N} Wiederholungen; Spiel {GID}: Q{BOX['period']} {BOX['gameClock']} {BOX['awayTeam']['score']}:{BOX['homeTeam']['score']}; Spielkey {KEY}")
    # ---------------------------------------------------------------- Bausteine ohne Streamlit
    from ui import live_tab as lt, player_tab as pt, player_view as pv
    from data import market_lines
    feed = fresh_feed(); state = feed.refresh()
    timeit("Daten: store.load() (pre_match_entries.json)", lambda: ps.load())
    timeit("Daten: games_with_players(entries) (alle Eintraege)", lambda: pt.games_with_players(ps.load()["entries"]))
    timeit("Daten: market_lines.load_entries()", lambda: market_lines.load_entries())
    timeit("Daten: Prognose-Snapshot laden", lambda: ds.load_forecast_snapshot(KEY))
    timeit("Spieltag: build_page (kalt, Karten+Uebersicht+Wetten)", lambda: lt.build_page(state))
    lt._page_cache.update(key=None, page=None)
    timeit("Spieltag: get_page (Zwischenspeicher warm)", lambda: lt.get_page(state))
    entry = ds.load_forecast_snapshot(KEY)
    game = pt.game_for_key(state, KEY)
    timeit("Spieler: Meine Spieler-Wetten (Zeilen + HTML)", lambda: pt.bets_html(pt.player_bet_rows(state, ds.get_day_player_bets(state.day))))
    timeit("Spieler: live_table_data (Live-Chancen aller Zeilen)", lambda: pt.live_table_data(game, entry))
    live = pt.live_table_data(game, entry)
    timeit("Spieler: build_table_model + render_table_html", lambda: pv.render_table_html(pv.build_table_model(entry, "team", "team", ds.get_player_bets_by_key(KEY), live)))
    html = pv.render_table_html(pv.build_table_model(entry, "team", "team", ds.get_player_bets_by_key(KEY), live))
    nrows = html.count("<tr class=") 
    print(f"Spielertabelle (Live): {nrows} Zeilen, {len(html) / 1024:.0f} KB HTML, {html.count('<tbody')} Spieler")
    timeit("Spieler: Vergleich Ausfaelle (Modell + HTML)", lambda: pv.render_compare_html(pv.build_compare_model(entry, entry, "team")))
    # ---------------------------------------------------------------- Streamlit-Laeufe einzelner Fragmente (laufendes Spiel)
    pre = "import sys; sys.path.insert(0, %r)\n" % str(ROOT)
    script_run("Fragment Spieltag-Kopf (_live_head)", pre + "from ui import live_tab as lt\nlt._live_head(True)")
    script_run("Fragment Spieltag-Karten (_live_cards)", pre + "from ui import live_tab as lt\nlt._live_cards(True)")
    script_run("Fragment Meine Spieler-Wetten (_my_bets)", pre + "from ui import player_tab as pt\npt._my_bets()")
    script_run("Fragment Spielertabelle live (_table_live)", pre + f"from ui import player_tab as pt\nfrom data import day_bets_store as ds\nentry = ds.load_forecast_snapshot({KEY!r})\npt._table_live({KEY!r}, entry, 'team', 'team')")
    script_run("Fragment Prognose-Ansicht komplett (_forecast_view)", pre + "from ui import player_tab as pt\npt._forecast_view()")
    script_run("Tab Spieler komplett (render_player_tab)", pre + "from ui import player_tab as pt\npt.render_player_tab()")
    script_run("Tab Spieltag komplett (render_spieltag_tab)", pre + "from ui import live_tab as lt\nlt.render_spieltag_tab()")
    if WITH_APP:
        # Voller App-Lauf: (1) alle Tabs gleichzeitig (altes st.tabs, NBAEDGE_ALL_TABS=1), (2) nur der aktive Bereich (Standard)
        for label, env, tab in (("GANZE APP: alle Tabs gleichzeitig (alt)", "1", None), ("GANZE APP: nur Bereich Spieler", "0", "🏃 Spieler"), ("GANZE APP: nur Bereich Spieltag", "0", "🏀 Spieltag"),
                                ("GANZE APP: nur Bereich Score Projections", "0", "📊 Score Projections"), ("GANZE APP: nur Bereich Pre-Match Eingabe", "0", "✍️ Pre-Match Eingabe")):
            os.environ["NBAEDGE_ALL_TABS"] = env
            ts = []
            for _ in range(1 if env == "1" or "Pre-Match" in label else max(1, N - 1)):
                fresh_feed()
                at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=900).run()
                t = time.perf_counter()
                if tab:
                    at = at.radio(key="main_tab").set_value(tab).run()             # Wechsel in den Bereich = ein weiterer voller Lauf
                    ts.append(time.perf_counter() - t)
                else:
                    ts.append(statistics.mean([0]) or 0)                         # (Lauf unten gemessen)
            if tab is None:
                fresh_feed(); t = time.perf_counter(); AppTest.from_file(str(ROOT / "app.py"), default_timeout=900).run(); ts = [time.perf_counter() - t]
            results[label] = ts
        os.environ["NBAEDGE_ALL_TABS"] = "0"
    # ---------------------------------------------------------------- Ausgabe
    print("\nZeit je Lauf (Mittel), absteigend:")
    for name, ts in sorted(results.items(), key=lambda kv: -statistics.mean(kv[1])):
        print(f"  {fmt(ts)}  {name}")
    timers = {"Spieltag-Kopf": "Fragment Spieltag-Kopf (_live_head)", "Spieltag-Karten": "Fragment Spieltag-Karten (_live_cards)", "Meine Spieler-Wetten": "Fragment Meine Spieler-Wetten (_my_bets)",
              "Spielertabelle live": "Fragment Spielertabelle live (_table_live)"}
    per_min = sum(2 * statistics.mean(results[v]) for v in timers.values())
    print(f"\nAktive run_every-Fragmente (30 s) bei laufendem Spiel: {len(timers)} ({', '.join(timers)}); Fragment-Laeufe pro Minute: {2 * len(timers)}; Rechenzeit der Takte pro Minute: {per_min:.1f} s "
          f"= {100 * per_min / 60:.0f} % Auslastung (je Sitzung, nur Takte)")
    print(f"Netz-Abrufe der Attrappe waehrend der Messung: {Net.calls} (kein echter Abruf)")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
