"""Harness fuer tests/browser_score_check.py: startet die ECHTE app.py (alle Tabs) mit simulierten Netzantworten (tests/fake_net.py, kein echtes Netz,
Temp-Verzeichnisse). Nicht direkt starten."""
import json, os, runpy, sys, time, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.chdir(ROOT)
if not os.environ.get("NBAEDGE_HARNESS_READY"):            # nur beim ersten Lauf einrichten (Streamlit fuehrt das Skript bei jedem Rerun neu aus)
    import fake_net
    fake_net.install(); fake_net.fresh_env(remaining=400)
    from fake_net import state
    for k in ("NBAEDGE_TRACKING_DIR", "NBAEDGE_ROSTERS"):
        if os.environ.get("HARNESS_" + k): os.environ[k] = os.environ["HARNESS_" + k]
    import data.nba_live as nl; nl.NBA_CACHE_SECONDS = 10 ** 6
    n = time.time(); H = 3600
    K, P = "New York Knicks", "Philadelphia 76ers"
    iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
    def ev(home, away, total, pts, commence, eid):
        bms = []
        for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(pts)], pts):
            ms = [{"key": "totals", "last_update": iso(n - 700), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
                  {"key": "spreads", "last_update": iso(n - 700), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
            bms.append({"key": bk, "last_update": iso(n - 700), "markets": ms})
        return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
    Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu",
        "data": [ev(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}}, "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
    os.environ["NBAEDGE_HARNESS_READY"] = "1"
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
