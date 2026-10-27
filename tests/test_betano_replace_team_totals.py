"""Test: Betano-Import ersetzt die gespeicherten Team-Total-Linien eines Teams komplett, wenn Betano die Linien verschiebt (kein Abbruch 'hoechstens 3 hoehere Linien').
Offline, Temp-Ordner (fake_net.fresh_env); echte Dateien werden nicht beruehrt. Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_replace_team_totals.py"""
import hashlib, json, os, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.rosters as ro
import betano_import as bi

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
real = {n: sha(ROOT / "data" / n) for n in ("elo_model.pkl", "rosters.json", "tracking/pre_match_entries.json", "tracking/day_bets.json")}
FIX = ROOT / "tests" / "fixtures" / "betano_magic_hawks.har.json"
REAL_ROSTER = (ROOT / "data" / "rosters.json").read_text()
M, HK = "Orlando Magic", "Atlanta Hawks"
START = "2026-10-21T23:00:00Z"
NOW = 1792623600000 / 1000 - 6 * 3600
G = {"home": M, "away": HK, "date": "2026-10-21", "start": START}
KEY = ps.game_key(G["date"], START, M, HK)

tmp = fresh_env()
ro.rosters_path().write_text(REAL_ROSTER)
(tmp / "upcoming_cache.json").write_text(json.dumps({"fetched_at": NOW, "params": {}, "games": [{"home_team": {"full_name": M}, "visitor_team": {"full_name": HK}, "date": G["date"], "datetime": START, "status": "scheduled"}]}))
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def run_import(answers):
    out = []
    rc = bi.main(["--datei", str(FIX)], real=lambda p: answers.pop(0) if answers else "q", write=out.append, now_fn=lambda: NOW, after=None)
    return rc, "\n".join(out)
def tt(side): return sorted((l["line"], l["over_odds"], l["under_odds"]) for l in ps.team_total_lines(entry(), side))
def tt_main(side): return next(l["line"] for l in ps.team_total_lines(entry(), side) if l.get("id") == "main")

# Betano-Leitern (Linie -> (Over, Under)); Hauptlinie = ausgeglichenste Quoten. ALT = gespeichert, NEU = Betano jetzt (um 2 Punkte verschoben)
def ladder(main, lo, hi, base=1.80):
    return {"main": main, "lines": {round(main + k, 1): (round(base - 0.12 * k, 2), round(base + 0.12 * k, 2)) for k in range(lo, hi + 1)}}
ALT = {"home": ladder(122.5, -3, 3), "away": ladder(113.5, -3, 3)}
NEU = {"home": ladder(124.5, -3, 3, 1.85), "away": ladder(116.5, -3, 3, 1.82)}
_orig_parse = bi.parse_event
def with_team(team, shift=0.0):
    def f(data, home, away):
        r = _orig_parse(data, home, away)
        LAST['ref'] = _orig_parse(data, home, away)
        if shift:                                                      # Spread und Total des alten Stands: um 'shift' Punkte verschoben
            for m in ("spread", "total"):
                r[m] = {"main": r[m]["main"] + shift, "lines": {k + shift: v for k, v in r[m]["lines"].items()}}
        r["team"] = {s: {"main": team[s]["main"], "lines": dict(team[s]["lines"])} for s in ("home", "away")}
        return r
    return f
LAST = {}
def run_import(team, answers=None, shift=0.0):
    answers = answers if answers is not None else [""]
    out = []
    bi.parse_event = with_team(team, shift)
    try:
        rc = bi.main(["--datei", str(FIX)], real=lambda p: answers.pop(0) if answers else "q", write=out.append, now_fn=lambda: NOW, after=None)
    finally:
        bi.parse_event = _orig_parse
    return rc, "\n".join(out)
def tt(side): return sorted((l["line"], l["over_odds"], l["under_odds"]) for l in ps.team_total_lines(entry(), side))
def tt_main(side): return next(l["line"] for l in ps.team_total_lines(entry(), side) if l.get("id") == "main")
def expect(team, side): return sorted((ln, o, u) for ln, (o, u) in team[side]["lines"].items())

rc, txt = run_import(ALT, shift=2.0)
check("Ausgangslage: alter Stand (7 Linien je Team) gespeichert", rc == 0 and all(tt(s) == expect(ALT, s) and tt_main(s) == ALT[s]["main"] for s in ("home", "away")), txt[-300:])
rc, txt = run_import(NEU)
check("Betano verschiebt um 2 Punkte: kein Abbruch 'hoechstens 3', gespeichert", rc == 0 and "höchstens" not in txt and "ABBRUCH" not in txt and "Gespeichert." in txt, txt[-400:])
for side in ("home", "away"):
    check(f"{side}: gespeicherte Linien + Quoten = Betano (nicht mehr gelieferte entfernt)", tt(side) == expect(NEU, side), (tt(side), expect(NEU, side)))
    check(f"{side}: Hauptlinie kommt von Betano", tt_main(side) == NEU[side]["main"], tt_main(side))
def mk_lines(kind):
    f = ps.active_spread_lines if kind == "spread" else ps.active_total_lines
    k = "line_home" if kind == "spread" else "line"
    return sorted(l[k] for l in f(entry()))
_ref = LAST['ref']
for kind in ("spread", "total"):
    got = mk_lines(kind)
    check(f"{kind}: nach Verschiebung nur Linien aus dem aktuellen Betano-Stand, Hauptlinie von Betano", got and all(x in _ref[kind]["lines"] for x in got) and _ref[kind]["main"] in got, (got, _ref[kind]["main"]))
check("Limit 'hoechstens 3 je Richtung' bleibt bestehen", ps.MAX_TOTAL_PER_DIRECTION == 3)
check("echte Dateien unveraendert", {n: sha(ROOT / "data" / n) for n in real} == real)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
