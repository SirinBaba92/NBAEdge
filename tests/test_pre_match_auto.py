"""Tests: Sperre zwischen Prozessen, Quelle "hand"/"auto" und Vorrang der Handeingabe in data/pre_match_store.py.
Offline, nur Temp-Ordner (NBAEDGE_TRACKING_DIR), keine echten Dateien, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_auto.py"""
import json, multiprocessing as mp, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="pm_auto_")
os.environ["NBAEDGE_TRACKING_DIR"] = TMP
import data.pre_match_store as ps

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

NOW = time.time()
START = ps.iso_now(NOW + 5 * 3600).replace("+00:00", "Z")
START = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + 5 * 3600))
H, A = "New York Knicks", "Philadelphia 76ers"
def win(h, a, b="Betano"): return {"home_odds": h, "away_odds": a, "bookmaker": b}
def srow(rid="main", line="-4,5", h="1,91", a="1,95"): return {"id": rid, "line": line, "home_odds": h, "away_odds": a, "bookmaker": "Betano"}
def entry(h=H, a=A):
    return ps.load()["entries"][ps.game_key("2026-10-20", START, h, a)]

# --- 1) Sperre zwischen Prozessen: 6 Prozesse x 5 Spiele gleichzeitig, nichts geht verloren
def worker(i):
    os.environ["NBAEDGE_TRACKING_DIR"] = TMP
    for j in range(5):
        ps.save_market("2026-10-20", START, f"Heim{i}-{j}", f"Gast{i}-{j}", ps.WINNER, "1,5", "2,5", "Betano")
procs = [mp.get_context("fork").Process(target=worker, args=(i,)) for i in range(6)]
[p.start() for p in procs]; [p.join(60) for p in procs]
d = ps.load()
check("1 Sperre: 30 Spiele aus 6 Prozessen, keins verloren", len(d["entries"]) == 30 and all(p.exitcode == 0 for p in procs), f"{len(d['entries'])}")
check("1 Sperrdatei pre_match_entries.json.lock liegt im Temp-Ordner", (Path(TMP) / "pre_match_entries.json.lock").exists())
ps.save_market("2026-10-20", START, "A", "B", ps.WINNER, "1,5", "2,5", "x")      # Wiedereintritt: save_card ruft intern _lock mehrfach
r = ps.save_card("2026-10-20", START, "A", "B", winner=win("1,6", "2,4"), now=NOW)
check("1 Wiedereintritt in derselben Sperre funktioniert", r["status"] == "saved")

# --- 2) Hand: Revisionen ohne Feld; alte Revisionen ohne Feld gelten als hand
e = entry("A", "B")
check("2 Handeingabe schreibt kein Feld source", all("source" not in r for r in e["markets"][ps.WINNER]["revisions"]))
check("2 revision_source(ohne Feld) = hand", all(ps.revision_source(r) == "hand" for r in e["markets"][ps.WINNER]["revisions"]))
check("2 has_hand_revision(alter Markt) = True", ps.has_hand_revision(e["markets"][ps.WINNER]))

# --- 3) save_auto: ohne Handeingabe gespeichert und als auto markiert
r = ps.save_auto("2026-10-20", START, H, A, winner=win("1,70", "2,20"), spread_rows=[srow()], now=NOW)
e = entry()
check("3 save_auto ohne Hand: gespeichert", r["status"] == "saved" and r["skipped_hand"] == 0, str(r["status"]))
check("3 Revisionen tragen source=auto (Sieger, Spread)", e["markets"][ps.WINNER]["revisions"][-1].get("source") == "auto"
      and e["markets"][ps.SPREAD]["lines"][0]["revisions"][-1].get("source") == "auto")
check("3 has_hand_revision(auto-Markt) = False", not ps.has_hand_revision(e["markets"][ps.WINNER]))
r2 = ps.save_auto("2026-10-20", START, H, A, winner=win("1,75", "2,15"), now=NOW + 1)
e = entry()
check("3 auto darf eigene auto-Werte aktualisieren", r2["status"] == "saved" and e["markets"][ps.WINNER]["home_odds"] == 1.75 and len(e["markets"][ps.WINNER]["revisions"]) == 2)

# --- 4) Hand ueberschreibt auto; danach hat die Hand Vorrang
ps.save_card("2026-10-20", START, H, A, winner=win("1,80", "2,10"), now=NOW + 2)
e = entry()
check("4 Hand ueberschreibt auto (Revision ohne source)", e["markets"][ps.WINNER]["home_odds"] == 1.8 and "source" not in e["markets"][ps.WINNER]["revisions"][-1])
before = json.dumps(ps.load(), sort_keys=True)
r3 = ps.save_auto("2026-10-20", START, H, A, winner=win("1,99", "1,99"), now=NOW + 3)
check("4 auto nach Hand: uebersprungen mit klarer Meldung", r3["status"] == "skipped" and r3["reason"] == "übersprungen: Handeingabe hat Vorrang", str(r3))
check("4 Datei dabei byte-gleich (nichts ueberschrieben, nichts angehaengt)", json.dumps(ps.load(), sort_keys=True) == before)

# --- 5) Mischfall: Sieger = Hand (uebersprungen), Spread-Hauptlinie nur auto (gespeichert), neue Spread-Zeile ok, Hand-Spread-Linie bleibt
ps.save_card("2026-10-20", START, "C", "D", winner=win("1,5", "2,5"), spread_rows=[srow(line="-3,5")], now=NOW)
r4 = ps.save_auto("2026-10-20", START, "C", "D", winner=win("9,0", "9,0"), spread_rows=[srow(line="-5,0", h="1,8"), srow(None, "-4,5")], now=NOW + 1)
e = entry("C", "D")
check("5 Hand-Sieger, Hand-Hauptlinie und die ganze Spread-Leiter bleiben Hand", r4["status"] == "skipped" and r4["skipped_hand"] == 3
      and e["markets"][ps.WINNER]["home_odds"] == 1.5 and len(e["markets"][ps.SPREAD]["lines"]) == 1 and e["markets"][ps.SPREAD]["lines"][0]["line_home"] == -3.5, str(r4))
ps.save_card("2026-10-20", START, "K", "L", winner=win("1,5", "2,5"), now=NOW)
r4b = ps.save_auto("2026-10-20", START, "K", "L", winner=win("9,0", "9,0"), spread_rows=[srow(line="-5,0", h="1,8")], now=NOW + 1)
e = entry("K", "L")
check("5 Mischfall: Hand-Sieger bleibt, Spread (ohne Hand) wird als auto gespeichert", r4b["status"] == "saved" and r4b["skipped_hand"] == 1
      and e["markets"][ps.WINNER]["home_odds"] == 1.5 and e["markets"][ps.SPREAD]["lines"][0]["revisions"][-1].get("source") == "auto")
# Spieler: Hand-Block wird nie angefasst
pb = lambda v: [{"block_id": None, "person_id": 77, "name": "X", "team": H, "team_abbreviation": "NYK", "mode": "milestones", "rows": [{"id": None, "value": str(v), "odds": "1,9", "bookmaker": "B"}]}]
ps.save_card("2026-10-20", START, "E", "F", player_blocks=pb(20), now=NOW)
r5 = ps.save_auto("2026-10-20", START, "E", "F", player_blocks=pb(25), now=NOW + 1)
check("5 Spielerblock mit Handeingabe: auto uebersprungen", r5["status"] == "skipped" and len(entry("E", "F")["markets"][ps.PLAYER_POINTS]["players"][0]["lines"]) == 1)
r6 = ps.save_auto("2026-10-20", START, "G", "H", player_blocks=pb(20), now=NOW)
l = entry("G", "H")["markets"][ps.PLAYER_POINTS]["players"][0]["lines"][0]
check("5 neuer Spielerblock durch auto: gespeichert mit source=auto", r6["status"] == "saved" and l["revisions"][-1].get("source") == "auto")

# --- 6) Anpfiff-Sperre gilt auch fuer auto
try:
    ps.save_auto("2026-10-20", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 3600)), "I", "J", winner=win("1,5", "2,5"), now=NOW)
    check("6 auto nach Anpfiff abgelehnt", False)
except ps.GameStartedError:
    check("6 auto nach Anpfiff abgelehnt", True)

print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
