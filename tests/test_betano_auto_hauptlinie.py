"""Tests: Betano-Automatik, wandernde Hauptlinie (Spread, Total, Team Totals). Offline: Betano-Antwort = vorhandene Rohantwort
analysis/results/betano_rockets_thunder_roh.json (Hauptlinien veraendert), Temp-Ordner, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_auto_hauptlinie.py"""
import copy, hashlib, json, os, sys, urllib.error, warnings
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
import datetime as dt
NOW = dt.datetime(2026, 10, 31, 19, 0, tzinfo=dt.timezone.utc).timestamp()
GAME = {"home_team": {"full_name": H}, "visitor_team": {"full_name": A}, "date": "2026-10-31", "datetime": START, "status": "scheduled"}
LIST = {"data": {"blocks": [{"events": [RAW["data"]["event"]]}]}}

def variant(spread=None, total=None, thunder=None, rockets=None):
    """Rohantwort mit verschobener Hauptlinie (die Leitern bleiben wie bei Betano)."""
    d = copy.deepcopy(RAW)
    for m in d["data"]["event"]["markets"]:
        sel = m.get("selections") or []
        if m["type"] == "OUAO" and len(sel) == 2 and thunder is not None:
            m["handicap"] = thunder; [s.__setitem__("handicap", thunder) or s.__setitem__("name", s["name"].split()[0] + f" {thunder}") for s in sel]
        if m["type"] == "OUHO" and len(sel) == 2 and rockets is not None:
            m["handicap"] = rockets; [s.__setitem__("handicap", rockets) or s.__setitem__("name", s["name"].split()[0] + f" {rockets}") for s in sel]
    return d

class Net:
    def __init__(self, data): self.data, self.calls = data, []
    def __call__(self, path):
        self.calls.append(path)
        return LIST if "/api/sport/" in path else self.data

def setup():
    tmp = fresh_env()
    (tmp / "rosters.json").write_text((ROOT / "data" / "rosters.json").read_text())
    os.environ["NBAEDGE_LIVE_DIR"] = str(tmp / "live")
    return tmp
def run(data, now=NOW, **kw):
    return ba.run_once(now=now, fetch=Net(data), sleep=lambda s: None, pause_seconds=0, games=[GAME], **kw)
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def logtext(): return alog.log_path().read_text() if alog.log_path().exists() else ""
def ou(i, d, line, o="1.9", u="1.9"): return {"id": i, "direction": d, "line": str(line), "over_odds": o, "under_odds": u, "bookmaker": "Betano"}
def sp(i, line, h="1.9", a="1.9"): return {"id": i, "line": str(line), "home_odds": h, "away_odds": a, "bookmaker": "Betano"}
def seed(spread, total, away, home, **kw):
    """Gespeicherter Stand der Automatik (source=auto); Zeilen: (Linie, Richtung)-Listen, Hauptlinie zuerst."""
    r = lambda lines, f: [f("main" if k == 0 else None, *l) for k, l in enumerate(lines)]
    return ps.save_auto("2026-10-31", START, H, A, spread_rows=[sp("main" if k == 0 else None, l) for k, l in enumerate(spread)],
                        total_rows=[ou("main" if k == 0 else None, None if k == 0 else d, l) for k, (l, d) in enumerate(total)],
                        team_rows={"away": [ou("main" if k == 0 else None, None if k == 0 else d, l) for k, (l, d) in enumerate(away)],
                                   "home": [ou("main" if k == 0 else None, None if k == 0 else d, l) for k, (l, d) in enumerate(home)]}, now=NOW - 7200)
def active(market_lines): return [l for l in market_lines if l.get("active", True)]
def vals(lines, key="line"): return [l[key] for l in active(lines)]
def mk(): return entry()["markets"]
def tt(side): return mk()[ps.TEAM_TOTALS][side]["lines"]
def unique(lines, key="line"): v = vals(lines, key); return len(v) == len(set(v))
def main_of(lines, key="line"): return next(l[key] for l in active(lines) if l["id"] == "main")
def removed_auto(lines, v, key="line"): return any(l.get("active") is False and l[key] == v and l["revisions"][-1]["action"] == "removed" and l["revisions"][-1].get("source") == "auto" for l in lines)

P = bi.parse_event(RAW["data"], H, A)
# Betano jetzt: Spread-Hauptlinie -2,5 | Total 218,5 | Thunder 108,5 | Rockets 110,5
THUNDER_LOW = [(l, "lower") for l in (104.5, 105.5, 106.5)]
THUNDER_HIGH = [(l, "higher") for l in (109.5, 110.5, 111.5)]

# (a)+(g) Fall Thunder aus der Rohantwort, alle drei Maerkte, beide Teams: Hauptlinie wandert auf eine gespeicherte auto-Zusatzlinie
setup()
seed([-3.5, -5.5, -4.5, -2.5, -1.5], [(217.5, None), (214.5, "lower"), (215.5, "lower"), (216.5, "lower"), (218.5, "higher"), (219.5, "higher"), (220.5, "higher")],
     [(107.5, None), (104.5, "lower"), (105.5, "lower"), (106.5, "lower"), (108.5, "higher"), (109.5, "higher"), (110.5, "higher")],
     [(109.5, None), (106.5, "lower"), (107.5, "lower"), (108.5, "lower"), (110.5, "higher"), (111.5, "higher"), (112.5, "higher")])
try:
    ps.save_auto("2026-10-31", START, H, A, team_rows={"away": [ou("main", None, 108.5), ou(None, "higher", 108.5)]}, now=NOW)
    check("0 Ausgangslage: die Pruefung lehnt die doppelte Linie weiter ab (ohne Entfernen)", False)
except ps.CardInputError as e:
    check("0 Ausgangslage: die Pruefung lehnt die doppelte Linie weiter ab (ohne Entfernen)", "mehrfach" in str(e))
before_rev = json.dumps(entry()["markets"]["total"], sort_keys=True)
r = run(RAW["data"] and {"data": RAW["data"]})
log1 = logtext()
check("a Thunder: Spiel gespeichert, Lauf OK, kein Fehler", r["result"] == "OK" and list(r["games"].values()) == ["saved"] and r["games"] and "0 Fehler" in r["detail"], str(r))
check("a Thunder: Hauptzeile 108,5 mit aktuellen Quoten, jede Linie nur einmal", main_of(tt("away")) == 108.5 and unique(tt("away")) and
      [l for l in active(tt("away")) if l["id"] == "main"][0]["over_odds"] == P["team"]["away"]["lines"][108.5][0])
check("a Thunder: alte Zusatzlinie x4 (108,5) als auto entfernt, Revision nachvollziehbar", removed_auto(tt("away"), 108.5))
want = lambda side: sorted(ba.bi.AutoAnswers._team_extras(type("o", (), {"d": P})(), side) + [P["team"][side]["main"]])
check("a Thunder: Leiter stimmt mit Betano ueberein (Hauptlinie + je 3 Linien)", sorted(vals(tt("away"))) == want("away"), f"{sorted(vals(tt('away')))} {want('away')}")
check("g Rockets (Heim): Hauptlinie 110,5 = Betano, Leiter stimmt, keine Doppelung", main_of(tt("home")) == 110.5 and unique(tt("home")) and sorted(vals(tt("home"))) == want("home") and removed_auto(tt("home"), 110.5))
check("g Spread: Hauptlinie -2,5 = Betano, keine Doppelung, alte Zeile -2,5 entfernt", main_of(mk()[ps.SPREAD]["lines"], "line_home") == -2.5 and unique(mk()[ps.SPREAD]["lines"], "line_home") and removed_auto(mk()[ps.SPREAD]["lines"], -2.5, "line_home"))
check("g Total: Hauptlinie 218,5 = Betano, keine Doppelung, alte Zeile 218,5 entfernt", main_of(mk()[ps.TOTAL]["lines"]) == 218.5 and unique(mk()[ps.TOTAL]["lines"]) and removed_auto(mk()[ps.TOTAL]["lines"], 218.5))
allrev = [x for x in ps._all_revisions(entry())]
check("a alle Revisionen tragen source=auto (nichts von der Hand)", allrev and all(x.get("source") == "auto" for x in allrev))
# (e) Folgelauf
snap = json.dumps(ps.load(), sort_keys=True)
r = run(RAW)
check("e Folgelauf mit gleichen Daten: unveraendert, Datei byte-gleich, OK", list(r["games"].values()) == ["unchanged"] and r["result"] == "OK" and json.dumps(ps.load(), sort_keys=True) == snap, str(r))

# (b) Hauptlinie wandert um mehr als 1 und die Richtung wechselt: gespeichert Hauptlinie 105,5 mit hoeheren 106,5/107,5/108,5, Betano jetzt 108,5
setup()
seed([-3.5], [(218.5, None)], [(105.5, None), (102.5, "lower"), (103.5, "lower"), (104.5, "lower"), (106.5, "higher"), (107.5, "higher"), (108.5, "higher")], [(110.5, None)])
r = run(RAW)
check("b Hauptlinie 105,5 -> 108,5 (Richtungswechsel 106,5/107,5): gespeichert, OK", r["result"] == "OK" and list(r["games"].values()) == ["saved"], str(r))
check("b Richtungen stimmen (106,5 und 107,5 jetzt lower), keine Doppelung, Leiter = Betano", unique(tt("away")) and main_of(tt("away")) == 108.5 and sorted(vals(tt("away"))) == want("away")
      and all(l["direction"] == "lower" for l in active(tt("away")) if l["line"] in (106.5, 107.5)), f"{sorted(vals(tt('away')))}")
check("b alte Zeilen mit falscher Richtung als auto entfernt", removed_auto(tt("away"), 106.5) and removed_auto(tt("away"), 107.5) and removed_auto(tt("away"), 108.5))

# (c) Zusatzlinien fallen aus dem Fenster
# c1) gespeichert: Hauptlinie 108,5 mit je 3 weit entfernten Zusatzlinien; die neue Leiter ersetzt sie (Entfernen + Neuanlegen in einem Lauf, sonst > 3 je Richtung)
setup()
seed([-2.5], [(218.5, None)], [(108.5, None), (98.5, "lower"), (99.5, "lower"), (100.5, "lower"), (116.5, "higher"), (117.5, "higher"), (118.5, "higher")], [(110.5, None)])
r = run(RAW)
check("c1 Zusatzlinien ausserhalb des Fensters: Lauf OK, alle sechs als auto entfernt, Leiter = Betano", r["result"] == "OK" and all(removed_auto(tt("away"), v) for v in (98.5, 99.5, 100.5, 116.5, 117.5, 118.5))
      and sorted(vals(tt("away"))) == want("away"), f"{r['result']} {sorted(vals(tt('away')))}")
# c2) nur Entfernen noetig (alles andere gleich): eine veraltete Zeile direkt in den (temporaeren) Speicher legen
r = run(RAW, now=NOW + 5)
data = json.loads(ps.store_path().read_text())
away = data["entries"][KEY]["markets"][ps.TEAM_TOTALS]["away"]["lines"]
away.append({"id": "x99", "role": "extra", "direction": "lower", "active": True, "line": 90.5, "over_odds": 1.1, "under_odds": 7.0, "bookmaker": "Betano", "entered_at": "x", "updated_at": "x",
             "market_suggestion": None, "revisions": [{"action": "saved", "line": 90.5, "over_odds": 1.1, "under_odds": 7.0, "bookmaker": "Betano", "saved_at": "x", "market_suggestion": None, "source": "auto"}]})
ps.store_path().write_text(json.dumps(data))
r = run(RAW, now=NOW + 10)
check("c2 nur eine veraltete auto-Zeile (90,5): Lauf OK, Zeile als auto entfernt, Rest unveraendert", r["result"] == "OK" and list(r["games"].values()) == ["saved"] and removed_auto(tt("away"), 90.5) and sorted(vals(tt("away"))) == want("away"), str(r))
snap = json.dumps(ps.load(), sort_keys=True)
r = run(RAW, now=NOW + 15)
check("c/e danach unveraendert", list(r["games"].values()) == ["unchanged"] and json.dumps(ps.load(), sort_keys=True) == snap)
# c3) veraltete Hand-Zeile wird nie entfernt
data = json.loads(ps.store_path().read_text())
data["entries"][KEY]["markets"][ps.TEAM_TOTALS]["away"]["lines"].append({"id": "x98", "role": "extra", "direction": "lower", "active": True, "line": 91.5, "over_odds": 1.1, "under_odds": 7.0, "bookmaker": "Betano",
    "entered_at": "x", "updated_at": "x", "market_suggestion": None, "revisions": [{"action": "saved", "line": 91.5, "over_odds": 1.1, "under_odds": 7.0, "bookmaker": "Betano", "saved_at": "x", "market_suggestion": None}]})
ps.store_path().write_text(json.dumps(data))
r = run(RAW, now=NOW + 20)
check("c3 veraltete Hand-Zeile (91,5) bleibt stehen, Lauf ohne Fehler", r["result"] == "OK" and 91.5 in vals(tt("away")) and not removed_auto(tt("away"), 91.5), str(r))

# (d) Hand-Zeile auf der betroffenen Linie bleibt unberuehrt; Spiel wird trotzdem gespeichert, Protokoll nennt es
setup()
seed([-3.5], [(218.5, None)], [(107.5, None), (104.5, "lower"), (105.5, "lower"), (106.5, "lower"), (108.5, "higher"), (109.5, "higher"), (110.5, "higher")], [(110.5, None)])
x4 = next(l for l in tt("away") if l["line"] == 108.5)["id"]
hand_card = ps.save_card("2026-10-31", START, H, A, team_rows={"away": [{"id": "main", "line": "107.5", "over_odds": "1.8", "under_odds": "1.91", "bookmaker": "Betano", "direction": None},
                                                                          {"id": x4, "line": "108.5", "over_odds": "1.95", "under_odds": "1.85", "bookmaker": "Betano", "direction": "higher"}]}, now=NOW + 1)
hand_line = json.dumps(next(l for l in tt("away") if l["id"] == x4), sort_keys=True)
check("d Ausgangslage: x4 hat eine Hand-Revision", ps.has_hand_revision(next(l for l in tt("away") if l["id"] == x4)))
# Hand hat die Zeile x4; Betano-Hauptlinie ist 108,5 -> Hauptzeile bleibt, 108,5 gehoert der Hand
r = run(RAW, now=NOW + 5)
check("d Hand: Lauf OK, Spiel gespeichert (Spread/Total/Rockets laufen weiter)", r["result"] == "OK" and list(r["games"].values()) == ["saved"], str(r))
check("d Hand-Zeile 108,5 byte-gleich, nicht entfernt, jede Linie nur einmal", json.dumps(next(l for l in tt("away") if l["id"] == x4), sort_keys=True) == hand_line and unique(tt("away")) and 108.5 in vals(tt("away")))
check("d Protokoll nennt 'Linie 108,5 gehört der Hand'", "Linie 108,5 gehört der Hand" in logtext(), logtext()[-300:])
check("d die Hand-Hauptlinie-Regel bleibt: Spread/Total der Automatik wurden aktualisiert", main_of(mk()[ps.SPREAD]["lines"], "line_home") == -2.5)

# (f) 3 Laeufe hintereinander mit wandernder Hauptlinie
setup()
seed([-2.5], [(218.5, None)], [(108.5, None), (105.5, "lower"), (106.5, "lower"), (107.5, "lower"), (109.5, "higher"), (110.5, "higher"), (111.5, "higher")], [(110.5, None)])
res = []
for k, hl in enumerate((109.5, 107.5, 111.5, 111.5)):
    d = variant(thunder=hl)
    r = run(d, now=NOW + 60 * (k + 1))
    P2 = bi.parse_event(d["data"], H, A)
    w = sorted(bi.AutoAnswers._team_extras(type("o", (), {"d": P2})(), "away") + [P2["team"]["away"]["main"]])
    res.append((hl, r["result"], list(r["games"].values()), main_of(tt("away")), unique(tt("away")), sorted(vals(tt("away"))) == w))
check("f 3 Laeufe mit Hauptlinie 109,5 / 107,5 / 111,5 ohne Fehler, Hauptzeile folgt Betano, Leiter stimmt, keine Doppelung",
      all(x[1] == "OK" and x[2] != ["error"] and x[3] == x[0] and x[4] and x[5] for x in res), str(res))
check("f vierter Lauf (gleiche Daten) unveraendert", res[3][2] == ["unchanged"], str(res[3]))
check("f jede Protokollzeile <= 200 Zeichen, kein Fehler im Protokoll", all(len(l.split("detail=", 1)[1]) <= 200 for l in logtext().splitlines() if "job=betano_auto" in l) and "Fehler (" not in logtext())

# Fehlergrund vollstaendig (> 200 Zeichen): Detail-Zeilen
setup()
long = "x" * 450
e = ps.CardInputError([long])
orig = ps.save_auto
ps.save_auto = lambda *a, **k: (_ for _ in ()).throw(e)
try:
    r = run(RAW)
finally:
    ps.save_auto = orig
txt = "".join(l.split("detail=", 1)[1].replace("Details: ", "") for l in logtext().splitlines() if "job=betano_auto" in l)
check("5 Fehler: Grund laenger als 200 Zeichen steht vollstaendig in Detail-Zeilen", r["result"] == "WARN" and long in txt and all(len(l.split("detail=", 1)[1]) <= 200 for l in logtext().splitlines()), str(r["result"]))

# echte Dateien
real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unveraendert (tracking, automation.log, Zustand, Sperre)", real_before == real_after, str({k: v for k, v in real_after.items() if real_before[k] != v}))
print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
