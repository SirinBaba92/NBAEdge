"""Tests fuer record_live.py (Roh-Recorder). Offline: Abruf und Uhr sind Attrappen, alles in Temp-Ordnern; kein Netz, kein caffeinate, kein Zugriff auf ~/NBAEdge_live_history.
Trockenlauf gegen die Mock-Daten (data/mock/mock_boxscore.json, mock_playbyplay.json).
Aufruf aus dem Projektordner: venv/bin/python tests/test_record_live.py"""
import gzip, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import record_live as rl
from engine import game_clock as gc

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

MOCK_BOX = json.loads((ROOT / "data/mock/mock_boxscore.json").read_text())
MOCK_PBP = json.loads((ROOT / "data/mock/mock_playbyplay.json").read_text())
BOX_RAW = json.dumps({"meta": {"code": 200}, "game": MOCK_BOX}).encode()
PBP_RAW = json.dumps({"meta": {"code": 200}, "game": {"gameId": "x", "actions": MOCK_PBP}}).encode()
T0 = datetime(2026, 10, 22, 23, 0, 0, tzinfo=timezone.utc).timestamp()      # 01:00 Uhr deutscher Zeit

def team(city, name, tri, score=0, periods=()):
    return {"teamCity": city, "teamName": name, "teamTricode": tri, "score": score, "periods": list(periods)}

def row(gid, status, period, clock, text="", home=("Philadelphia", "76ers", "PHI"), away=("Cleveland", "Cavaliers", "CLE"), hs=0, as_=0, et="2026-10-22T19:00:00-04:00", utc="2026-10-22T23:00:00Z"):
    return {"gameId": gid, "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": et, "gameTimeUTC": utc,
            "homeTeam": team(*home, score=hs), "awayTeam": team(*away, score=as_)}

class Net:
    """Attrappe fuer den Abruf: Antworten je URL-Typ, Zaehler, Zeit laeuft mit sleep."""
    def __init__(self):
        self.t = T0
        self.rows = []
        self.fail = None                         # FetchResult fuer ALLE Abrufe
        self.calls = []
    def now(self): return self.t
    def sleep(self, s): self.t += s
    def fetch(self, url):
        self.calls.append(url)
        if self.fail:
            return self.fail
        if "scoreboard" in url:
            raw = json.dumps({"scoreboard": {"gameDate": "2026-10-22", "games": self.rows}}).encode()
        elif "boxscore" in url:
            raw = BOX_RAW
        else:
            raw = PBP_RAW
        return rl.FetchResult(status=200, data=json.loads(raw), raw=raw)
    def kinds(self): return [("sb" if "scoreboard" in u else "box" if "boxscore" in u else "pbp") for u in self.calls]

def files(root): return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())
def lines(p): return [json.loads(l) for l in Path(p).read_text().splitlines()]

# ----------------------------------------------------------------- Pfade und Dateinamen
check("US-Spieltag aus gameEt", rl.game_day_us({"gameEt": "2026-10-22T19:00:00-04:00"}) == "2026-10-22")
check("US-Spieltag aus UTC (02:00 UTC = Vortag 22:00 ET)", rl.game_day_us({"gameTimeUTC": "2026-10-23T02:00:00Z"}) == "2026-10-22")
check("US-Spieltag Rueckfall Scoreboard-Datum", rl.game_day_us({"_scoreboard_date": "2026-10-22"}) == "2026-10-22")
os.environ.pop("NBAEDGE_LIVE_DIR", None)
check("Standardordner ausserhalb des Projekts", rl.live_root() == Path.home() / "NBAEdge_live_history" and ROOT not in rl.live_root().parents)
os.environ["NBAEDGE_LIVE_DIR"] = "/tmp/xyz_live"
check("NBAEDGE_LIVE_DIR aendert den Ordner", rl.live_root() == Path("/tmp/xyz_live"))
check("--dir schlaegt Umgebungsvariable", rl.live_root("/tmp/abc") == Path("/tmp/abc"))
os.environ.pop("NBAEDGE_LIVE_DIR")
check("Spielordner", rl.game_dir(Path("/r"), "2026-10-22", "0022600001") == Path("/r/2026-10-22/0022600001"))
check("Box-Dateiname (UTC, mit Datum, sortierbar ueber Mitternacht)", rl.box_filename(T0) == "20261022-230000.json.gz" and rl.box_filename(T0 + 3600) == "20261023-000000.json.gz")
check("Referenznummer der Sperrseite", rl.ref_from_body("Reference&#32;&#35;18&#46;6e2a3517&#46;1792682233&#46;ab12cd") == "18.6e2a3517.1792682233.ab12cd")

# ----------------------------------------------------------------- Entscheidung neu / laeuft / beendet
C = gc.from_scoreboard_game
check("vor Anpfiff -> wartet", rl.classify_game(C(row("1", 1, 0, "")), False, False) == "wartet")
check("laeuft, neu gesehen -> laeuft_neu", rl.classify_game(C(row("1", 2, 2, "PT05M00.00S")), False, False) == "laeuft_neu")
check("laeuft, schon gesehen -> laeuft", rl.classify_game(C(row("1", 2, 2, "PT05M00.00S")), True, False) == "laeuft")
check("beendet, nicht abgeschlossen -> beendet", rl.classify_game(C(row("1", 3, 4, "")), True, False) == "beendet")
check("beendet, abgeschlossen -> fertig", rl.classify_game(C(row("1", 3, 4, "")), True, True) == "fertig")

# ----------------------------------------------------------------- atomares Schreiben
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    p = td / "a" / "b.json"
    rl.write_json(p, {"x": 1})
    check("write_json atomar: Datei da, kein Temp-Rest", p.exists() and json.loads(p.read_text()) == {"x": 1} and not list(p.parent.glob(".*tmp*")))
    real = os.replace
    def boom(*a, **k): raise OSError("Platte voll")
    rl.os.replace = boom
    try:
        rl.write_json(p, {"x": 2}); raised = False
    except OSError:
        raised = True
    finally:
        rl.os.replace = real
    check("Fehler beim Ersetzen: alte Datei unveraendert, kein Temp-Rest", raised and json.loads(p.read_text()) == {"x": 1} and not list(p.parent.glob(".*tmp*")))
    rl.write_gz(td / "g.json.gz", b'{"k": 1}')
    check("write_gz: lesbar", gzip.decompress((td / "g.json.gz").read_bytes()) == b'{"k": 1}')
    rl.append_jsonl(td / "e.jsonl", {"a": 1}); rl.append_jsonl(td / "e.jsonl", {"a": 2})
    check("append_jsonl: zwei Zeilen, ganz", [r["a"] for r in lines(td / "e.jsonl")] == [1, 2])

# ----------------------------------------------------------------- Sperrdatei
with tempfile.TemporaryDirectory() as td:
    a, b = rl.InstanceLock(Path(td) / ".recorder.lock"), rl.InstanceLock(Path(td) / ".recorder.lock")
    check("erste Instanz bekommt die Sperre", a.acquire())
    check("zweite Instanz wird abgewiesen", not b.acquire())
    a.release()
    check("nach Freigabe geht es wieder", b.acquire())
    b.release()

# ----------------------------------------------------------------- Wartezeit
bo = rl.Backoff()
seq = [bo.failure() for _ in range(7)]
check("Backoff verdoppelt bis 300 s", seq == [30, 60, 120, 240, 300, 300, 300], seq)
bo.success()
check("Erfolg setzt zurueck", bo.wait == 0 and bo.failure() == 30)

# ----------------------------------------------------------------- Fehlerbehandlung beim Abruf (ohne Netz)
class R:
    def __init__(self, status, text="", payload=None):
        self.status_code, self.text, self.content, self._p = status, text, text.encode(), payload
    def json(self):
        if self._p is None: raise ValueError("kein JSON")
        return self._p
res = rl.http_fetch("u", {}, http_get=lambda u, headers=None, timeout=None: R(403, "<H1>Access Denied</H1> Reference&#32;&#35;18&#46;6e2a3517&#46;1792"))
check("403: Status und Referenznummer", res.status == 403 and res.ref == "18.6e2a3517.1792" and not res.ok)
res = rl.http_fetch("u", {}, http_get=lambda u, headers=None, timeout=None: R(200, "<html>", None))
check("200 ohne JSON = Fehler", not res.ok and "JSON" in res.error)
def timeout(u, headers=None, timeout=None): raise TimeoutError("zu langsam")
res = rl.http_fetch("u", {}, http_get=timeout)
check("Timeout = Fehler ohne Ausnahme", not res.ok and res.error == "TimeoutError" and res.status is None)

# ----------------------------------------------------------------- Trockenlauf mit Attrappen
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    root, trk = td / "live", td / "tracking"
    trk.mkdir()
    # Schnappschuss + Eingabe nur fuer Spiel 1 (Philadelphia - Cleveland)
    key = "2026-10-22|2026-10-22T23:00:00Z|Philadelphia 76ers|Cleveland Cavaliers"
    (trk / "projection_snapshots.json").write_text(json.dumps({"games": {key: {"game_date": "2026-10-22", "start_utc": "2026-10-22T23:00:00Z", "home": "Philadelphia 76ers", "away": "Cleveland Cavaliers",
        "versions": [{"hash": "alt"}, {"hash": "neu", "projection": {"exp_total": 226.5, "exp_spread": 3.1}}]}}}))
    (trk / "pre_match_entries.json").write_text(json.dumps({"entries": {key: {"markets": {"total": {"lines": []}}}}}))
    pg = td / "pregame.json"
    pg.write_text(json.dumps({"abc123": {"commence": T0, "home_team": "Philadelphia 76ers", "away_team": "Cleveland Cavaliers", "fetched_at": T0 - 600, "lines": {"total": 226.5}}}))
    model = td / "elo_model.pkl"; model.write_bytes(b"modell")
    net = Net()
    rec = rl.Recorder(root, fetch=net.fetch, now=net.now, sleep=net.sleep, log=lambda *_: None, headers={"User-Agent": "x"},
                      tracking_dir=trk, pregame_path=pg, model_path=model)
    g1, g2, g3 = "0022600001", "0022600002", "0022600003"
    net.rows = [row(g1, 2, 1, "PT11M30.00S", hs=2, as_=0),                                                                        # laeuft, gerade angepfiffen
                row(g2, 2, 3, "PT06M00.00S", home=("Oklahoma City", "Thunder", "OKC"), away=("Denver", "Nuggets", "DEN"), hs=60, as_=58, et="2026-10-22T21:30:00-04:00"),   # laeuft schon (spaet gesehen)
                row(g3, 1, 0, "", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]                                # noch nicht gestartet
    check("Durchlauf 1 meldet Erfolg", rec.cycle() is True)
    d1, d2, d3 = (root / "2026-10-22" / g for g in (g1, g2, g3))
    check("Abrufe: 1 Scoreboard + 2 Boxscores (nur laufende Spiele)", net.kinds() == ["sb", "box", "box"], net.kinds())
    check("Box-Dateien liegen als <Datum>-<hhmmss>.json.gz im Ordner box/", len(list((d1 / "box").glob("*.json.gz"))) == 1 and len(list((d2 / "box").glob("*.json.gz"))) == 1)
    box_file = next((d1 / "box").glob("*.json.gz"))
    check("Roh-Boxscore unveraendert komprimiert", gzip.decompress(box_file.read_bytes()) == BOX_RAW)
    c1, c2 = json.loads((d1 / "context.json").read_text()), json.loads((d2 / "context.json").read_text())
    check("context.json Spiel 1: Schnappschuss (letzte Version), Eingabe, Vorab-Linie, Modell-SHA, nicht spaet", c1["snapshot"]["hash"] == "neu" and c1["game_key"] == key and c1["pre_match_entry"] is not None
          and c1["pregame_lines"]["lines"]["total"] == 226.5 and c1["model"]["sha1"] and not c1["late_start"] and c1["home"] == "Philadelphia 76ers")
    check("context.json Spiel 2: laeuft schon -> late_start, kein Schnappschuss vermerkt", c2["late_start"] and c2["snapshot"] is None and any("kein Modell-Schnappschuss" in n for n in c2["notes"]))
    check("noch nicht gestartetes Spiel 3: kein context, keine Box", not (d3 / "context.json").exists() and not (d3 / "box").exists())
    ev = lines(root / "2026-10-22" / "events.jsonl")
    check("Phasen-Ereignisse im Tagesfile (Q1, Q3, PRE) mit Viertel/Uhr/Stand", {e["phase"] for e in ev if e["type"] == "phase"} == {"Q1", "Q3", "PRE"}
          and all("period" in e and "clock" in e and "score_home" in e for e in ev if e["type"] == "phase"))
    check("Herzschlag beim ersten Durchlauf", any(e["type"] == "heartbeat" and e["game_id"] is None and e["live"] == 2 and e["pre"] == 1 for e in ev))
    check("Spiel-Ereignisse auch im Spielfile", {e["type"] for e in lines(d1 / "events.jsonl")} >= {"phase", "context", "heartbeat"})

    # 30 s spaeter: noch keine neue Box; 60 s spaeter: neue Box
    net.sleep(30); net.calls.clear()
    rec.cycle()
    check("nach 30 s kein neuer Boxscore", net.kinds() == ["sb"], net.kinds())
    net.sleep(30); net.calls.clear()
    rec.cycle()
    check("nach 60 s neuer Boxscore je laufendem Spiel", net.kinds() == ["sb", "box", "box"] and len(list((d1 / "box").glob("*.json.gz"))) == 2, net.kinds())
    n_ev = len(lines(root / "2026-10-22" / "events.jsonl"))
    net.sleep(30); rec.cycle()
    check("keine doppelten Phasen-Zeilen bei unveraenderter Phase", sum(1 for e in lines(root / "2026-10-22" / "events.jsonl") if e["type"] == "phase" and e["game_id"] == g1) == 1)

    # Spiel 1 endet (Verlaengerung: 2 OT-Perioden im finalen Boxscore), Spiel 2 laeuft weiter
    net.rows[0] = row(g1, 3, 5, "PT00M00.00S", text="Final/OT", hs=118, as_=116)
    net.sleep(30); net.calls.clear()
    rec.cycle()
    check("Spielende: finaler Boxscore + komplettes Play-by-Play (je 1 Abruf), Box fuer Spiel 2", net.kinds() == ["sb", "box", "pbp", "box"], net.kinds())
    check("final_box, final_pbp und result.json geschrieben", all((d1 / n).exists() for n in ("final_box.json.gz", "final_pbp.json.gz", "result.json")))
    check("final_pbp roh und vollstaendig", len(json.loads(gzip.decompress((d1 / "final_pbp.json.gz").read_bytes()))["game"]["actions"]) == len(MOCK_PBP))
    r = json.loads((d1 / "result.json").read_text())
    check("result.json: Punkte je Viertel und Endstand aus dem Boxscore", r["home"]["final"] == MOCK_BOX["homeTeam"]["score"] and sum(r["home"]["quarters"]) == r["home"]["regulation"] and len(r["home"]["quarters"]) == 4, r["home"])
    net.sleep(60); net.calls.clear(); rec.cycle()
    check("beendetes Spiel wird nicht noch einmal abgerufen", "pbp" not in net.kinds() and net.kinds().count("box") == 1, net.kinds())

    # Verlaengerung getrennt auswerten (synthetische Perioden)
    box = {"homeTeam": team("A", "Hawks", "ATL", 118, [{"period": i, "periodType": "REGULAR", "score": 25} for i in (1, 2, 3)] + [{"period": 4, "periodType": "REGULAR", "score": 24}, {"period": 5, "periodType": "OVERTIME", "score": 12}, {"period": 6, "periodType": "OVERTIME", "score": 7}]),
           "awayTeam": team("B", "Bulls", "CHI", 116, [{"period": i, "periodType": "REGULAR", "score": 24} for i in (1, 2, 3)] + [{"period": 4, "periodType": "REGULAR", "score": 28}, {"period": 5, "periodType": "OVERTIME", "score": 9}, {"period": 6, "periodType": "OVERTIME", "score": 7}])}
    res = rl.build_result("2026-10-22", "x", box, {}, T0)
    check("Endstand getrennt: regulaer 99:100, Verlaengerung 19:16, 2 OT", res["home"]["regulation"] == 99 and res["away"]["regulation"] == 100 and res["home"]["overtime"] == 19 and res["away"]["overtime"] == 16
          and res["home"]["final"] == 118 and res["went_to_overtime"] and res["ot_count"] == 2 and res["home"]["quarters"] == [25, 25, 25, 24], res)

    # Neustart: Zustand kommt von der Festplatte (nichts wird doppelt geschrieben oder abgerufen)
    ctx_before = (d1 / "context.json").read_bytes()
    net2 = Net(); net2.t = net.t; net2.rows = [row(g1, 3, 5, "PT00M00.00S", text="Final/OT", hs=118, as_=116)]
    rec2 = rl.Recorder(root, fetch=net2.fetch, now=net2.now, sleep=net2.sleep, log=lambda *_: None, headers={}, tracking_dir=trk, pregame_path=pg, model_path=model)
    rec2.cycle()
    check("nach Neustart: beendetes Spiel nicht erneut abgerufen, context.json unveraendert", net2.kinds() == ["sb"] and (d1 / "context.json").read_bytes() == ctx_before, net2.kinds())

    # 403: Wartezeit verdoppelt sich, kein Haemmern, Fehler mit Status und Referenznummer
    net.fail = rl.FetchResult(status=403, error="HTTP 403", ref="18.6e2a3517.1792")
    net.calls.clear()
    r1 = rec.cycle(); w1 = rec.backoff.wait
    r2 = rec.cycle(); w2 = rec.backoff.wait
    r3 = rec.cycle(); w3 = rec.backoff.wait
    check("403: Durchlauf meldet Fehler, nur 1 Abruf je Durchlauf, Wartezeit 30 -> 60 -> 120", (r1, r2, r3) == (False, False, False) and net.kinds() == ["sb"] * 3 and (w1, w2, w3) == (30, 60, 120), (net.kinds(), w1, w2, w3))
    errs = [e for e in lines(root / "2026-10-22" / "events.jsonl") if e["type"] == "error"]
    check("Fehlerzeilen enthalten HTTP-Status, Referenznummer, Wartezeit und Spielstaende", errs and errs[-1]["http"] == 403 and errs[-1]["ref"] == "18.6e2a3517.1792" and errs[-1]["backoff_s"] == 120 and errs[-1]["games"])
    net.fail = None
    check("danach laeuft es weiter und die Wartezeit ist zurueckgesetzt", rec.cycle() is True and rec.backoff.wait == 0)
    # Box-Fehler mitten im Durchlauf: Abbruch der restlichen Abrufe
    net.sleep(120); net.calls.clear()
    orig = net.fetch
    def f429(url):
        if "boxscore" in url:
            net.calls.append(url)
            return rl.FetchResult(status=429, error="HTTP 429")
        return orig(url)
    net.fetch = f429
    rec.fetch = net.fetch
    okc = rec.cycle()
    check("429 beim Boxscore: Durchlauf endet nach dem ersten Fehler (kein Abruf-Sturm)", okc is False and net.kinds() == ["sb", "box"] and rec.backoff.wait == 30, net.kinds())
    net.fetch = orig; rec.fetch = orig

    # Selbstbeendigung
    net.rows[1] = row(g2, 3, 4, "", text="Final", home=("Oklahoma City", "Thunder", "OKC"), away=("Denver", "Nuggets", "DEN"), hs=120, as_=110, et="2026-10-22T21:30:00-04:00")
    net.rows[2] = row(g3, 3, 4, "", text="Final", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"), hs=100, as_=90)
    rec.backoff.success(); net.sleep(60); rec.cycle(); net.sleep(60); rec.cycle()
    check("alle Spiele beendet, aber erst kurz her: laeuft weiter", not rec.should_stop())
    net.sleep(3 * 3600 - 60); rec.cycle()
    check("alle beendet und 3 h ohne neues Spiel: beendet sich", rec.should_stop())
    net.rows.append(row("0022600099", 1, 0, "", home=("Utah", "Jazz", "UTA"), away=("Phoenix", "Suns", "PHX")))
    rec.cycle()
    check("neues Spiel erscheint: Wartezeit beginnt von vorn", not rec.should_stop())

    # nichts im Projektordner angelegt, nur im Temp-Ordner
    check("alle Dateien liegen im Zielordner, keine Temp-Reste", not [f for f in files(root) if ".tmp" in f], files(root)[:3])


# ----------------------------------------------------------------- Beenden-Regel (A): aktueller US-Spieltag, 17:00-Wechsel, Obergrenze, --bis
def berlin(y, m, d, hh, mm=0):
    from zoneinfo import ZoneInfo
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
check("US-Spieltag: 16:59 Berlin = Vortag, 17:00 = heute", rl.current_us_day(berlin(2026, 10, 23, 16, 59)) == "2026-10-22" and rl.current_us_day(berlin(2026, 10, 23, 17, 0)) == "2026-10-23")
check("US-Spieltag nachts um 01:00 Berlin = Vortag (Spiele des US-Tags laufen noch)", rl.current_us_day(berlin(2026, 10, 23, 1, 0)) == "2026-10-22")
check("US-Spieltag am Tag der Zeitumstellung (25.10., Berlin)", rl.current_us_day(berlin(2026, 10, 25, 16, 59)) == "2026-10-24" and rl.current_us_day(berlin(2026, 10, 25, 17, 0)) == "2026-10-25")
check("--bis: naechstes Vorkommen (heute, falls noch nicht erreicht)", rl.parse_until("07:00", berlin(2026, 10, 22, 18, 0)) == berlin(2026, 10, 23, 7, 0) and rl.parse_until("23:30", berlin(2026, 10, 22, 18, 0)) == berlin(2026, 10, 22, 23, 30))

def mk(now_t, rows_, until=None, root=None):
    n = Net(); n.t = now_t; n.rows = rows_
    r = rl.Recorder(Path(root), fetch=n.fetch, now=n.now, sleep=n.sleep, log=lambda *_: None, headers={}, tracking_dir=Path(root) / "trk", pregame_path=Path(root) / "pg.json", model_path=Path(root) / "m.pkl", until=until)
    return n, r
def day_row(gid, day, status, period=4, clock="", text=""):
    return row(gid, status, period, clock, text=text, et=f"{day}T19:00:00-04:00", utc=f"{day}T23:00:00Z", hs=100, as_=90)

with tempfile.TemporaryDirectory() as td:
    # Scoreboard zeigt noch den Vortag (21.10., alle beendet); es ist 18:00 Berlin am 22.10. -> aktueller Tag ist der 22.10.
    t = berlin(2026, 10, 22, 18, 0)
    n, r = mk(t, [day_row("A1", "2026-10-21", 3, text="Final"), day_row("A2", "2026-10-21", 3, text="Final")], root=td + "/a")
    r.cycle()
    check("Scoreboard zeigt noch den Vortag: kein Beenden", r.stop_reason() is None)
    n.sleep(5 * 3600); r.cycle()
    check("auch nach 5 Stunden ohne Spiel des aktuellen Tags: laeuft weiter", r.stop_reason() is None)
    # Wechsel auf den neuen Tag: neues Spiel (22.10.) laeuft
    n.t = berlin(2026, 10, 23, 1, 0); n.rows.append(day_row("B1", "2026-10-22", 2, 1, "PT10M00.00S"))
    r.cycle()
    check("Spiel des aktuellen Tags laeuft: kein Beenden", r.stop_reason() is None)
    n.rows[-1] = day_row("B1", "2026-10-22", 3, text="Final"); n.t += 3 * 3600; r.cycle()
    check("alle Spiele des Tags beendet, aber Zeitpunkt des Spielendes gerade erst: noch nicht beenden", r.stop_reason() is None)
    n.t += 3 * 3600 - 30; r.cycle()
    check("3 Stunden nach dem letzten Spielende: noch nicht ganz", r.stop_reason() is None)
    n.t += 60; r.cycle()
    check("3 Stunden ohne neues Spiel nach Spielende: Beenden mit Begruendung", r.stop_reason() and "3 Stunden" in r.stop_reason(), r.stop_reason())
    n.rows.append(day_row("B2", "2026-10-22", 1, 0, ""))
    n.t += 5; r.cycle()
    check("neues Spiel des Tags erscheint nach Fristende: weiterlaufen", r.stop_reason() is None)

with tempfile.TemporaryDirectory() as td:
    # 17:00-Wechsel: alle Spiele des 22.10. sind beendet, dann wird es 17:01 am 23.10. -> aktueller Tag = 23.10., noch kein Spiel -> weiterlaufen
    n, r = mk(berlin(2026, 10, 23, 8, 0), [day_row("C1", "2026-10-22", 3, text="Final")], root=td)
    r.cycle(); n.t = berlin(2026, 10, 23, 12, 30); r.cycle()
    check("08:00 bis 12:30: Spieltag 22.10. komplett beendet und 3 h vorbei -> Beenden erlaubt", r.stop_reason() is not None, r.stop_reason())
    n.t = berlin(2026, 10, 23, 17, 1); r.cycle()
    check("nach dem 17:00-Wechsel zaehlt der Vortag nicht mehr: weiterlaufen", r.stop_reason() is None, r.stop_reason())

with tempfile.TemporaryDirectory() as td:
    # Obergrenze 20 h: Scoreboard zeigt dauerhaft nur den Vortag
    t = berlin(2026, 10, 22, 18, 0)
    n, r = mk(t, [day_row("D1", "2026-10-21", 3, text="Final")], root=td)
    r.cycle(); n.t = t + 20 * 3600 - 60; r.cycle()
    check("kurz vor 20 h: laeuft", r.stop_reason() is None)
    n.t = t + 20 * 3600 + 1; r.cycle()
    check("nach 20 Stunden: Obergrenze beendet ihn", r.stop_reason() and "20 Stunden" in r.stop_reason(), r.stop_reason())
    r.run  # run() nutzt dieselbe Regel; Ereignis "stop" mit Grund
with tempfile.TemporaryDirectory() as td:
    # --bis: harte Endzeit auch bei laufendem Spiel
    t = berlin(2026, 10, 23, 5, 0)
    n, r = mk(t, [day_row("E1", "2026-10-22", 2, 4, "PT01M00.00S")], until=berlin(2026, 10, 23, 7, 0), root=td)
    r.cycle()
    check("--bis noch nicht erreicht: laeuft", r.stop_reason() is None)
    n.t = berlin(2026, 10, 23, 7, 0); r.cycle()
    check("--bis erreicht: beendet, auch wenn ein Spiel laeuft", r.stop_reason() == "--bis erreicht")
    # run() mit Schleife: bricht ab und schreibt ein stop-Ereignis mit Grund
    n2, r2 = mk(berlin(2026, 10, 23, 6, 59), [day_row("E1", "2026-10-22", 2, 4, "PT01M00.00S")], until=berlin(2026, 10, 23, 7, 0), root=td + "/b")
    r2.run()
    stops = [e for e in lines(Path(td) / "b" / "2026-10-22" / "events.jsonl") if e["type"] == "stop"]
    check("run(): beendet sich bei --bis und protokolliert den Grund", stops and stops[-1]["reason"] == "--bis erreicht", stops)

check("Abrufe nur NBA.com-URLs", all(u.startswith("https://cdn.nba.com/") for u in net.calls))
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
