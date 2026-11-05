"""Tests: Betano-Automatik, Total-/Team-Total-Konflikt mit Hand-Linien. Belegen Hand-Linien die Leiter eines Marktes (z. B. 3 niedrigere) und wandert Betanos Hauptlinie,
wuerde die Pruefung 'hoechstens 3 niedrigere/hoehere Linien' das ganze Spiel ablehnen. Erwartet: nur dieser Markt wird uebersprungen (Hinweis 'Total uebersprungen'),
Sieger, Spread, Team Totals und Spieler werden trotzdem gespeichert, Hand-Linien bleiben unveraendert.
Offline: Betano-Antwort = vorhandene Rohantwort analysis/results/betano_rockets_thunder_roh.json (Betano jetzt: Total 218,5, Thunder 108,5, Rockets 110,5), Temp-Ordner, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_total_konflikt.py"""
import datetime as dt, hashlib, json, os, sys, warnings
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
NOW = dt.datetime(2026, 10, 31, 19, 0, tzinfo=dt.timezone.utc).timestamp()
GAME = {"home_team": {"full_name": H}, "visitor_team": {"full_name": A}, "date": "2026-10-31", "datetime": START, "status": "scheduled"}
LIST = {"data": {"blocks": [{"events": [RAW["data"]["event"]]}]}}
P = bi.parse_event(RAW["data"], H, A)

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
def run(now=NOW):
    return ba.run_once(now=now, fetch=Net(RAW), sleep=lambda s: None, pause_seconds=0, games=[GAME])
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def logtext(): return alog.log_path().read_text() if alog.log_path().exists() else ""
def ou(i, d, line, o="1.9", u="1.9"): return {"id": i, "direction": d, "line": str(line), "over_odds": o, "under_odds": u, "bookmaker": "Betano"}
def mk(): return entry()["markets"]
def tot(): return mk()[ps.TOTAL]["lines"]
def tt(side): return mk()[ps.TEAM_TOTALS][side]["lines"]
def active(lines): return [l for l in lines if l.get("active", True)]
def by_line(lines, v): return next(l for l in active(lines) if l["line"] == v)
def main_of(lines): return next(l for l in active(lines) if l["id"] == "main")
def dump(x): return json.dumps(x, sort_keys=True)

def ladder(main, low, high):
    return [(main, None)] + [(v, "lower") for v in low] + [(v, "higher") for v in high]
def rows_of(lines): return [ou("main" if k == 0 else None, d, l) for k, (l, d) in enumerate(lines)]

def seed(total, away, home):
    """Stand der Automatik (source=auto): Sieger, Spread, Total, Team Totals; Linien als (Linie, Richtung)-Listen, Hauptlinie zuerst."""
    return ps.save_auto("2026-10-31", START, H, A, winner={"home_odds": "1.5", "away_odds": "2.6", "bookmaker": "Betano"},
                        spread_rows=[{"id": "main" if k == 0 else None, "line": str(l), "home_odds": "1.9", "away_odds": "1.9", "bookmaker": "Betano"} for k, l in enumerate([-3.5, -5.5, -4.5, -2.5, -1.5])],
                        total_rows=rows_of(total), team_rows={"away": rows_of(away), "home": rows_of(home)}, now=NOW - 7200)

def make_hand(market, side, values):
    """Setzt Handrevisionen auf die Zusatzlinien mit den Linienwerten (geaenderte Quoten); die Hauptlinie bleibt unveraendert (keine Handrevision)."""
    lines = tot() if market == "total" else tt(side)
    mainl = main_of(lines)
    rows = [ou("main", None, mainl["line"], str(mainl["over_odds"]), str(mainl["under_odds"]))]
    for v in values:
        l = by_line(lines, v)
        rows.append(ou(l["id"], l["direction"], v, "1.77", "2.11"))
    kw = {"total_rows": rows} if market == "total" else {"team_rows": {side: rows}}
    ps.save_card("2026-10-31", START, H, A, now=NOW - 3600, **kw)
    lines = tot() if market == "total" else tt(side)
    assert not ps.has_hand_revision(main_of(lines)), "Hauptlinie darf keine Handrevision haben"
    assert all(ps.has_hand_revision(by_line(lines, v)) for v in values)

AWAY_OK = ladder(107.5, [104.5, 105.5, 106.5], [108.5, 109.5, 110.5])
HOME_OK = ladder(109.5, [106.5, 107.5, 108.5], [110.5, 111.5, 112.5])

def conflict_case(name, total, hand_vals):
    setup()
    seed(total, AWAY_OK, HOME_OK)
    make_hand("total", None, hand_vals)
    before_total = dump(mk()[ps.TOTAL])
    hand_before = {v: dump(by_line(tot(), v)) for v in hand_vals}
    r = run()
    check(f"{name}: Lauf ohne Fehler, Spiel gespeichert", list(r["games"].values()) == ["saved"] and "0 Fehler" in r["detail"], str(r))
    check(f"{name}: Total unveraendert (byte-gleich), Hand-Linien unveraendert", dump(mk()[ps.TOTAL]) == before_total and all(dump(by_line(tot(), v)) == hand_before[v] for v in hand_vals))
    check(f"{name}: Hinweis 'Total übersprungen' im Protokoll", "Total übersprungen" in logtext(), logtext()[-400:])
    check(f"{name}: Sieger = Betano", (mk()[ps.WINNER]["home_odds"], mk()[ps.WINNER]["away_odds"]) == P["winner"], str((mk()[ps.WINNER]["home_odds"], mk()[ps.WINNER]["away_odds"])))
    check(f"{name}: Spread-Hauptlinie = Betano (-2,5)", main_of_spread() == -2.5)
    check(f"{name}: Team Totals Gast/Heim = Betano (Hauptlinien 108,5 / 110,5)", main_of(tt("away"))["line"] == 108.5 and main_of(tt("home"))["line"] == 110.5)
    blocks = [b for b in (mk().get(ps.PLAYER_POINTS) or {}).get("players", []) if b.get("active", True)]
    check(f"{name}: Spieler gespeichert", len(blocks) > 0, str(len(blocks)))
    allrev = ps._all_revisions(mk()[ps.TOTAL])
    check(f"{name}: keine Auto-Revision im Total nach dem Lauf (nichts entfernt, nichts geaendert)", not any(x.get("source") == "auto" and x["saved_at"] >= ps.iso_now(NOW) for x in allrev))
    return r

def main_of_spread(): return next(l for l in active(mk()[ps.SPREAD]["lines"]) if l["id"] == "main")["line_home"]

# (a) 3 niedrigere Hand-Linien; Hauptlinie wandert nach oben (gespeichert 217,5 -> Betano 218,5) und nach unten (gespeichert 219,5 -> Betano 218,5)
conflict_case("a hoch", ladder(217.5, [214.5, 215.5, 216.5], [218.5, 219.5, 220.5]), [214.5, 215.5, 216.5])
conflict_case("a runter", ladder(219.5, [216.5, 217.5, 218.5], [220.5, 221.5, 222.5]), [216.5, 217.5, 218.5])
# (b) 3 hoehere Hand-Linien
conflict_case("b hoch", ladder(217.5, [214.5, 215.5, 216.5], [218.5, 219.5, 220.5]), [218.5, 219.5, 220.5])
conflict_case("b runter", ladder(219.5, [216.5, 217.5, 218.5], [220.5, 221.5, 222.5]), [220.5, 221.5, 222.5])

# (c) Konflikt nur bei Team Totals Gast (3 niedrigere Hand-Linien 104,5/105,5/106,5, Betano-Hauptlinie 108,5 statt 107,5): nur Team Totals Gast uebersprungen
setup()
seed(ladder(217.5, [214.5, 215.5, 216.5], [218.5, 219.5, 220.5]), AWAY_OK, HOME_OK)
make_hand("team", "away", [104.5, 105.5, 106.5])
before_away = dump(mk()[ps.TEAM_TOTALS]["away"])
r = run()
check("c Lauf ohne Fehler, Spiel gespeichert", list(r["games"].values()) == ["saved"] and "0 Fehler" in r["detail"], str(r))
check("c Team Totals Gast unveraendert (byte-gleich)", dump(mk()[ps.TEAM_TOTALS]["away"]) == before_away)
check("c Hinweis 'Team Totals übersprungen', kein Hinweis 'Total übersprungen'", "Team Totals übersprungen" in logtext() and "Total übersprungen" not in logtext().replace("Team Totals übersprungen", ""), logtext()[-400:])
check("c Total = Betano (Hauptlinie 218,5), Team Totals Heim = Betano (110,5), Spread, Sieger, Spieler gespeichert",
      main_of(tot())["line"] == 218.5 and main_of(tt("home"))["line"] == 110.5 and main_of_spread() == -2.5 and mk()[ps.WINNER]["home_odds"] == P["winner"][0]
      and len([b for b in (mk().get(ps.PLAYER_POINTS) or {}).get("players", []) if b.get("active", True)]) > 0)

# (d) kein Konflikt (alles auto): Verhalten wie bisher, kein Hinweis
setup()
seed(ladder(217.5, [214.5, 215.5, 216.5], [218.5, 219.5, 220.5]), AWAY_OK, HOME_OK)
r = run()
check("d kein Konflikt: gespeichert, 0 Fehler", list(r["games"].values()) == ["saved"] and "0 Fehler" in r["detail"], str(r))
want_total = sorted([218.5] + [218.5 + d for d in (-3, -2, -1, 1, 2, 3)])
check("d Total-Leiter = Betano (Hauptlinie 218,5, je 3 Linien), Team Totals und Spread = Betano", main_of(tot())["line"] == 218.5 and sorted(l["line"] for l in active(tot())) == want_total
      and main_of(tt("away"))["line"] == 108.5 and main_of(tt("home"))["line"] == 110.5 and main_of_spread() == -2.5)
check("d weder 'Total übersprungen' noch 'Team Totals übersprungen' im Protokoll", "Total übersprungen" not in logtext() and "Team Totals übersprungen" not in logtext())

# (e) Hauptlinie unveraendert (218,5): 3 niedrigere Hand-Linien = genau die Betano-Leiter, Total wird normal gespeichert (auto-Zeilen bekommen die Betano-Quoten)
setup()
seed(ladder(218.5, [215.5, 216.5, 217.5], [219.5, 220.5, 221.5]), AWAY_OK, HOME_OK)
make_hand("total", None, [215.5, 216.5, 217.5])
hand_before = {v: dump(by_line(tot(), v)) for v in (215.5, 216.5, 217.5)}
r = run()
check("e Lauf ohne Fehler, gespeichert", list(r["games"].values()) == ["saved"] and "0 Fehler" in r["detail"], str(r))
check("e Total normal gespeichert: Hauptlinie und hoehere Linien tragen die Betano-Quoten", (main_of(tot())["over_odds"], main_of(tot())["under_odds"]) == tuple(P["total"]["lines"][218.5])
      and all((by_line(tot(), v)["over_odds"], by_line(tot(), v)["under_odds"]) == tuple(P["total"]["lines"][v]) for v in (219.5, 220.5, 221.5)),
      str((main_of(tot())["over_odds"], P["total"]["lines"][218.5])))
check("e Hand-Linien byte-gleich", all(dump(by_line(tot(), v)) == hand_before[v] for v in hand_before))
check("e kein Hinweis 'Total übersprungen'", "Total übersprungen" not in logtext())

# echte Dateien
real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unveraendert (tracking, automation.log, Zustand, Sperre)", real_before == real_after, str({k: v for k, v in real_after.items() if real_before[k] != v}))
print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
