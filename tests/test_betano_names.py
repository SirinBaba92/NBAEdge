"""Tests: toleranter Namensabgleich im Betano-Import (team_split), automatische Kader-Auffrischung (rosters.ensure_fresh, betano-Start) und Datei mit uebersprungenen Namen (data/betano_skipped.py).
Ohne Netz, nur Temp-Ordner; echte Dateien in data/tracking werden nicht veraendert. Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_names.py"""
import hashlib, json, os, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_ROSTERS=str(T / "rosters.json"))
import betano_import as bi
from data import betano_skipped as sk
from data import rosters

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "data" / "tracking").glob("*") if p.is_file()} | {str(ROOT / "data/rosters.json"): hashlib.sha1((ROOT / "data/rosters.json").read_bytes()).hexdigest()}
real_before = real_files()

# ---------------------------------------------------------------- Namensabgleich
P = lambda *names: [{"person_id": i + 1, "name": n} for i, n in enumerate(names)]
roster = {"Miami Heat": P("Bam Adebayo", "Bobby Portis Jr.", "Tim Hardaway Jr.", "Same Name", "Same Name."), "New Orleans Pelicans": P("Trey Murphy III", "Zion Williamson", "Dereck Lively II")}
g = {"home": "Miami Heat", "away": "New Orleans Pelicans"}
players = {"Bobby Portis": {20: 1.5}, "Tim Hardaway": {10: 1.4}, "Trey Murphy": {15: 1.8}, "Bam Adebayo": {20: 1.3}, "Dereck Lively": {10: 1.5}, "Same Name": {5: 1.2}, "Niemand Bekannt": {5: 2.0}}
out, miss = bi.team_split(players, roster, g)
check("Zusaetze: Portis, Hardaway Jr., Murphy III, Lively II werden dem richtigen Team zugeordnet (Kader-Name wird verwendet)",
      {"Bobby Portis Jr.", "Tim Hardaway Jr.", "Bam Adebayo"} <= {n for n, _ in out["home"]} and {n for n, _ in out["away"]} == {"Trey Murphy III", "Dereck Lively II"}, out)
check("Linien bleiben dem Spieler zugeordnet", dict(out["home"])["Bobby Portis Jr."] == {20: 1.5} and dict(out["away"])["Trey Murphy III"] == {15: 1.8})
check("mehrdeutiger Name ('Same Name' passt auf zwei Spieler nur normalisiert) wird nicht geraten; exakter Treffer bleibt; Unbekannter nicht zugeordnet", "Same Name" in dict(out["home"]) and miss == ["Niemand Bekannt"], miss)
out2, miss2 = bi.team_split({"Same  Name": {5: 1.2}}, roster, g)
check("wirklich mehrdeutig ('Same  Name' normalisiert = zwei Spieler): nicht geraten, in der Liste 'nicht zugeordnet'", miss2 == ["Same  Name"] and out2 == {"home": [], "away": []})
# bisher gefundene Namen unveraendert: alle echten Kader-Namen, alte Logik gegen neue
real = json.loads((ROOT / "data" / "rosters.json").read_text(encoding="utf-8"))["teams"]
def old_split(players, rp, g):
    idx = {}
    for side in ("home", "away"):
        for p in rp.get(g[side], []):
            idx[rosters.normalize_name(p["name"])] = (side, p["name"])
    o, m = {"home": [], "away": []}, []
    for name, th in players.items():
        h = idx.get(rosters.normalize_name(name))
        (o[h[0]].append((h[1], th)) if h else m.append(name))
    return o, m
teams = sorted(real); same = True; n = 0
for i, t in enumerate(teams):
    gg = {"home": t, "away": teams[(i + 1) % len(teams)]}
    pl = {p["name"]: {10: 1.5} for t2 in (gg["home"], gg["away"]) for p in real[t2]}
    a, b = old_split(pl, real, gg), bi.team_split(pl, real, gg)
    same &= (a == b); n += len(pl)
check(f"alle {n} Kader-Namen (30 Spielpaarungen): Ergebnis identisch zur bisherigen Logik", same)

# ---------------------------------------------------------------- Kader-Alter
def write_roster(age_days):
    ts = datetime.now().astimezone() - timedelta(days=age_days)
    d = {"version": 1, "format": "nbaedge-rosters", "fetched_at": ts.isoformat(timespec="seconds"), "source": "t", "season": "2026-27", "abrufe": 1, "teams": {"Miami Heat": [{"person_id": 1, "name": "A B", "position": "", "jersey": "", "team_id": 1, "team_abbreviation": "MIA"}]}}
    (T / "rosters.json").write_text(json.dumps(d), encoding="utf-8")
calls = []
def fake_refresh(now=None, **kw):
    calls.append(1); return {"teams": {"Miami Heat": [1, 2, 3]}}
write_roster(1.0)
check("Kader juenger als 2 Tage: kein Abruf, keine Meldung", rosters.ensure_fresh(refresh_fn=fake_refresh) is None and not calls)
write_roster(3.0)
msg = rosters.ensure_fresh(refresh_fn=fake_refresh)
check("Kader aelter als 2 Tage: genau EIN Abruf, Meldung 'Kader aktualisiert (3 Spieler)'", len(calls) == 1 and msg == "Kader aktualisiert (3 Spieler)", msg)
def boom(now=None, **kw): raise rosters.RosterError("Blockade")
check("Abruf-Fehler: nur 'Kader konnte nicht aktualisiert werden', keine Ausnahme", rosters.ensure_fresh(refresh_fn=boom) == "Kader konnte nicht aktualisiert werden")
(T / "rosters.json").unlink()
calls.clear()
check("Datei fehlt: wird geholt", rosters.ensure_fresh(refresh_fn=fake_refresh) is not None and len(calls) == 1)
# betano-Lauf: Kader-Schritt nur live, vor den Betano-Abrufen, Fehler stoert nicht
order = []
bi.ei.list_games = lambda now=None, games=None: [{"home": "Miami Heat", "away": "Dallas Mavericks", "date": "2026-10-26", "start": "2026-10-26T23:00:00Z"}]
bi.fetch_json = lambda path: (order.append("betano-abruf"), {"data": {}})[1]
bi.list_events = lambda payloads: []
out = []
rc = bi.main([], write=out.append, before=lambda w: (order.append("kader"), (_ for _ in ()).throw(RuntimeError("x")))[1])
check("betano live: Kader-Schritt VOR dem ersten Betano-Abruf, Fehler -> eine Zeile, Lauf geht normal weiter", order == ["kader", "betano-abruf"] and "Kader konnte nicht aktualisiert werden" in out and rc == 2, (order, out[-2:]))
order.clear(); out.clear()
bi.load_payloads = lambda p: [{}]
rc = bi.main(["--datei", "x.json"], write=out.append, before=lambda w: order.append("kader"))
check("betano mit --datei (offline): kein Kader-Abruf", order == [] and rc == 2)
order.clear(); out.clear()
rc = bi.main([], write=out.append)
check("ohne before-Funktion (Tests/andere Aufrufer): kein Kader-Abruf", "kader" not in order)

# ---------------------------------------------------------------- Datei mit uebersprungenen Namen
K = "2026-10-26|2026-10-26T23:00:00Z|Miami Heat|Dallas Mavericks"
check("ohne Datei/Eintrag: nichts anzuzeigen", sk.caption(K) is None)
now = datetime(2026, 10, 26, 5, 44).timestamp()
sk.record(K, "Miami Heat", "Dallas Mavericks", ["Bobby Portis", "Foo Bar"], now)
e = sk.get(K)
check("Eintrag: Spieltag, Spiel, Namen, Zeitpunkt in der Datei", e["names"] == ["Bobby Portis", "Foo Bar"] and e["home"] == "Miami Heat" and e["at"] and json.loads(sk.path().read_text(encoding="utf-8"))["days"]["2026-10-26"][K]["away"] == "Dallas Mavericks")
check("Anzeige: 'Nicht zugeordnet bei Betano: Bobby Portis, Foo Bar (Stand HH:MM)'", sk.caption(K).startswith("Nicht zugeordnet bei Betano: Bobby Portis, Foo Bar (Stand "), sk.caption(K))
sk.record("2026-10-26|2026-10-27T01:00:00Z|A|B", "A", "B", ["X"], now)
sk.record(K, "Miami Heat", "Dallas Mavericks", [], now + 60)
check("neuer Lauf ueberschreibt nur den Eintrag dieses Spiels; ohne Namen keine Anzeige, andere Spiele bleiben", sk.caption(K) is None and sk.get("2026-10-26|2026-10-27T01:00:00Z|A|B")["names"] == ["X"])
sk.path().write_text("kaputt", encoding="utf-8")
try:
    sk.record(K, "A", "B", ["Y"], now); raised = False
except Exception:
    raised = True
check("defekte Datei wird nicht ueberschrieben (record wirft, Lauf faengt es ab), Anzeige faellt still aus", raised and sk.path().read_text(encoding="utf-8") == "kaputt" and sk.caption(K) is None)
check("echte Dateien (tracking, rosters.json) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
