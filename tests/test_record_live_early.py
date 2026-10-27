"""Tests: Recorder erkennt den Anpfiff ueber den Boxscore, wenn das Scoreboard das Spiel noch als PRE zeigt (Verzug ~15 Min.). Offline, Attrappen, Temp-Ordner.
Aufruf: venv/bin/python tests/test_record_live_early.py"""
import gzip, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import record_live as rl

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

START = datetime(2026, 10, 22, 23, 0, 0, tzinfo=timezone.utc).timestamp()
def team(c, n, tri, score=0): return {"teamCity": c, "teamName": n, "teamTricode": tri, "score": score, "periods": []}
def srow(status, text="", period=0, clock=""):
    return {"gameId": "G1", "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": "2026-10-22T19:00:00-04:00",
            "gameTimeUTC": "2026-10-22T23:00:00Z", "homeTeam": team("Philadelphia", "76ers", "PHI"), "awayTeam": team("Cleveland", "Cavaliers", "CLE")}
def bgame(status, period=1, clock="PT11M00.00S", hs=2, as_=0):
    return {"gameId": "G1", "gameStatus": status, "gameStatusText": "Q1" if status == 2 else "Final" if status == 3 else "7:00 pm ET", "period": period, "gameClock": clock,
            "homeTeam": team("Philadelphia", "76ers", "PHI", hs), "awayTeam": team("Cleveland", "Cavaliers", "CLE", as_)}

class Net:
    def __init__(self, t):
        self.t, self.row, self.box, self.calls = t, srow(1, "7:00 pm ET"), ("404", None), []
    def now(self): return self.t
    def sleep(self, s): self.t += s
    def fetch(self, url):
        self.calls.append(url)
        if "scoreboard" in url:
            raw = json.dumps({"scoreboard": {"gameDate": "2026-10-22", "games": [dict(self.row)]}}).encode()
            return rl.FetchResult(status=200, data=json.loads(raw), raw=raw)
        if "boxscore" in url:
            kind, g = self.box
            if kind == "404": return rl.FetchResult(status=404, error="HTTP 404")
            if kind == "403": return rl.FetchResult(status=403, error="HTTP 403")
            raw = json.dumps({"game": g}).encode()
            return rl.FetchResult(status=200, data=json.loads(raw), raw=raw)
        raw = json.dumps({"game": {"gameId": "G1", "actions": []}}).encode()
        return rl.FetchResult(status=200, data=json.loads(raw), raw=raw)
    def n(self, what): return sum(1 for u in self.calls if what in u)

def mk(t, td):
    n = Net(t)
    logs = []
    r = rl.Recorder(Path(td), fetch=n.fetch, now=n.now, sleep=n.sleep, log=logs.append, headers={"User-Agent": "x Chrome/1.0 y"},
                    tracking_dir=Path(td) / "trk", pregame_path=Path(td) / "pg.json", model_path=Path(td) / "m.pkl")
    return n, r, logs
def files(root): return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file() and p.name != "events.jsonl")
def events(root): return [json.loads(l) for p in Path(root).rglob("events.jsonl") for l in p.read_text().splitlines()]
GD = lambda td: Path(td) / "2026-10-22" / "G1"

# 1) vor der Startzeit: kein Boxscore-Abruf
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START - 600, td)
    r.cycle()
    check("vor der Startzeit: kein Boxscore-Abruf", n.n("boxscore") == 0)

# 2) Startzeit erreicht, Boxscore 404: kein Fehler, kein Eintrag, kein Backoff, hoechstens alle 30 s
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 5, td)
    ok1 = r.cycle()
    check("404 vor dem Anpfiff: Durchlauf ok, kein Backoff", ok1 and r.backoff.wait == 0)
    check("404: Boxscore wurde abgefragt", n.n("boxscore") == 1)
    n.t += 10; r.cycle()
    check("nicht oefter als alle 30 s", n.n("boxscore") == 1)
    n.t += 25; r.cycle()
    check("nach 30 s wieder", n.n("boxscore") == 2)
    check("404: keine Fehler-, Kontext- oder Phasen-Eintraege ausser PRE-Phase, keine Boxdateien", not any(e["type"] in ("error", "context") for e in events(td)) and not (GD(td) / "box").exists(), files(td))
    check("404: kein Log-Eintrag ueber Fehler", not any("FEHLER" in l for l in logs), logs)

# 3) Boxscore gameStatus 1: leise
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 5, td)
    n.box = ("200", bgame(1, 0, ""))
    r.cycle()
    check("Boxscore gameStatus 1: nichts gespeichert, kein Fehler", not (GD(td) / "box").exists() and not (GD(td) / "context.json").exists()
          and not any(e["type"] == "error" for e in events(td)))

# 4) Scoreboard PRE, Boxscore gameStatus 2 -> wird aufgezeichnet
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 5, td)
    n.box = ("200", bgame(2))
    check("Durchlauf ok", r.cycle())
    box = list((GD(td) / "box").glob("*.json.gz")) if (GD(td) / "box").exists() else []
    check("Box-Datei geschrieben", len(box) == 1, files(td))
    check("Box-Datei enthaelt den Roh-Boxscore", box and json.loads(gzip.decompress(box[0].read_bytes()))["game"]["gameStatus"] == 2)
    ctx = json.loads((GD(td) / "context.json").read_text())
    check("context.json, nicht 'late_start' (Spiel gerade erst angepfiffen)", ctx["late_start"] is False and "Spiel lief beim ersten Sehen" not in " ".join(ctx["notes"]), ctx["notes"])
    ev = events(td)
    check("Phasenwechsel ins Protokoll", any(e["type"] == "phase" and e.get("status") == 2 for e in ev))
    # naechste Durchlaeufe: Scoreboard noch PRE
    calls0 = n.n("boxscore")
    n.t += 30; r.cycle()
    check("30 s spaeter (Box noch nicht faellig): kein zweiter Abruf, keine zweite Datei", n.n("boxscore") == calls0 and len(list((GD(td) / "box").glob("*.json.gz"))) == 1)
    n.t += 30; n.box = ("200", bgame(2, 1, "PT10M00.00S", 5, 3)); r.cycle()
    check("nach 60 s: zweite Box-Datei", len(list((GD(td) / "box").glob("*.json.gz"))) == 2, files(td))
    starts = [e for e in events(td) if e["type"] == "phase" and e["game_id"] == "G1" and e["day"] == "2026-10-22" and e.get("from") is None]
    ctxs = [e for e in (json.loads(l) for l in (GD(td) / "events.jsonl").read_text().splitlines()) if e["type"] == "context"]
    check("Kontext nur einmal gemeldet", len(ctxs) == 1, ctxs)
    # Scoreboard holt auf: weiter ohne Doppelstart
    n.row = srow(2, "Q1", 1, "PT09M00.00S"); n.t += 60; r.cycle()
    ctxs = [e for e in (json.loads(l) for l in (GD(td) / "events.jsonl").read_text().splitlines()) if e["type"] == "context"]
    names = [p.name for p in (GD(td) / "box").glob("*.json.gz")]
    check("Scoreboard holt auf: weiter 1 Kontext, Box-Dateinamen eindeutig", len(ctxs) == 1 and len(names) == len(set(names)) == 3, names)
    check("Ereignis 'start'-artiger Phasenwechsel (from=None) nur einmal", sum(1 for e in (json.loads(l) for l in (GD(td) / "events.jsonl").read_text().splitlines())
          if e["type"] == "phase" and e.get("from") is None) == 1)
    # Ende: Boxscore und Scoreboard
    n.row = srow(3, "Final", 4, ""); n.t += 60; n.box = ("200", bgame(3, 4, "", 110, 105)); r.cycle(); r.cycle()
    check("Ende wie bisher: final_box, final_pbp, result", all((GD(td) / f).exists() for f in ("final_box.json.gz", "final_pbp.json.gz", "result.json")), files(td))

# 5) Recorder startet erst mitten im Spiel (Scoreboard PRE, Box: 3. Viertel) -> erkannt, 'late' stimmt
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 40 * 60, td)
    n.box = ("200", bgame(2, 2, "PT06M00.00S", 40, 38))
    r.cycle()
    ctx = json.loads((GD(td) / "context.json").read_text())
    check("Start mitten im Spiel ueber Boxscore erkannt, Box gespeichert", ctx["late_start"] is True and len(list((GD(td) / "box").glob("*.json.gz"))) == 1)
    check("Hinweis 'Spiel lief beim ersten Sehen schon' bleibt hier stehen", any("lief beim ersten Sehen" in x for x in ctx["notes"]))

# 6) echter Fehler (403) wird weiterhin gemeldet mit Backoff
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 5, td)
    n.box = ("403", None)
    res = r.cycle()
    check("403 beim Probieren: Fehler, Backoff", res is False and r.backoff.wait == 30 and any(e["type"] == "error" for e in events(td)))

# 7) Normalfall unveraendert: Scoreboard sagt live -> ein Abruf pro Minute
with tempfile.TemporaryDirectory() as td:
    n, r, logs = mk(START + 5, td)
    n.row = srow(2, "Q1", 1, "PT11M00.00S"); n.box = ("200", bgame(2))
    r.cycle(); n.t += 30; r.cycle()
    check("Scoreboard live: wie bisher, 1 Box-Abruf in 30 s", n.n("boxscore") == 1)

print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
