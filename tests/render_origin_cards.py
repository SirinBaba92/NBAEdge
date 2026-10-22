"""Screenshot der Score-Projections-Karten mit Herkunftszeile (nur Karten-HTML/CSS aus ui/score_cards.py, ohne Streamlit, ohne Netz):
Karte 1 nur Cache, Karte 2 gemischt (eigene Linie Total/Team Totals), Karte 3 nur eigene Linien mit gelbem Hinweis.
Aufruf: venv/bin/python tests/render_origin_cards.py   (braucht Google Chrome; schreibt PNG in den Temp-Ordner)"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
os.environ["NBAEDGE_TRACKING_DIR"] = tempfile.mkdtemp(prefix="nbaedge_origin_")
import data.market_lines as ml
import data.pre_match_store as ps
import ui.score_cards as sc
from engine.projection import compute_projection

H = 3600; T = time.time()
K, P = "New York Knicks", "Philadelphia 76ers"
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
pred = {"home_team": K, "away_team": P, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38}
def own(total=None, spread=None, team=None, at=T):
    d = Path(os.environ["NBAEDGE_TRACKING_DIR"]); [f.unlink() for f in d.glob("*.json")] if d.exists() else None
    ps.save_card("2026-10-21", iso(at + 6 * H), K, P, spread_rows=[{"id": "main", "line": spread, "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"}] if spread else None,
                 total_rows=[{"id": "main", "direction": None, "line": total, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}] if total else None,
                 team_rows={s: [{"id": "main", "direction": None, "line": v, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}] for s, v in (team or {}).items()} or None, now=at)
    return list(ps.load()["entries"].values())[0]
cache = {"spread": 4.3, "total": 232.0, "team_totals": {}}
def card(entry):
    res = ml.resolve_market_lines(entry, cache, T - 4000, "cache_vorab", K, P)
    t, s = ml.projection_inputs(res)
    proj = compute_projection(pred, market_total=t, market_spread=s, game_date="2026-10-21")
    proj.update(market_total=t, market_spread=s, market_lines=res)
    return "".join(l.strip() for l in sc.render_card_html(sc.build_card_vm(proj)).splitlines())
html = ("<html><head><meta charset='utf-8'><style>body{background:#0a0a0f;margin:24px;font-family:sans-serif}" + sc.CARD_CSS.replace("{{", "{").replace("}}", "}") + "</style></head><body>"
        + card(None) + card(own(total="231,5", team={"away": "113,5", "home": "118"}, at=T)) + card(own(total="241,5", spread="-9,5", team={"away": "113,5", "home": "128"}, at=T)) + "</body></html>")
out = Path(tempfile.mkdtemp(prefix="nbaedge_cards_")); (out / "cards.html").write_text(html, encoding="utf-8")
subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={out / 'karten_herkunft.png'}",
                "--window-size=1440,2500", f"file://{out / 'cards.html'}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
print("Screenshot:", out / "karten_herkunft.png")
