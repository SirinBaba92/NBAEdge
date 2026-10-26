"""Tests fuer den ESPN-Injury-Report (data/espn_injuries.py, absences_store.apply_auto, betano_import-Ende, Hinweis in ui/player_absence). Ohne Netz: gespeicherte ESPN-Antwort
tests/fixtures/espn_injuries.json, Temp-Ordner. Aufruf aus dem Projektordner: venv/bin/python tests/test_espn_injuries.py"""
import json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
from data import absences_store as ab
from data import espn_injuries as ei
import betano_import as bi

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
real_before = (ROOT / "data/tracking/absences.json").read_bytes() if (ROOT / "data/tracking/absences.json").exists() else None

DATA = json.loads((ROOT / "tests/fixtures/espn_injuries.json").read_text(encoding="utf-8"))
NOW = time.time()
DAY = "2026-10-27"
mk = lambda pid, name, team: {"person_id": pid, "name": name, "team": team}
INFO = {"teams": {
    "Atlanta Hawks": [mk(1, "Mouhamed Gueye", "Atlanta Hawks"), mk(2, "Jalen Johnson", "Atlanta Hawks")],
    "Brooklyn Nets": [mk(3, "Mikel Brown", "Brooklyn Nets"), mk(4, "Same Name", "Brooklyn Nets"), mk(5, "Same  Name.", "Brooklyn Nets")],
    "Dallas Mavericks": [mk(6, "Dereck Lively II", "Dallas Mavericks")],
    "Indiana Pacers": [mk(7, "TJ McConnell", "Indiana Pacers")],
}}
GAMES = [{"key": f"{DAY}|2026-10-28T00:00:00Z|Atlanta Hawks|Brooklyn Nets", "home": "Atlanta Hawks", "away": "Brooklyn Nets"},
         {"key": f"{DAY}|2026-10-28T02:00:00Z|Indiana Pacers|Dallas Mavericks", "home": "Indiana Pacers", "away": "Dallas Mavericks"}]
K1, K2 = GAMES[0]["key"], GAMES[1]["key"]

# --- Status-Zuordnung
check("Status: Out/Out For Season = fehlt", ei.classify("Out") == "out" and ei.classify("Out For Season") == "out")
check("Status: Questionable/Doubtful/Day-To-Day/Probable = fraglich", all(ei.classify(s) == "doubtful" for s in ("Questionable", "Doubtful", "Day-To-Day", "Probable")))
check("Status: unbekannt wird ignoriert", ei.classify("Suspension") is None and ei.classify(None) is None)
inj = ei.parse(DATA)
check("ESPN-Beispielantwort gelesen", len(inj) == 84 and {i["kind"] for i in inj} == {"out", "doubtful"}, len(inj))

# --- Namensabgleich
r = [mk(1, "Nikola Jokić", "x"), mk(2, "Mikel Brown", "x"), mk(3, "Same Name", "x"), mk(4, "Same Name.", "x"), mk(5, "T.J. McConnell", "x")]
check("Abgleich exakt", ei.match_player("Mikel Brown", r)["person_id"] == 2)
check("Abgleich ohne Akzente", ei.match_player("Nikola Jokic", r)["person_id"] == 1)
check("Abgleich ohne Jr./Punkte", ei.match_player("Mikel Brown Jr.", r)["person_id"] == 2 and ei.match_player("TJ McConnell", r)["person_id"] == 5)
check("Abgleich mehrdeutig/unbekannt: kein Treffer", ei.match_player("Same Name", r)["person_id"] == 3 and ei.match_player("Same  Name", r) is None and ei.match_player("Niemand Bekannt", r) is None)

# --- Zuordnung + Eintragen
assigned, unmatched = ei.assign(inj, GAMES, INFO)
a1, a2 = assigned[K1], assigned[K2]
check("Out zugeordnet (Gueye ATL, Brown Jr. BKN)", {p["person_id"] for p in a1["out"]} == {1, 3}, a1["out"])
check("Suffix/Punkte: Lively II, McConnell", {p["person_id"] for p in a2["out"]} == {6, 7})
check("nicht zugeordnet wird gelistet, nicht geraten", unmatched and all("Gueye" not in u and "Lively" not in u for u in unmatched), len(unmatched))

res = ei.run(NOW, fetch_fn=lambda: DATA, info=INFO, games=GAMES)
g = ab.get(K1)
check("Lauf ok, Eintraege mit Kennzeichnung ESPN und Zeit", res["ok"] and set(g["out"]) == {1, 3} and all(v["source"] == "espn" and v["fetched_at"] for v in g["out"].values()), res["line"])
check("Hinweis 'nicht zugeordnet' am Spiel gespeichert", g["auto"]["unmatched"] == [u for u in unmatched if u in g["auto"]["unmatched"]] and len(g["auto"]["unmatched"]) > 0)

# --- Hand-Eintraege haben Vorrang
ab.set_absences(K1, [mk(1, "Mouhamed Gueye", "Atlanta Hawks"), mk(2, "Jalen Johnson", "Atlanta Hawks")], [], now=NOW)   # Hand: Gueye bleibt, Johnson neu, Brown entfernt
g = ab.get(K1)
check("Handaenderung: bestehender Auto-Eintrag behaelt Kennzeichnung, Neuer ohne", g["out"][1].get("source") == "espn" and "source" not in g["out"][2] and 3 not in g["out"])
ab.set_absences(K1, [mk(1, "Mouhamed Gueye", "Atlanta Hawks")], [mk(2, "Jalen Johnson", "Atlanta Hawks")], now=NOW + 1)  # Johnson per Hand als fraglich
for fake in (DATA, {"injuries": [{"displayName": "Atlanta Hawks", "injuries": [{"status": "Out", "athlete": {"displayName": "Jalen Johnson"}}]},
                                  {"displayName": "Brooklyn Nets", "injuries": [{"status": "Out", "athlete": {"displayName": "Mikel Brown Jr."}}]}]}):
    ei.run(NOW + 60, fetch_fn=lambda f=fake: f, info=INFO, games=GAMES)
g = ab.get(K1)
check("Hand 'fraglich' wird nicht von ESPN 'Out' ueberschrieben", 2 in g["doubtful"] and 2 not in g["out"] and "source" not in g["doubtful"][2])
check("von Hand entfernter Auto-Eintrag (Brown) kommt nicht wieder", 3 not in g["out"])
check("Auto-Eintrag, der bei ESPN nicht mehr 'out' ist (Gueye), verschwindet", 1 not in g["out"], sorted(g["out"]))
check("Lively/McConnell im anderen Spiel nach 2. Lauf ohne Daten entfernt", not ab.get(K2)["out"])

# --- Anzeige
from ui import player_absence as pa
ei.run(NOW + 120, fetch_fn=lambda: DATA, info=INFO, games=GAMES)
lines = pa.auto_caption_lines(ab.get(K2))
check("Anzeige: 'automatisch (ESPN), Stand HH:MM'", lines and lines[0].startswith("automatisch (ESPN), Stand ") and len(lines[0].split("Stand ")[1][:5]) == 5, lines[:1])
check("Anzeige: ohne Auto-Daten nichts", pa.auto_caption_lines({"out": {}, "doubtful": {}, "auto": None}) == [])

# --- Fehler stoert Betano nicht
def boom(): raise ConnectionError("kein Netz")
res = ei.run(NOW, fetch_fn=boom, info=INFO, games=GAMES)
check("ESPN-Fehler: Zeile 'nicht erreichbar', keine Ausnahme", not res["ok"] and res["line"] == "ESPN-Verletzungen: nicht erreichbar")
check("ESPN-Fehler aendert keine Eintraege", ab.get(K2).get("auto") is not None and set(ab.get(K1)["doubtful"]) == {2})
out = []
bi.ei.list_games = lambda now=None, games=None: []
rc = bi.main([], write=out.append, after=lambda w: (_ for _ in ()).throw(RuntimeError("x")))
check("betano: ohne Spiele kein ESPN-Aufruf, Lauf normal", rc == 0 and not any("ESPN" in o for o in out))
bi.ei.list_games = lambda now=None, games=None: [{"home": "A", "away": "B", "date": "", "start": "x"}]
bi.fetch_json = lambda path: {"data": {}}
bi.list_events = lambda payloads: [{"id": 1}]
bi.match_event = lambda g, ev: None
out = []
rc = bi.main([], write=out.append, after=lambda w: (_ for _ in ()).throw(RuntimeError("x")))
check("betano: ESPN-Ausnahme am Ende -> eine Zeile, Rueckgabe 0", rc == 0 and out[-1] == "ESPN-Verletzungen: nicht erreichbar", out[-2:])
out = []
rc = bi.main([], write=out.append, after=lambda w: w("ESPN-Verletzungen: ok"))
check("betano: Aufruf nach 'Beendet'", rc == 0 and out[-2].startswith("Beendet") and out[-1] == "ESPN-Verletzungen: ok")
now_real = (ROOT / "data/tracking/absences.json").read_bytes() if (ROOT / "data/tracking/absences.json").exists() else None
check("echte absences.json unveraendert", now_real == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
