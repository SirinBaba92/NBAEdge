"""Tests: Betano-Automatik, Kern (betano_auto.py). Offline: abgerufene Betano-Antworten kommen aus dem Mitschnitt tests/fixtures/betano_magic_hawks.har.json,
der Abruf wird durch eine Funktion ersetzt (kein Netz). Temp-Ordner fuer Tracking, Kader, Protokoll, Zustandsfile, Sperren, Recorder-Ordner.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_auto.py"""
import hashlib, json, os, sys, tempfile, urllib.error, warnings
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
from data import job_lock

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
REAL = [ROOT / "data/tracking/pre_match_entries.json", ROOT / "data/automation.log", ROOT / "data/betano_auto_state.json", ROOT / "data/betano_auto.lock", ROOT / "data/rosters.json", ROOT / "data/upcoming_cache.json"]
real_before = {str(p): sha(p) for p in REAL}

FIX = ROOT / "tests/fixtures/betano_magic_hawks.har.json"
har = json.loads(FIX.read_text())["log"]["entries"]
dtl = json.loads(har[0]["response"]["content"]["text"])
lst = json.loads(har[1]["response"]["content"]["text"])
EVENTS = [ev for b in lst["data"]["blocks"] for ev in b["events"]]
START_MS = EVENTS[0]["startTime"]
NOW = START_MS / 1000 - 6 * 3600
START = "2026-10-21T23:00:00Z"
def bdl(ev, start=START):
    h, a = [p["name"] for p in ev["participants"][:2]]
    return {"home_team": {"full_name": h}, "visitor_team": {"full_name": a}, "date": "2026-10-21", "datetime": start, "status": "scheduled"}
G1 = bdl(EVENTS[0])
M, HK = "Orlando Magic", "Atlanta Hawks"
KEY = ps.game_key("2026-10-21", START, M, HK)

class Net:
    """Ersatz fuer bi.fetch_json: zaehlt Abrufe; fail = {Teil der Adresse: Ausnahme}."""
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}
    def __call__(self, path):
        self.calls.append(path)
        for k, exc in self.fail.items():
            if k in path:
                raise exc
        return lst if "/api/sport/" in path else dtl

def http(code): return urllib.error.HTTPError("https://x.invalid/", code, "x", {}, None)
def setup():
    tmp = fresh_env()
    (tmp / "rosters.json").write_text((ROOT / "data" / "rosters.json").read_text())
    os.environ["NBAEDGE_LIVE_DIR"] = str(tmp / "live")
    (tmp / "upcoming_cache.json").write_text(json.dumps({"fetched_at": NOW, "params": {}, "games": [G1]}))      # fuer den Handimport (liest die Spiele aus dem Cache)
    return tmp
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def revs(e):
    out = []
    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                (out.extend(v) if k == "revisions" else walk(v))
        elif isinstance(n, list):
            [walk(x) for x in n]
    walk(e); return out
def run(net, games, now=NOW, **kw):
    return ba.run_once(now=now, fetch=net, sleep=lambda s: None, pause_seconds=0, games=games, **kw)
def logtext(): return alog.log_path().read_text() if alog.log_path().exists() else ""

# 1) kein Spiel in Sicht / schon begonnen / spaeter als 12 h
setup(); net = Net()
r = run(net, [bdl(EVENTS[0], "2026-10-22T14:00:00Z")])        # 15 h spaeter
check("1 Spiel erst in 15 h: Lauf uebersprungen, kein Abruf", r["result"] == "SKIP" and "kein Spiel in Sicht" in r["detail"] and not net.calls, str(r))
r = run(net, [G1], now=START_MS / 1000 + 60)                  # Spiel hat begonnen
check("1 begonnenes Spiel: nichts gespeichert, kein Abruf", r["result"] == "SKIP" and not net.calls and entry() is None)
check("1 Protokoll: job=betano_auto SKIP ohne URL", "job=betano_auto | result=SKIP | detail=Spielplan: übergeben; kein Spiel in Sicht" in logtext() and "http" not in logtext())

# 2) Speichern als auto
setup(); net = Net()
r = run(net, [G1])
e = entry()
check("2 Spiel gespeichert (saved), Lauf OK", r["result"] == "OK" and list(r["games"].values()) == ["saved"], str(r))
check("2 genau 2 Abrufe (Liste + Spiel), Spielseite mit /api/quoten/ und bt=6", len(net.calls) == 2 and net.calls[1].startswith("/api/quoten/") and net.calls[1].endswith("&bt=6"), str(net.calls))
check("2 alle Revisionen tragen source=auto", e and revs(e) and all(x.get("source") == "auto" for x in revs(e)), f"{len(revs(e or {}))}")
check("2 Zustand ok, letzter Lauf gesetzt, Zustandsfile liegt neben automation.log (nicht in tracking)",
      ba.load_state()["state"] == "ok" and ba.load_state()["last_run"] and ba.state_path().parent == alog.log_path().parent and "tracking" not in str(ba.state_path()))

# 3) zweiter Lauf mit gleichen Daten -> unchanged
before = json.dumps(ps.load(), sort_keys=True)
r = run(Net(), [G1])
check("3 zweiter Lauf: unchanged, Datei unveraendert", list(r["games"].values()) == ["unchanged"] and json.dumps(ps.load(), sort_keys=True) == before, str(r))

# 4) Handeingabe wird nicht ueberschrieben
setup()
out = []
rc = bi.main(["--datei", str(FIX)], real=lambda p: "", write=out.append, now_fn=lambda: NOW)       # Handlauf: Enter = speichern
e = entry(); hand_before = json.dumps(e, sort_keys=True)
check("4 Handimport hat gespeichert (ohne source)", e is not None and revs(e) and all("source" not in x for x in revs(e)))
dtl_alt = json.loads(json.dumps(dtl))
for col in dtl_alt["data"]["event"]["sixPackLayout"]["columns"]:        # andere Quoten bei Betano
    for s in col.get("selections", []):
        s["price"] = str(float(s["price"]) + 0.25)
class Net2(Net):
    def __call__(self, path):
        self.calls.append(path)
        return lst if "/api/sport/" in path else dtl_alt
r = run(Net2(), [G1])
check("4 Automatik nach Hand: skipped, Eintrag byte-gleich", list(r["games"].values()) == ["skipped"] and json.dumps(entry(), sort_keys=True) == hand_before, str(r))

# 5) Timeout ueberspringt nur das Spiel, Lauf geht weiter
setup()
g2 = bdl(EVENTS[1])
net = Net(fail={EVENTS[1]["url"].split("/")[2]: TimeoutError("timed out")})
r = run(net, [g2, G1])
res = list(r["games"].values())
check("5 Timeout: Spiel 1 error, Spiel 2 trotzdem saved, Lauf WARN", res == ["error", "saved"] and r["result"] == "WARN" and entry() is not None, str(r))
check("5 Zustand bleibt ok (kein Stopp)", ba.load_state()["state"] == "ok")

# 6) 429: stoppen, 6 Stunden Pause, Lauf waehrend der Pause tut nichts
setup()
S = START_MS / 1000 + 8 * 3600                                  # Anpfiff spaeter, damit das Spiel nach 6 h noch nicht begonnen hat
iso = lambda ts: __import__("datetime").datetime.fromtimestamp(ts, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
g2, G1x = bdl(EVENTS[1], iso(S)), bdl(EVENTS[0], iso(S))
T0 = S - 11 * 3600
net = Net(fail={EVENTS[1]["url"].split("/")[2]: http(429)})
r = run(net, [g2, G1x], now=T0)
st = ba.load_state()
check("6 429: Lauf gestoppt (ERROR), danach kein weiterer Abruf, Spiel 2 nicht gespeichert", r["result"] == "ERROR" and len(net.calls) == 2 and entry() is None, str(net.calls))
check("6 Zustand pause, pause_until = jetzt + 6 h", st["state"] == "pause" and abs(__import__("datetime").datetime.fromisoformat(st["pause_until"]).timestamp() - (T0 + 6 * 3600)) < 2, str(st))
net = Net()
r = run(net, [G1x], now=T0 + 3600)
check("6 Lauf in der Pause: nichts getan (kein Abruf)", r["result"] == "SKIP" and "Pause" in r["detail"] and not net.calls and entry() is None)
r = run(Net(), [G1x], now=T0 + 6 * 3600 + 5)
check("6 nach 6 h laeuft es wieder (Zustand ok)", r["result"] == "OK" and ba.load_state()["state"] == "ok", str(r))

# 7) 403: AUS bis reset
setup()
r = run(Net(fail={"/api/sport/": http(403)}), [G1])
check("7 403 auf der Spielliste: ERROR, Zustand aus", r["result"] == "ERROR" and ba.load_state()["state"] == "aus")
net = Net()
r = run(net, [G1], now=NOW + 1)
check("7 spaeter Lauf: bleibt aus, kein Abruf", r["result"] == "SKIP" and "AUS" in r["detail"] and not net.calls)
check("7 Protokoll nennt 403 und Freigabe", "HTTP 403" in logtext() and "--reset" in logtext())
ba.reset()
check("7 reset: Zustand ok", ba.load_state()["state"] == "ok" and ba.load_state()["last_error"] is None)
r = run(Net(), [G1])
check("7 nach reset laeuft die Automatik wieder", r["result"] == "OK")

# 8) 3 Fehler brechen ab
setup()
gs = [bdl(EVENTS[i]) for i in (1, 2, 3, 4)] + [G1]
fail = {EVENTS[i]["url"].split("/")[2]: TimeoutError("t") for i in (1, 2, 3, 4)}
net = Net(fail=fail)
r = run(net, gs)
check("8 nach 3 Fehlern abgebrochen: ERROR, nur Liste + 3 Spielabrufe, 4. und 5. Spiel nicht abgerufen", r["result"] == "ERROR" and len(net.calls) == 4 and "3 Fehlern" in r["detail"] and entry() is None, str(net.calls))

# 9) belegte Sperren
tmp = setup(); net = Net()
lk = job_lock.FileLock(); assert lk.acquire()
r = run(net, [G1])
lk.release()
check("9 Betano-Sperre belegt (z. B. Handabruf): Lauf uebersprungen, kein Abruf", r["result"] == "SKIP" and "Sperre belegt" in r["detail"] and not net.calls)
rec = job_lock.FileLock(tmp / "live" / ".recorder.lock"); assert rec.acquire()
r = run(net, [G1])
check("9 Recorder laeuft: Lauf uebersprungen, kein Abruf", r["result"] == "SKIP" and "Recorder" in r["detail"] and not net.calls)
r = run(net, [G1], respect_recorder=False)
rec.release()
check("9 respect_recorder=False ignoriert den Recorder (Schalter)", r["result"] == "OK")
check("9 Sperre nach dem Lauf wieder frei", job_lock.FileLock().acquire())

# 10) Handabruf (betano_import live) wartet nicht blind: belegte Sperre -> klare Meldung
setup()
lk = job_lock.FileLock(); assert lk.acquire()
orig = job_lock.FileLock.__init__
job_lock.FileLock.__init__ = lambda self, path=None, timeout=0.0: orig(self, path, 0.0)
out = []
rc = bi.main([], real=lambda p: "", write=out.append, now_fn=lambda: NOW)
job_lock.FileLock.__init__ = orig; lk.release()
check("10 Handabruf bei belegter Sperre: Meldung, Rueckgabe 1, nichts abgerufen", rc == 1 and any("Sperrdatei belegt" in x for x in out))

# ===== Spielplan selbst holen (Schritt d)
import datetime as dt
from data import fetcher
UTC = dt.timezone.utc
Z = lambda s_: dt.datetime.fromisoformat(s_.replace("Z", "+00:00")).timestamp()
SCHED = [  # (BDL-Datum = US-Spieltag, Anpfiff UTC, Heim, Gast)
    ("2026-10-28", "2026-10-29T00:00:00Z", "Orlando Magic", "Atlanta Hawks"),
    ("2026-10-28", "2026-10-29T02:30:00Z", "Washington Wizards", "Milwaukee Bucks"),
    ("2026-10-29", "2026-10-29T23:30:00Z", "Brooklyn Nets", "Charlotte Hornets"),
    ("2026-10-29", "2026-10-30T02:00:00Z", "Miami Heat", "Minnesota Timberwolves"),
]
class Plan:
    """Ersatz fuer fetcher._get: BallDontLie-Spielplan, filtert wie die API nach start_date/end_date (US-Datum); zaehlt Abrufe; fail = Ausnahme."""
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail
    def __call__(self, endpoint, params=None, retries=5):
        self.calls.append(dict(params))
        if self.fail:
            raise self.fail
        return {"data": [{"id": i, "date": d, "datetime": s_.replace("Z", ".000Z"), "status": "scheduled", "home_team": {"full_name": h}, "visitor_team": {"full_name": a}}
                         for i, (d, s_, h, a) in enumerate(SCHED) if params["start_date"] <= d <= params["end_date"]]}
orig_get = fetcher._get
def run_sched(plan, now, **kw):
    fetcher._get = plan
    try:
        return ba.run_once(now=now, fetch=Net(), sleep=lambda s_: None, pause_seconds=0, **kw)
    finally:
        fetcher._get = orig_get
def fresh_sched_env():
    tmp = setup()
    p = Path(os.environ["NBAEDGE_UPCOMING_CACHE"])
    if p.exists(): p.unlink()
    return tmp

# a) Cache alt -> einmal neu holen; Cache frisch -> kein Abruf
fresh_sched_env()
T3 = Z("2026-10-28T16:00:00Z")                                   # 17:00 Berlin (MEZ)
plan = Plan(); r = run_sched(plan, T3)
check("d1 kein Cache: Spielplan einmal neu geholt (1 Abruf), Herkunft im Protokoll", len(plan.calls) == 1 and "Spielplan: neu geholt" in r["detail"] and "Spielplan: neu geholt" in logtext(), str(r))
check("d1 Fenster = UTC-Datum-1 bis UTC-Datum", plan.calls[0]["start_date"] == "2026-10-27" and plan.calls[0]["end_date"] == "2026-10-28", str(plan.calls))
check("d1 Cache wurde ueber die bestehende Funktion geschrieben (Fenster, fetched_at = now)", json.loads(Path(os.environ["NBAEDGE_UPCOMING_CACHE"]).read_text())["fetched_at"] == T3)
plan = Plan(); r = run_sched(plan, T3 + 3600)                    # 1 h spaeter, Cache 1 h alt (< 6 h)
check("d2 Cache frisch (1 h): kein Abruf, Herkunft Cache", not plan.calls and "Spielplan: Cache" in r["detail"], str(r))
plan = Plan(); r = run_sched(plan, T3 + 7 * 3600)                 # Cache 7 h alt
check("d3 Cache alt (7 h): einmal neu geholt", len(plan.calls) == 1 and "neu geholt" in r["detail"], str(r))

# b) Spielplan-Abruf schlaegt fehl
fresh_sched_env()
plan = Plan(fail=ConnectionError("kein Netz")); r = run_sched(plan, T3)
check("d4 Abruf scheitert (ohne Cache): SKIP mit klarer Meldung, nichts gespeichert, Zustand ok", r["result"] == "SKIP" and "Spielplan nicht verfügbar" in r["detail"] and entry() is None and ba.load_state()["state"] == "ok", str(r))
# alter Cache + Abruf scheitert -> nicht auf altem Stand weiterarbeiten
Path(os.environ["NBAEDGE_UPCOMING_CACHE"]).write_text(json.dumps({"fetched_at": T3 - 8 * 3600, "params": {"start_date": "2026-10-27", "end_date": "2026-10-28", "per_page": 100},
                                                                  "games": [{"id": 1, "date": "2026-10-28", "datetime": "2026-10-29T00:00:00.000Z", "status": "scheduled", "home_team": {"full_name": M}, "visitor_team": {"full_name": HK}}]}))
plan = Plan(fail=ConnectionError("kein Netz")); r = run_sched(plan, T3)
check("d5 alter Cache (8 h) + Abruf scheitert: SKIP 'Spielplan nicht verfügbar' (kein Stand von gestern)", r["result"] == "SKIP" and "Spielplan nicht verfügbar" in r["detail"] and entry() is None, str(r))
# 429 / 403 bei BallDontLie wie bei Betano
fresh_sched_env()
fake_net.state["bdl_status"] = 429
orig_sleep = fetcher.time.sleep; fetcher.time.sleep = lambda s_: None
try:
    fetcher._get = orig_get
    r = ba.run_once(now=T3, fetch=Net(), sleep=lambda s_: None, pause_seconds=0)
finally:
    fetcher.time.sleep = orig_sleep; fake_net.state["bdl_status"] = 200
st = ba.load_state()
check("d6 BallDontLie 429: ERROR, Pause 6 h im Zustand", r["result"] == "ERROR" and st["state"] == "pause" and abs(dt.datetime.fromisoformat(st["pause_until"]).timestamp() - (T3 + 6 * 3600)) < 2, str(st))
ba.reset(); fresh_sched_env(); fake_net.state["bdl_status"] = 403
try:
    r = ba.run_once(now=T3, fetch=Net(), sleep=lambda s_: None, pause_seconds=0)
finally:
    fake_net.state["bdl_status"] = 200
check("d7 BallDontLie 403: ERROR, Automatik aus", r["result"] == "ERROR" and ba.load_state()["state"] == "aus")
ba.reset()

# c) feste Zeiten: Mitternacht UTC, 17:00 Berlin, 02:00 Berlin
def selected(now):
    fresh_sched_env()
    plan = Plan(); fetcher._get = plan
    try:
        g_, _ = ba.get_schedule(now)
    finally:
        fetcher._get = orig_get
    return sorted(g["home"].split()[-1] for g in ba.games_in_sight(now, g_)), plan.calls[0]
names, w = selected(Z("2026-10-27T23:59:00Z"))
check("c1 23:59 UTC (00:59 Berlin): Fenster 26.-27., Spiele des 28. noch 24 h weg -> keines in Sicht", names == [] and w["end_date"] == "2026-10-27", f"{names} {w}")
names, w = selected(Z("2026-10-28T00:01:00Z"))
check("c2 00:01 UTC: Fenster wechselt auf 27.-28. (Spiele des 28. im Fenster), noch >12 h bis Anpfiff", names == [] and w["end_date"] == "2026-10-28", f"{names} {w}")
names, w = selected(T3)
check("c3 17:00 Berlin: Hawks-Spiel (8 h) und Bucks-Spiel (10,5 h) gewaehlt, Folgetag noch nicht", names == ["Magic", "Wizards"], str(names))
names, w = selected(Z("2026-10-29T01:00:00Z"))                   # 02:00 Berlin (MEZ)
check("c4 02:00 Berlin: Fenster 28.-29., Magic-Spiel begonnen (nicht gewaehlt), Wizards-Spiel in 1,5 h gewaehlt", names == ["Wizards"] and w["start_date"] == "2026-10-28" and w["end_date"] == "2026-10-29", f"{names} {w}")
names, _ = selected(Z("2026-10-29T16:00:00Z"))
check("c5 Folgetag: die Spiele des 29. (7,5 h und 10 h) sind im Fenster und gewaehlt", names == ["Heat", "Nets"], str(names))
# Eigenschaft: zu jeder halben Stunde ist jedes Spiel, das in den naechsten 12 h beginnt, im Spielplan-Fenster (nichts geht verloren)
lost, t0 = [], Z("2026-10-27T12:00:00Z")
for k in range(0, 2 * 24 * 3 * 2):
    now_k = t0 + k * 1800
    fresh_sched_env(); plan = Plan(); fetcher._get = plan
    try:
        g_, _src = ba.get_schedule(now_k)
    finally:
        fetcher._get = orig_get
    have = {(g["home_team"]["full_name"]) for g in g_}
    for d, s_, h, a in SCHED:
        if now_k < Z(s_) <= now_k + 12 * 3600 and h not in have:
            lost.append((now_k, h))
check("c6 ueber 3 Tage in 30-Minuten-Schritten geht kein Spiel im 12-h-Fenster verloren", not lost, str(lost[:3]))
# doppelt behandelt? Lauf um 16:00 Z und um 17:00 Z: zweites Mal unchanged/kein neues Speichern, ein Abruf beim ersten
fresh_sched_env(); plan = Plan()
lst_shift = json.loads(json.dumps(lst))
for b_ in lst_shift["data"]["blocks"]:
    for ev_ in b_["events"]:
        ev_["startTime"] = int(Z("2026-10-29T00:00:00Z") * 1000)
class NetShift(Net):
    def __call__(self, path):
        self.calls.append(path)
        return lst_shift if "/api/sport/" in path else dtl
fake_det = NetShift()
fetcher._get = plan
try:
    r1 = ba.run_once(now=T3, fetch=fake_det, sleep=lambda s_: None, pause_seconds=0)
    r2 = ba.run_once(now=T3 + 3600, fetch=NetShift(), sleep=lambda s_: None, pause_seconds=0)
finally:
    fetcher._get = orig_get
check("c7 zwei Laeufe nacheinander: Spielplan nur einmal geholt, Magic-Spiel beim zweiten Mal unchanged (nicht doppelt)", len(plan.calls) == 1 and r1["games"].get("Magic - Hawks") == "saved"
      and r2["games"].get("Magic - Hawks") in ("unchanged",), f"{r1['games']} {r2['games']}")

# 11) echte Dateien unberuehrt
real_after = {str(p): sha(p) for p in REAL}
check("11 echte Dateien unveraendert (tracking, automation.log, Zustand, Sperre, Kader)", real_before == real_after, str({k: (real_before[k], real_after[k]) for k in real_before if real_before[k] != real_after[k]}))

print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
