"""Test fuer record_live.prognosen_hinweis (Erinnerungszeile beim Start). Kein Netz, echte Dateien werden nur gelesen/nicht veraendert.
Aufruf: venv/bin/python tests/test_record_live_prognosen_hinweis.py"""
import hashlib, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import record_live as rl

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
real = [ROOT / "data" / "upcoming_cache.json"]
before = [sha(p) for p in real]

from data.game_updates import us_today
day = us_today().isoformat()
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    cache = t / "c.json"
    cache.write_text(json.dumps({"fetched_at": 1.0, "games": [{"date": day, "home_team": {"full_name": "Atlanta Hawks"}, "visitor_team": {"full_name": "Washington Wizards"}}]}))
    sd = t / "snaps"; sd.mkdir()
    os.environ["NBAEDGE_UPCOMING_CACHE"] = str(cache)
    os.environ["NBAEDGE_SNAPSHOT_DIR"] = str(sd)
    out = []
    rl.prognosen_hinweis(out.append)
    check("fehlende Prognose wird gemeldet", len(out) == 1 and "FEHLT: Wizards @ Hawks" in out[0], out)
    (sd / f"{day}.json").write_text(json.dumps({"games": {f"{day}|{day}T01:00:00Z|Atlanta Hawks|Washington Wizards": {"created_after_start": False}}}))
    out = []
    rl.prognosen_hinweis(out.append)
    check("vorhandene Prognose: '1 von 1'", len(out) == 1 and "1 von 1" in out[0], out)
    cache.write_text("{{")
    out = []
    rl.prognosen_hinweis(out.append)
    check("kaputter Zwischenspeicher: Meldung statt Absturz", len(out) == 1 and "nicht geprüft" in out[0].lower(), out)

# Fehler in der Pruefung selbst darf den Start nicht verhindern
import importlib.util as iu
orig = iu.spec_from_file_location
iu.spec_from_file_location = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaputt"))
try:
    out = []
    rl.prognosen_hinweis(out.append)
finally:
    iu.spec_from_file_location = orig
check("Fehler in der Pruefung: eine Meldung, kein Absturz", len(out) == 1 and "nicht moeglich" in out[0], out)

check("echter Zwischenspeicher unveraendert", [sha(p) for p in real] == before)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
