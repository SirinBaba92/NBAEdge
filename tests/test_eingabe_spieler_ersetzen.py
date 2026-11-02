"""Tests: Handweg (betano_import.run_one -> eingabe.run_game/execute_plan), Spieler ersetzen (Roadmap 3.2k). Offline: Betano-Antwort = vorhandene Rohantwort
analysis/results/betano_rockets_thunder_roh.json, Spielerstufen per parse_event-Ersatz verschoben, Temp-Ordner, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_eingabe_spieler_ersetzen.py"""
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


G = {"home": H, "away": A, "date": "2026-10-31", "start": START}
def hand(now=NOW):
    """Handabruf wie betano_import.main: run_one mit der Rohantwort (Betano-Stufen per PATCH verschoben); Rueckgabe (Ergebnis, Ausgabe, Fehler)."""
    out, asked = [], []
    def no_input(prompt=""):
        if str(prompt).startswith("Speichern?"):
            asked.append(1)
            if len(asked) > 1:                           # nach einer Ablehnung fragt die Eingabe erneut: hier abbrechen, statt endlos zu laufen
                raise AssertionError("Speichern abgelehnt: " + "".join(map(str, out))[-300:])
            return ""                                    # Enter = speichern
        raise AssertionError("unerwartete Eingabe: " + prompt)
    try:
        res = bi.run_one(out.append, G, RAW["data"], real=no_input, now_fn=lambda: now)
        return res, "\n".join(map(str, out)), None
    except Exception as e:
        return None, "\n".join(map(str, out)), e
def seed_hand(**players):
    ps.save_card("2026-10-31", START, H, A, player_blocks=[block_dict(n, t) for n, t in players.items()], now=NOW - 7200)    # ohne source = Hand
def filestate(): return ps.store_path().read_bytes() if ps.store_path().exists() else b""
def rev_actions(name, th):
    return [(x["action"], x.get("source", "hand")) for b in blocks(name) for l in b["lines"] if l["threshold"] == th for x in l["revisions"]]

# (a) Fall Fears: 9 gespeicherte Stufen, Betano jetzt ganz andere -> alle alten entfernen, neue speichern, ein Durchgang
setup(); seed_hand(**{SHAI: range(28, 37)})
PATCH[SHAI] = odds([37, 38, 39])
res, text, err = hand()
check("a kein Fehler beim Speichern (Spielerblock existiert nicht mehr)", err is None and "existiert nicht mehr" not in text, f"{err!r} {text[-300:]}")
check("a neue Stufen 37+ bis 39+ aktiv in neuem Block, alter Block inaktiv", act(SHAI) == [37, 38, 39] and len(blocks(SHAI)) == 2 and [b.get("active", True) for b in blocks(SHAI)] == [False, True], str([(b["id"], b.get("active")) for b in blocks(SHAI)]))
check("a alte Stufen: Revision removed (Hand, ohne source), nichts gelöscht", all(rev_actions(SHAI, t) == [("saved", "hand"), ("removed", "hand")] for t in range(28, 37)))
check("a übrige Spieler/Märkte aus demselben Durchgang gespeichert", act(MITCHELL) and entry()["markets"].get(ps.TOTAL))
# (e) Folgelauf
snap = filestate(); res, text, err = hand()
check("e Folgelauf mit gleichen Daten: unverändert, Datei byte-gleich, kein Fehler", err is None and filestate() == snap, f"{err!r} {text[-200:]}")

# (b) Teilentfernung: Block bleibt, wie bisher
setup(); seed_hand(**{MITCHELL: range(16, 25)})
PATCH[MITCHELL] = odds(range(20, 26))
bid_before = blocks(MITCHELL)[0]["id"]
res, text, err = hand()
check("b Teilentfernung 16-24 -> 20-25: Stufen 20+ bis 25+, derselbe Block (keine Neuanlage)", err is None and act(MITCHELL) == list(range(20, 26)) and len(blocks(MITCHELL)) == 1 and blocks(MITCHELL)[0]["id"] == bid_before, f"{err!r}")
check("b 16+ bis 19+ als removed (Hand)", all(rev_actions(MITCHELL, t)[-1] == ("removed", "hand") for t in range(16, 20)))

# (c) Fehler beim Speichern schreibt nichts Halbes (Trockenlauf findet ihn vor dem Entfernen)
setup(); seed_hand(**{SHAI: range(28, 37)})
PATCH[SHAI] = odds([37, 38, 39])
_val = ps._validate_players
def failing(blocks_, saved):
    if any(b.get("name") == SHAI and not b.get("block_id") for b in blocks_ or []):
        raise ps.CardInputError([f"Spielerpunkte · {SHAI}: Testfehler Quote."])
    return _val(blocks_, saved)
ps._validate_players = failing
snap = filestate(); res, text, err = hand(); ps._validate_players = _val
check("c Speichern abgelehnt, Datei byte-gleich (weder Entfernen noch Neuanlage)", err is not None and filestate() == snap, f"{err!r}")
check("c alte Stufen noch aktiv", act(SHAI) == list(range(28, 37)))
# (c2) Der Trockenlauf geht denselben Weg wie das Speichern: veraltete block_id wird schon beim Prüfen gemeldet
try:
    ps.save_card("2026-10-31", START, H, A, player_blocks=[block_dict(SHAI, [40], bid="p99")], dry_run=True, now=NOW)
    check("c2 veraltete block_id wird im Trockenlauf gemeldet", False)
except ps.OddsInputError as e:
    check("c2 veraltete block_id wird im Trockenlauf gemeldet", "existiert nicht mehr" in str(e), str(e))

# (d) Spread, Total, Team Totals: Hauptzeile bleibt immer, die Leiter kann nicht leer werden -> Hauptlinie wandert ohne Fehler
setup()
ou = lambda i, d, line: {"id": i, "direction": d, "line": str(line), "over_odds": "1.9", "under_odds": "1.9", "bookmaker": "Betano"}
sp = lambda i, line: {"id": i, "line": str(line), "home_odds": "1.9", "away_odds": "1.9", "bookmaker": "Betano"}
ps.save_card("2026-10-31", START, H, A, spread_rows=[sp("main", -3.5), sp(None, -5.5), sp(None, -4.5)],
             total_rows=[ou("main", None, 217.5), ou(None, "lower", 214.5), ou(None, "higher", 218.5)],
             team_rows={"away": [ou("main", None, 107.5), ou(None, "higher", 108.5)], "home": [ou("main", None, 109.5), ou(None, "higher", 110.5)]}, now=NOW - 7200)
res, text, err = hand()
lines = lambda k: [l for l in entry()["markets"][k]["lines"] if l.get("active", True)]
uniq = lambda ls, key: len({l[key] for l in ls}) == len(ls)
check("d Hauptlinien wandern (Spread/Total/Team Totals): kein Fehler, Hauptzeile je Markt vorhanden, keine Doppelung",
      err is None and all(any(l["id"] == "main" for l in lines(k)) for k in (ps.SPREAD, ps.TOTAL)) and uniq(lines(ps.SPREAD), "line_home") and uniq(lines(ps.TOTAL), "line")
      and all(uniq([l for l in entry()["markets"][ps.TEAM_TOTALS][s]["lines"] if l.get("active", True)], "line") for s in ("home", "away")), f"{err!r} {text[-300:]}")
snap = filestate(); res, text, err = hand()
check("d/e Folgelauf unverändert", err is None and filestate() == snap)

real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unberührt (Hash vorher = nachher)", real_before == real_after)
print("ALLE OK" if ok else "FEHLER")
sys.exit(0 if ok else 1)
