"""Tests: Betano-Automatik, wandernde Spielerstufen (Roadmap 3.2j). Offline: Betano-Antwort = vorhandene Rohantwort
analysis/results/betano_rockets_thunder_roh.json, Spielerstufen per parse_event-Ersatz verschoben, Temp-Ordner, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_auto_spieler.py"""
import copy, datetime as dt, hashlib, json, os, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install()
import betano_auto as ba
import betano_import as bi
import data.automation_log as alog
import data.pre_match_store as ps
from data import rosters

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
REAL = [ROOT / "data/tracking/pre_match_entries.json", ROOT / "data/automation.log", ROOT / "data/betano_auto_state.json", ROOT / "data/betano_auto.lock"]
real_before = {str(p): sha(p) for p in REAL}

RAW = json.loads((ROOT / "analysis/results/betano_rockets_thunder_roh.json").read_text())
H, A = "Houston Rockets", "Oklahoma City Thunder"
START = "2026-11-01T00:30:00Z"
KEY = ps.game_key("2026-10-31", START, H, A)
NOW = dt.datetime(2026, 10, 31, 19, 0, tzinfo=dt.timezone.utc).timestamp()
GAME = {"home_team": {"full_name": H}, "visitor_team": {"full_name": A}, "date": "2026-10-31", "datetime": START, "status": "scheduled"}
LIST = {"data": {"blocks": [{"events": [RAW["data"]["event"]]}]}}
SHAI, MITCHELL, MCCAIN, EASON = "Shai Gilgeous-Alexander", "Ajay Mitchell", "Jared McCain", "Tari Eason"

_orig_parse = bi.parse_event
PATCH = {}                                  # Spieler -> {Schwelle: Quote}: ersetzt die Betano-Stufen dieses Spielers
def parse(data, home, away):
    p = _orig_parse(data, home, away)
    for name, th in PATCH.items():
        p["players"][name] = dict(th)
    return p
bi.parse_event = parse

class Net:
    def __call__(self, path):
        return LIST if "/api/sport/" in path else RAW
def setup():
    tmp = fresh_env()
    (tmp / "rosters.json").write_text((ROOT / "data" / "rosters.json").read_text())
    os.environ["NBAEDGE_LIVE_DIR"] = str(tmp / "live")
    PATCH.clear()
    return tmp
def run(now=NOW):
    return ba.run_once(now=now, fetch=Net(), sleep=lambda s: None, pause_seconds=0, games=[GAME])
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def logtext(): return alog.log_path().read_text() if alog.log_path().exists() else ""
ROSTER = rosters.load()
def pid(name):
    for tn, t in ROSTER["teams"].items():
        for p in (t if isinstance(t, list) else t.get("players", [])):
            if p["name"] == name:
                return {**p, "team_name": tn}
    raise KeyError(name)
def block_dict(name, ths, odds=2.0, bid=None):
    p = pid(name)
    return {"block_id": bid, "person_id": p["person_id"], "name": name, "team": p["team_name"], "team_abbreviation": p.get("team_abbreviation") or "", "mode": "milestones",
            "rows": [{"id": None, "value": str(t), "odds": str(odds), "bookmaker": "Betano"} for t in ths]}
def seed(**players):
    ps.save_auto("2026-10-31", START, H, A, player_blocks=[block_dict(n, t) for n, t in players.items()], now=NOW - 7200)
def blocks(name): return [b for b in entry()["markets"][ps.PLAYER_POINTS]["players"] if b["name"] == name]
def act(name):
    b = [b for b in blocks(name) if b.get("active", True)]
    return sorted(l["threshold"] for l in b[0]["lines"] if l.get("active", True)) if b else []
def removed_auto(name, th):
    return any(l["threshold"] == th and l.get("active") is False and l["revisions"][-1]["action"] == "removed" and l["revisions"][-1].get("source") == "auto"
               for b in blocks(name) for l in b["lines"])
def odds(ths, o=2.0): return {t: o for t in ths}

# (a) Fall Fears: 9 gespeicherte Stufen (auto), Betano jetzt ganz andere 3 Stufen (9+3 > 10)
setup()
seed(**{SHAI: range(28, 37)})
PATCH[SHAI] = odds([37, 38, 39])
r0 = ps.save_auto("2026-10-31", START, H, A, player_blocks=[block_dict(SHAI, [37, 38, 39], bid="p1")], now=NOW)
check("0 Ausgangslage: ohne Entfernen scheitert der Spieler (höchstens 10 Meilensteine), Protokollzeile nennt ihn", r0["status"] == "unchanged" and any("Shai" in x and "höchstens 10" in x for x in r0["skipped_lines"]), str(r0))
r = run()
check("a Lauf OK, Spiel gespeichert, 0 Fehler", r["result"] == "OK" and list(r["games"].values()) == ["saved"] and "0 Fehler" in r["detail"], str(r))
check("a neue Stufen 37+ bis 39+ aktiv, alte 28+ bis 36+ weg", act(SHAI) == [37, 38, 39], str(act(SHAI)))
check("a alte Stufen als Revision removed mit source=auto (nichts gelöscht)", all(removed_auto(SHAI, t) for t in range(28, 37)))
check("a alle Revisionen des Spielers source=auto", all(x.get("source") == "auto" for b in blocks(SHAI) for x in ps._all_revisions(b)))
check("a übrige Spieler gespeichert (Mitchell, McCain, Eason aktiv)", all(act(n) for n in (MITCHELL, MCCAIN, EASON)))
# (b) Folgelauf
snap = json.dumps(ps.load(), sort_keys=True)
r = run()
check("b Folgelauf mit gleichen Daten: unverändert, Datei byte-gleich", list(r["games"].values()) == ["unchanged"] and json.dumps(ps.load(), sort_keys=True) == snap, str(r))

# (a2) Teilweise Verschiebung: Block bleibt, nur einzelne Stufen fallen weg
setup()
seed(**{MITCHELL: range(16, 25)})
PATCH[MITCHELL] = odds(range(20, 26))
r = run()
check("a2 Teilverschiebung 16-24 -> 20-25: gespeichert, Stufen 20+ bis 25+", r["result"] == "OK" and act(MITCHELL) == list(range(20, 26)) and len(blocks(MITCHELL)) == 1, f"{act(MITCHELL)} {r}")
check("a2 16+ bis 19+ als auto entfernt", all(removed_auto(MITCHELL, t) for t in range(16, 20)))

# (c) Hand-Zeilen: bleiben unberührt, Block übersprungen und im Protokoll genannt
setup()
seed(**{SHAI: range(28, 37)})
ps.save_card("2026-10-31", START, H, A, player_blocks=[block_dict(MCCAIN, [13, 14], bid=None)], now=NOW - 3600)       # Hand (ohne source)
hand_block = json.dumps(blocks(MCCAIN), sort_keys=True)
PATCH[MCCAIN] = odds([30, 31]); PATCH[SHAI] = odds([37, 38, 39])
r = run()
check("c Lauf OK, Spiel gespeichert (übrige Spieler/Märkte)", r["result"] == "OK" and list(r["games"].values()) == ["saved"], str(r))
check("c Hand-Block McCain byte-gleich", json.dumps(blocks(MCCAIN), sort_keys=True) == hand_block)
check("c Protokoll nennt den übersprungenen Spielerblock", "Spieler Jared McCain gehört der Hand" in logtext() or "Jared McCain gehört der Hand" in " ".join(r["notes"]), logtext()[-300:])
check("c übriger Spieler Shai trotzdem verschoben", act(SHAI) == [37, 38, 39])
# Hand-Revision macht auch einen entfernten Hand-Block dauerhaft zur Hand (wie bisher): Block bleibt auch nach Hand-Entfernen unberührt
ps.remove_player_block("2026-10-31", START, H, A, blocks(MCCAIN)[0]["id"], now=NOW - 60)
frozen = json.dumps(blocks(MCCAIN), sort_keys=True)
r = run()
check("c2 nach Hand-Entfernen bleibt der Block unberührt, kein Fehler", json.dumps(blocks(MCCAIN), sort_keys=True) == frozen and r["result"] == "OK", str(r))

# (d) Ein Spieler scheitert, der Rest wird gespeichert
setup()
seed(**{SHAI: range(28, 37)})
PATCH[SHAI] = odds([37, 38, 39]); _val = ps._validate_players
def failing(blocks, saved):                      # die Prüfung des Speichers lehnt genau diesen einen Spieler ab (Betano-Stufen selbst sind gültig)
    if any(b.get("name") == EASON for b in blocks or []):
        raise ps.CardInputError([f"Spielerpunkte · {EASON}: Testfehler Quote."])
    return _val(blocks, saved)
ps._validate_players = failing
r = run()
log = logtext(); ps._validate_players = _val
check("d Spiel gespeichert, Lauf OK/WARN ohne Abbruch", list(r["games"].values()) == ["saved"] and r["result"] in ("OK", "WARN"), str(r))
check("d Eason nicht gespeichert, Shai und Mitchell gespeichert", not act(EASON) and act(SHAI) == [37, 38, 39] and act(MITCHELL), f"{act(EASON)} {act(SHAI)}")
check("d Protokoll nennt Spieler und Grund", "Spieler Tari Eason übersprungen (Testfehler Quote)" in log, log[-400:])
check("d Spread/Total/Team Totals gespeichert", all(entry()["markets"].get(m) for m in (ps.SPREAD, ps.TOTAL, ps.TEAM_TOTALS)))

# (e) drei Läufe hintereinander mit wandernden Stufen
setup()
seed(**{SHAI: range(28, 37), MITCHELL: range(16, 25)})
res = []
for step, (a, b) in enumerate([(range(30, 39), range(18, 27)), (range(33, 42), range(19, 28)), (range(36, 45), range(22, 31))]):
    PATCH[SHAI], PATCH[MITCHELL] = odds(a), odds(b)
    r = run(NOW + step * 3600)
    res.append((r["result"], list(r["games"].values()), act(SHAI) == sorted(a), act(MITCHELL) == sorted(b)))
check("e 3 Läufe wandernde Stufen: alle OK, gespeichert, Stufen = Betano", all(x == ("OK", ["saved"], True, True) for x in res), str(res))
check("e nie mehr als 10 aktive Stufen, keine Fehler im Protokoll", len(act(SHAI)) <= 10 and "ERROR" not in logtext() and "WARN" not in logtext())
snap = json.dumps(ps.load(), sort_keys=True); r = run(NOW + 4 * 3600)
check("e Folgelauf unverändert", list(r["games"].values()) == ["unchanged"] and json.dumps(ps.load(), sort_keys=True) == snap, str(r))

real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unberührt (Hash vorher = nachher)", real_before == real_after)
print("ALLE OK" if ok else "FEHLER")
sys.exit(0 if ok else 1)
