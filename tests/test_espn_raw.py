"""Test: ESPN-Rohantwort wird je geaenderter Antwort unveraendert gespeichert (data/espn_injuries.save_raw / fetch). Ohne Netz (requests ersetzt), Temp-Ordner,
echte Daten nur per Hash/Dateiliste verglichen. Aufruf aus dem Projektordner: venv/bin/python tests/test_espn_raw.py"""
import json, os, stat, sys, tempfile, time, types, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_AUTOMATION_LOG=str(T / "automation.log"))
from data import espn_injuries as ei

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
real_dir = ROOT / "data" / "tracking"
real_before = sorted((str(p), p.stat().st_mtime_ns) for p in real_dir.rglob("*"))
raw_dir = lambda: T / "tracking" / "espn_raw"
files = lambda: sorted(raw_dir().rglob("*.json")) if raw_dir().exists() else []

def payload(comment="Out 3 weeks", ts="2026-10-30T10:00:00Z"):
    return json.dumps({"timestamp": ts, "status": "success", "injuries": [{"id": "1", "displayName": "Boston Celtics", "injuries": [
        {"id": "9", "status": "Out", "longComment": comment, "shortComment": "kurz", "athlete": {"displayName": "Jayson Tatum"}}]}]}, ensure_ascii=False).encode("utf-8")
class Resp:
    def __init__(self, b): self.content, self.status_code = b, 200
    def raise_for_status(self): pass
    def json(self): return json.loads(self.content)
ANSWER = [payload()]
fake_requests = types.SimpleNamespace(get=lambda *a, **k: Resp(ANSWER[0]))
sys.modules["requests"] = fake_requests                      # kein Netz: fetch() importiert requests erst beim Aufruf

d = ei.fetch()
check("Abruf mit gefaelschter Antwort: Ergebnis wie bisher (dict mit 'injuries'), genau eine Datei gespeichert", isinstance(d.get("injuries"), list) and len(files()) == 1, str(files()))
f1 = files()[0]
check("Pfad espn_raw/<YYYY-MM-DD>/<HHMMSS>.json, Inhalt Byte fuer Byte die Rohantwort, kein .tmp", f1.parent.parent.name == "espn_raw" and len(f1.parent.name) == 10 and len(f1.stem) == 6 and f1.read_bytes() == ANSWER[0] and not list(raw_dir().rglob("*.tmp")), str(f1))
check("Kommentartext ist in der gespeicherten Datei", "Out 3 weeks" in f1.read_text(encoding="utf-8"))
ANSWER[0] = payload(ts="2026-10-30T11:00:00Z")               # gleiche Antwort, nur neuer Abrufzeitpunkt
ei.save_raw(ANSWER[0], now=time.time() + 5)
check("zweiter Abruf mit gleicher Antwort (nur 'timestamp' anders): keine zweite Datei", len(files()) == 1, str(files()))
ANSWER[0] = payload(comment="Out 5 weeks", ts="2026-10-30T12:00:00Z")
ei.save_raw(ANSWER[0], now=time.time() + 10)
check("geaenderte Antwort (neuer Kommentar): genau eine neue Datei", len(files()) == 2 and "Out 5 weeks" in files()[-1].read_text(encoding="utf-8"), str(files()))
n = len(files()); ei.save_raw(ANSWER[0], now=time.time() + 15)
check("nochmal dieselbe Antwort: weiter 2 Dateien", len(files()) == n == 2)
# Schreibfehler: Ordner nicht beschreibbar
os.chmod(raw_dir(), stat.S_IRUSR | stat.S_IXUSR)
for d_ in raw_dir().iterdir(): os.chmod(d_, stat.S_IRUSR | stat.S_IXUSR)
err = None
try:
    r = ei.save_raw(payload(comment="Out 9 weeks"), now=time.time() + 20)
except Exception as e:
    err = e
check("Schreibfehler (Ordner nicht beschreibbar): kein Fehler nach aussen, Rueckgabe None", err is None and r is None, repr(err))
log = (T / "automation.log").read_text() if (T / "automation.log").exists() else ""
check("Schreibfehler: genau eine Protokollzeile (job=espn_raw)", log.count("job=espn_raw") == 1, log[:150])
try:
    ANSWER[0] = payload(comment="Out 9 weeks"); d = ei.fetch(); fetch_ok = isinstance(d, dict)
except Exception as e:
    fetch_ok = False
check("fetch() liefert trotz Schreibfehler die Antwort (Morgenroutine unbeeintraechtigt)", fetch_ok)
for d_ in raw_dir().iterdir(): os.chmod(d_, stat.S_IRWXU)
os.chmod(raw_dir(), stat.S_IRWXU)
check("kaputte Antwort (kein JSON): save_raw wirft nicht", ei.save_raw(b"<html>") is None)
check("echtes data/tracking weder angelegt noch veraendert", sorted((str(p), p.stat().st_mtime_ns) for p in real_dir.rglob("*")) == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
