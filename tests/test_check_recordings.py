"""Tests fuer analysis/check_recordings.py. Offline, nur kuenstliche Daten in einem Temp-Ordner (nie ~/NBAEdge_live_history).
Aufruf aus dem Projektordner: venv/bin/python tests/test_check_recordings.py"""
import gzip, json, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import check_recordings as cr

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

T0 = datetime(2026, 10, 22, 23, 0, 0, tzinfo=timezone.utc)
def iso(t): return t.isoformat(timespec="seconds")
def gz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(gzip.compress(json.dumps(obj).encode()))
def jl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text("".join(json.dumps(r) + "\n" for r in rows))
def box(hs, as_, period=4): return {"game": {"period": period, "homeTeam": {"score": hs}, "awayTeam": {"score": as_}}}
def quarters(total): return (total // 4, total // 4, total // 4, total - 3 * (total // 4))
def result(hs, as_, hq=None, aq=None, hot=(), aot=()):
    hq, aq = hq or quarters(hs - sum(hot)), aq or quarters(as_ - sum(aot))
    def side(q, ot, f): return {"tricode": "HOM" if f is hs else "AWY", "quarters": list(q), "regulation": sum(q), "overtime_periods": list(ot), "overtime": sum(ot), "final": f}
    return {"home": side(hq, hot, hs), "away": side(aq, aot, as_), "went_to_overtime": bool(hot or aot), "ot_count": max(len(hot), len(aot))}

def make_game(root, day, gid, n_box=5, step_min=1.0, skip_after=None, final=(100, 98), box_score=(100, 98), res_score=(100, 98), files=True, errors=0, ctx_extra=None):
    g = root / day / gid
    ev = [{"type": "phase", "phase": "Q1", "ts": iso(T0)}]
    for i in range(errors):
        ev.append({"type": "error", "http": 403, "backoff_s": 30, "ts": iso(T0)})
    t = T0
    for i in range(n_box):
        if skip_after is not None and i == skip_after:
            t += timedelta(minutes=12)
        gz(g / "box" / (t.strftime("%Y%m%d-%H%M%S") + ".json.gz"), box(*box_score))
        t += timedelta(minutes=step_min)
    if files:
        jl(g / "events.jsonl", ev + [{"type": "final", "ts": iso(t)}])
        (g / "context.json").write_text(json.dumps({"home_tricode": "HOM", "away_tricode": "AWY", **(ctx_extra or {})}))
        gz(g / "final_box.json.gz", box(*final)); gz(g / "final_pbp.json.gz", {"game": {"actions": []}})
        (g / "result.json").write_text(json.dumps(result(*res_score)))
    else:
        jl(g / "events.jsonl", ev + [{"type": "phase", "phase": "FINAL", "ts": iso(t)}])
    return g

def state(root, day, gid): return next(g for g in cr.check_day(root, day)["games"] if g["id"] == gid)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    day = "2026-10-22"
    make_game(root, day, "G_OK", errors=2)
    make_game(root, day, "G_GAP", skip_after=2)
    make_game(root, day, "G_MISS", files=False)
    make_game(root, day, "G_SCORE", final=(101, 98))
    make_game(root, day, "G_BOXSCORE", box_score=(99, 98))
    make_game(root, day, "G_LATE", ctx_extra={"late_start": True})
    after = make_game(root, day, "G_AFTER", n_box=0, ctx_extra={"first_seen_after_end": True})
    jl(root / day / "G_PRE" / "events.jsonl", [{"type": "phase", "phase": "PRE", "ts": iso(T0)}])
    jl(root / day / "G_LIVE" / "events.jsonl", [{"type": "phase", "phase": "Q2", "ts": iso(T0)}])
    gz(root / day / "G_LIVE" / "box" / "20261022-230000.json.gz", box(10, 8, 2))
    jl(root / day / "events.jsonl", [{"type": "start", "ts": iso(T0)}, {"type": "heartbeat", "ts": iso(T0 + timedelta(minutes=5)), "games": []}])
    (root / ".recorder.lock").write_text("999999999\n")

    before = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))
    rep = cr.check_day(root, day)
    out = cr.render(rep)
    after_snap = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))
    check("nur lesend: Ordner nach der Pruefung unveraendert", before == after_snap)

    G = lambda gid: state(root, day, gid)
    check("vollstaendiges Spiel gruen", G("G_OK")["state"] == cr.GREEN, G("G_OK")["why"])
    check("Fehler gezaehlt (2 x 403)", G("G_OK")["errors"] == 2 and G("G_OK")["kinds"] == {"403": 2} and G("G_OK")["pause_s"] == 60)
    check("Boxscores gezaehlt, Luecke 1 Min.", G("G_OK")["boxes"] == 5 and abs(G("G_OK")["max_gap"] - 1.0) < 1e-6)
    check("Anpfiff und Ende erkannt", G("G_OK")["start"] is not None and G("G_OK")["end"] is not None)
    check("grosse Luecke -> gelb", G("G_GAP")["state"] == cr.YELLOW and G("G_GAP")["max_gap"] > 11, str(G("G_GAP")["max_gap"]))
    check("fehlende Endedateien -> rot", G("G_MISS")["state"] == cr.RED and "final_box" in G("G_MISS")["why"])
    check("Endstand result != final_box -> rot", G("G_SCORE")["state"] == cr.RED and "final_box" in G("G_SCORE")["why"])
    check("Endstand result != letzter Boxscore -> rot", G("G_BOXSCORE")["state"] == cr.RED and "Boxscore" in G("G_BOXSCORE")["why"])
    check("spaet gesehenes Spiel -> gelb", G("G_LATE")["state"] == cr.YELLOW)
    check("nachgeladenes Spiel ohne Reihe -> gruen", G("G_AFTER")["state"] == cr.GREEN)
    check("Spiel vor dem Anpfiff = noch nicht gestartet, kein Fehler", G("G_PRE")["state"] == "wartet")
    check("laufendes Spiel = laeuft noch", G("G_LIVE")["state"] == "laeuft")
    check("Tageszeile: Heartbeat, kein Stopp, Groesse", rep["last_beat"] is not None and not rep["stopped"] and rep["size_mb"] > 0)
    check("Ausgabe enthaelt Ampel und deutsche Begriffe", "Ampel:" in out and "vollständig" in out and "noch nicht gestartet" in out)

    # Plausibilitaet Overtime
    make_game(root, day, "G_OT", final=(110, 108), box_score=(110, 108), res_score=(110, 108))
    (root / day / "G_OT" / "result.json").write_text(json.dumps(result(110, 108, hot=(10,), aot=(8,))))
    check("Overtime ohne passende Periode in final_box -> rot", G("G_OT")["state"] == cr.RED, G("G_OT")["why"])

    # Selbst beendet
    jl(root / day / "events.jsonl", [{"type": "start", "ts": iso(T0)}, {"type": "heartbeat", "ts": iso(T0 + timedelta(minutes=5))},
                                     {"type": "stop", "reason": "alle Spiele des Spieltags beendet, 3 Stunden ohne neues Spiel", "ts": iso(T0 + timedelta(hours=4))}])
    rep = cr.check_day(root, day)
    check("selbst beendet mit Grund erkannt", rep["stopped"] and rep["self_ended"] and "3 Stunden" in rep["reason"])
    jl(root / day / "events.jsonl", [{"type": "start", "ts": iso(T0)}, {"type": "stop", "reason": "Strg+C/SIGTERM", "ts": iso(T0 + timedelta(hours=1))}])
    check("Strg+C = von Hand beendet", not cr.check_day(root, day)["self_ended"])
    jl(root / day / "events.jsonl", [{"type": "start", "ts": iso(T0)}, {"type": "heartbeat", "ts": iso(T0 + timedelta(minutes=5))}])
    check("Herzschlag veraltet ohne Stopp -> Warnung", cr.check_day(root, day, now=T0 + timedelta(hours=3))["stale"])

    check("neuester Spieltag", cr.latest_day(root) == day)
    check("main: unbekannter Tag -> Exit 2", cr.main(["1999-01-01", "--dir", tmp]) == 2)
    check("main: neuester Tag -> Exit 0", cr.main(["--dir", tmp]) == 0)

print("ALLE OK" if ok else "FEHLER")
sys.exit(0 if ok else 1)
