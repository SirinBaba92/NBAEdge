"""
Pruefskript fuer die Live-Aufzeichnungen (record_live.py). NUR LESEND: im Aufzeichnungsordner wird nichts angelegt, veraendert oder geloescht,
der Recorder wird weder beruehrt noch gestoert.

Aufruf:  venv/bin/python analysis/check_recordings.py [Spieltag JJJJ-MM-TT, Standard: der neueste]   Option: --dir <Ordner> (sonst NBAEDGE_LIVE_DIR oder ~/NBAEdge_live_history)

Je Spiel: Vollstaendigkeit (context, final_box, final_pbp, result, Boxscore-Anzahl, groesste Luecke), Ereignisse (Fehler, Pausen, Anpfiff, Ende),
Plausibilitaet (Endstand in result = letzter Boxscore = final_box; Perioden/Overtime), dazu eine Gesamtzeile je Tag und am Ende eine Ampel je Spiel.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
BOX_GAP_WARN_MIN = 6.0           # Takt 60 s, Backoff bis 300 s: laengere Luecken gelten als echte Luecke
HEARTBEAT_STALE_MIN = 12.0       # Herzschlag alle 5 Min.; aelter + kein Stopp-Ereignis = Recorder offenbar nicht aktiv
LIVE_PHASES = {"Q1", "Q2", "Q3", "Q4", "BREAK", "HALFTIME", "REGULAR_END", "OT"}
FINAL_FILES = ("final_box.json.gz", "final_pbp.json.gz", "result.json")
GREEN, YELLOW, RED, GREY = "🟢", "🟡", "🔴", "⚪"


def live_root(override: str | None = None) -> Path:
    return Path(override or os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")


# ----------------------------------------------------------------------------- Lesen
def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def read_gz_json(path: Path):
    try:
        return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
    except Exception:
        return None


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue                                  # halbe Zeile am Dateiende (Recorder schreibt gerade): ignorieren
    except OSError:
        pass
    return rows


def parse_ts(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def hhmm(dt: datetime | None) -> str:
    return dt.astimezone(BERLIN).strftime("%H:%M") if dt else "-"


def box_times(box_dir: Path) -> list[datetime]:
    out = []
    try:
        names = sorted(p.name for p in box_dir.iterdir())
    except OSError:
        return out
    for n in names:
        m = re.fullmatch(r"(\d{8})-(\d{6})\.json\.gz", n)
        if m:
            out.append(datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc))
    return out


def dir_size(path: Path) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def latest_day(root: Path) -> str | None:
    days = sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)) if root.is_dir() else []
    return days[-1] if days else None


# ----------------------------------------------------------------------------- Auswertung je Spiel
def error_label(ev: dict) -> str:
    if ev.get("http") in (403, 429):
        return str(ev["http"])
    if ev.get("http"):
        return f"HTTP {ev['http']}"
    return str(ev.get("error") or "unbekannt")


def team_scores(game: dict) -> tuple[int | None, int | None]:
    def s(side):
        v = (game.get(side) or {}).get("score")
        return int(v) if v is not None else None
    return s("homeTeam"), s("awayTeam")


def check_game(gdir: Path, now: datetime) -> dict:
    gid = gdir.name
    ev = read_jsonl(gdir / "events.jsonl")
    ctx = read_json(gdir / "context.json")
    res = read_json(gdir / "result.json")
    present = {n: (gdir / n).is_file() for n in ("context.json",) + FINAL_FILES}
    times = box_times(gdir / "box")
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    max_gap = max(gaps) if gaps else 0.0

    phases = [e for e in ev if e.get("type") == "phase"]
    last_phase = (phases[-1].get("phase") if phases else None)
    live_seen = any(e.get("phase") in LIVE_PHASES for e in phases) or bool(times)
    start = next((parse_ts(e["ts"]) for e in phases if e.get("phase") in LIVE_PHASES), None)
    end = next((parse_ts(e["ts"]) for e in ev if e.get("type") == "final"), None)
    errors = [e for e in ev if e.get("type") == "error"]
    kinds: dict[str, int] = {}
    for e in errors:
        kinds[error_label(e)] = kinds.get(error_label(e), 0) + 1
    pause_s = sum(int(e.get("backoff_s") or 0) for e in errors)

    ctx = ctx or {}
    late, after_end = bool(ctx.get("late_start")), bool(ctx.get("first_seen_after_end"))
    home = (res or {}).get("home", {}).get("tricode") or ctx.get("home_tricode") or "?"
    away = (res or {}).get("away", {}).get("tricode") or ctx.get("away_tricode") or "?"

    # Plausibilitaet
    problems: list[str] = []
    final_box = read_gz_json(gdir / "final_box.json.gz")
    fb_game = (final_box or {}).get("game") or {}
    fb_score = team_scores(fb_game)
    last_box_score = None
    if times:
        lb = read_gz_json(gdir / "box" / times[-1].strftime("%Y%m%d-%H%M%S.json.gz"))
        last_box_score = team_scores((lb or {}).get("game") or {})
    if res:
        rs = (res["home"]["final"], res["away"]["final"])
        if final_box and fb_score != rs:
            problems.append(f"Endstand result {rs[0]}:{rs[1]} ≠ final_box {fb_score[0]}:{fb_score[1]}")
        if last_box_score and None not in last_box_score and last_box_score != rs:
            problems.append(f"Endstand result {rs[0]}:{rs[1]} ≠ letzter Boxscore {last_box_score[0]}:{last_box_score[1]}")
        for side in ("home", "away"):
            r = res[side]
            if len(r["quarters"]) != 4:
                problems.append(f"{side}: {len(r['quarters'])} statt 4 Viertel")
            if r["regulation"] + r["overtime"] != r["final"]:
                problems.append(f"{side}: Viertel+OT {r['regulation'] + r['overtime']} ≠ Endstand {r['final']}")
        if res.get("went_to_overtime") != bool(res["home"]["overtime_periods"] or res["away"]["overtime_periods"]):
            problems.append("Overtime-Kennzeichen passt nicht zu den Perioden")
        if fb_game and int(fb_game.get("period") or 0) != 4 + int(res.get("ot_count") or 0):
            problems.append(f"final_box Periode {fb_game.get('period')} ≠ 4 + {res.get('ot_count')} OT")
    elif present["final_box.json.gz"] and final_box is None:
        problems.append("final_box nicht lesbar")

    # Ampel
    missing = [n for n in FINAL_FILES if not present[n]]
    if not live_seen and not any(present.values()):
        state, why = "wartet", "noch nicht gestartet"
    elif not end and not res and last_phase != "FINAL":
        state, why = "laeuft", f"läuft noch (Phase {last_phase or '?'}, {len(times)} Boxscores bisher)"
    elif missing:
        state, why = RED, "fehlt: " + ", ".join(n.split(".")[0] for n in missing)
    elif problems:
        state, why = RED, problems[0]
    elif not times and not after_end:
        state, why = RED, "keine Boxscore-Reihe aufgezeichnet"
    elif late or max_gap > BOX_GAP_WARN_MIN:
        state, why = YELLOW, ("Spiel lief beim ersten Sehen schon (Reihe beginnt später)" if late and max_gap <= BOX_GAP_WARN_MIN
                              else f"größte Boxscore-Lücke {max_gap:.1f} Min.")
    elif after_end:
        state, why = GREEN, "nachgeladen nach Spielende: Endstand, final_box und PBP vollständig, keine Live-Reihe"
    else:
        state, why = GREEN, f"alles da, {len(times)} Boxscores, größte Lücke {max_gap:.1f} Min."
    return {"id": gid, "home": home, "away": away, "present": present, "boxes": len(times), "max_gap": max_gap, "kinds": kinds,
            "errors": len(errors), "pauses": len(errors), "pause_s": pause_s, "start": start, "end": end, "problems": problems,
            "late": late, "after_end": after_end, "state": state, "why": why, "last_phase": last_phase}


# ----------------------------------------------------------------------------- Tageszeile
def pid_alive(lock: Path) -> bool | None:
    try:
        pid = int(Path(lock).read_text().split()[0])
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (OSError, ValueError, IndexError):
        return None


def check_day(root: Path, day: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ddir = root / day
    ev = read_jsonl(ddir / "events.jsonl")
    beats = [e for e in ev if e.get("type") == "heartbeat"]
    stops = [e for e in ev if e.get("type") == "stop"]
    starts = [e for e in ev if e.get("type") == "start"]
    last_beat = parse_ts(beats[-1]["ts"]) if beats else None
    last_stop = stops[-1] if stops else None
    last_start = parse_ts(starts[-1]["ts"]) if starts else None
    stop_ts = parse_ts(last_stop["ts"]) if last_stop else None
    stopped = bool(last_stop and (last_start is None or stop_ts >= last_start))
    reason = str(last_stop.get("reason")) if stopped else None
    self_ended = bool(stopped and not reason.startswith("Strg+C"))
    stale = bool(last_beat and (now - last_beat).total_seconds() / 60 > HEARTBEAT_STALE_MIN)
    successor = None                                  # spaeterer Tag, in dem der Recorder nach dem letzten Herzschlag weiterschrieb
    if last_beat:
        for later in sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name) and p.name > day):
            if any((parse_ts(e.get("ts")) or last_beat) > last_beat for e in read_jsonl(root / later / "events.jsonl")):
                successor = later
                break
    scoreboard_errors = sum(1 for e in ev if e.get("type") == "error")
    ids = {p.name for p in ddir.iterdir() if p.is_dir()} if ddir.is_dir() else set()
    for e in beats + starts:
        ids |= {str(g.get("game_id")) for g in (e.get("games") or []) if g.get("game_id")}
    games = [check_game(ddir / gid, now) for gid in sorted(ids)]
    return {"day": day, "last_beat": last_beat, "stopped": stopped, "reason": reason, "self_ended": self_ended, "stale": stale, "successor": successor,
            "restarts": max(0, len(starts) - 1), "scoreboard_errors": scoreboard_errors, "size_mb": dir_size(ddir) / 1e6 if ddir.is_dir() else 0.0,
            "pid_alive": pid_alive(root / ".recorder.lock"), "games": games, "exists": ddir.is_dir()}


# ----------------------------------------------------------------------------- Ausgabe
def render(rep: dict) -> str:
    L = [f"=== Spieltag {rep['day']} ==="]
    if rep["last_beat"] is None:
        beat = "kein Herzschlag"
    else:
        beat = f"Herzschlag bis {hhmm(rep['last_beat'])} Uhr"
    if rep["stopped"]:
        how = f"selbst beendet: {rep['reason']}" if rep["self_ended"] else f"von Hand beendet ({rep['reason']})"
    elif rep["successor"]:
        how = f"Recorder lief danach weiter (Tageswechsel, Aufzeichnung ab da unter {rep['successor']})"
    elif rep["stale"]:
        how = "KEIN Stopp-Ereignis und Herzschlag veraltet: Recorder offenbar abgestürzt oder nicht aktiv"
    else:
        how = "läuft noch" if rep["pid_alive"] is not False else "läuft laut Sperrdatei nicht mehr"
    extra = f", {rep['restarts']} Neustart(s)" if rep["restarts"] else ""
    L.append(f"Recorder: {beat}; {how}{extra}; Scoreboard-Fehler: {rep['scoreboard_errors']}; Tagesordner {rep['size_mb']:.1f} MB")
    L.append("")
    for g in rep["games"]:
        f = g["present"]
        mark = lambda k: "✓" if f[k] else "✗"
        err = (f"{g['errors']} Fehler (" + ", ".join(f"{k}: {v}" for k, v in sorted(g["kinds"].items())) + ")") if g["errors"] else "0 Fehler"
        name = f"{g['away']} @ {g['home']} ({g['id']})" if g["home"] != "?" else f"Spiel {g['id']}"
        L.append(name)
        if g["state"] == "wartet":
            L.append("  noch nicht gestartet (nur Vorspiel-Ereignisse, noch keine Dateien)")
            continue
        L.append(f"  Dateien: context {mark('context.json')}  final_box {mark('final_box.json.gz')}  final_pbp {mark('final_pbp.json.gz')}  result {mark('result.json')}"
                 f"   Boxscores: {g['boxes']}, größte Lücke {g['max_gap']:.1f} Min.")
        L.append(f"  Ereignisse: {err}, Pausen {g['pauses']} ({g['pause_s']} s); Anpfiff {hhmm(g['start']) if g['start'] else ('nicht live gesehen' if g['after_end'] else '-')}, Ende {hhmm(g['end'])}")
        L.append(f"  Plausibilität: " + ("; ".join(g["problems"]) if g["problems"] else ("in Ordnung" if f["result.json"] else "nicht prüfbar (kein result)")))
    L.append("")
    L.append("Ampel:")
    for g in rep["games"]:
        name = f"{g['away']} @ {g['home']}" if g["home"] != "?" else f"Spiel {g['id']}"
        label = {GREEN: "vollständig", YELLOW: "Lücken", RED: "unvollständig", "wartet": "noch nicht gestartet", "laeuft": "läuft noch"}[g["state"]]
        L.append(f"  {GREY if g['state'] in ('wartet', 'laeuft') else g['state']} {name}: {label}" + ("" if g["state"] == "wartet" else f" – {g['why']}"))
    if not rep["games"]:
        L.append("  keine Spiele gefunden")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prueft die Live-Aufzeichnungen (nur lesend)")
    ap.add_argument("day", nargs="?", help="Spieltag JJJJ-MM-TT (Standard: neuester)")
    ap.add_argument("--dir", help="Aufzeichnungsordner")
    args = ap.parse_args(argv)
    root = live_root(args.dir)
    day = args.day or latest_day(root)
    if not day or not (root / day).is_dir():
        print(f"Kein Aufzeichnungsordner für {day or 'irgendeinen Spieltag'} in {root}.")
        return 2
    print(render(check_day(root, day)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
