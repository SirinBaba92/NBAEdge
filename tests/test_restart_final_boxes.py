"""Neustart-Test ohne laufende App und ohne Netz: Beendete Spiele vom 25.10.2026 bekommen ihre Spielerpunkte aus final_box.json.gz des Recorders (nur lesen) bzw. aus dem eigenen Cache.
Voraussetzung: ~/NBAEdge_live_history/2026-10-25 vorhanden (sonst uebersprungen). Aufruf: venv/bin/python tests/test_restart_final_boxes.py"""
import gzip, json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory()
os.environ["NBAEDGE_FINAL_BOX_DIR"] = str(Path(TMP.name) / "cache")
from data import live_feed as lf

DAY = "2026-10-25"
REC = Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history") / DAY
if not REC.is_dir():
    print("SKIP: keine Aufnahme fuer", DAY); sys.exit(0)

boxes = {}
for d in sorted(p for p in REC.iterdir() if (p / "final_box.json.gz").exists()):
    boxes[d.name] = json.loads(gzip.decompress((d / "final_box.json.gz").read_bytes()))["game"]
team = lambda t: {k: t[k] for k in ("teamCity", "teamName", "teamTricode", "score", "periods")}
rows = [{"gameId": g, "gameStatus": 3, "gameStatusText": "Final", "period": 4, "gameClock": "", "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": b["gameTimeUTC"],
         "homeTeam": team(b["homeTeam"]), "awayTeam": team(b["awayTeam"])} for g, b in boxes.items()]

class R:
    def __init__(s, p): s.status_code, s.p, s.text = 200, p, ""
    def json(s): return s.p
calls = []
def get(url, **kw):
    calls.append(url)
    if "scoreboard" in url.lower():
        return R({"scoreboard": {"gameDate": DAY, "games": rows}})
    raise ConnectionError("kein Netz")

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

feed = lf.LiveFeed(http_get=get)                       # frischer Prozess = Neustart
st = feed.refresh(time.time(), day=DAY)
check("alle Spiele des Tages im Feed", len(st.games) == len(boxes) >= 7, len(st.games))
for g in st.games:
    exp = {p["personId"]: p["statistics"]["points"] for tm in ("homeTeam", "awayTeam") for p in boxes[g.game_id][tm]["players"]}
    got = {int(p.person_id): p.points for p in g.players}
    check(f"{g.game_id}: Spielerpunkte aus final_box, vollstaendig", g.players_complete and got and all(got[k] == exp[k] for k in got), f"{len(got)} Spieler")
check("kein Boxscore-Abruf bei NBA.com", not [c for c in calls if "boxscore" in c.lower()], len(calls))
print("ALLES BESTANDEN" if ok else "FEHLER"); sys.exit(0 if ok else 1)
