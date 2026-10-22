"""
Roh-Recorder fuer NBA-Live-Daten (nur cdn.nba.com, keine Odds-API-Credits, keine Betano-Abrufe).

Start (Alias "aufzeichnen") oder:  venv/bin/python record_live.py          Beenden: Strg+C (sauber) oder  pkill -f record_live.py
Optionen:  --einmal (ein Durchlauf, dann Ende)   --dir <Ordner> (statt NBAEDGE_LIVE_DIR)   --ohne-caffeinate
           --bis HH:MM (harte Endzeit in deutscher Zeit; naechstes Vorkommen dieser Uhrzeit)

Ablage (ausserhalb des Projekts, damit Ordner-Backups sie nicht mitnehmen):
  <NBAEDGE_LIVE_DIR oder ~/NBAEdge_live_history>/<US-Spieltag>/<game_id>/
      context.json            einmal beim ersten Sehen eines laufenden/beendeten Spiels: Modell-Schnappschuss, Hauptlinien, Modell-SHA, Heim/Gast
      box/<JJJJMMTT>-<hhmmss>.json.gz   Roh-Boxscore etwa jede Minute (Zeit in UTC; Datum im Namen, damit es ueber Mitternacht sortiert)
      final_box.json.gz, final_pbp.json.gz, result.json   einmal nach Spielende (Endstand regulaer/Verlaengerung getrennt, Punkte je Viertel)
      events.jsonl            Phasenwechsel, Fehler (HTTP-Status, Referenznummer der Sperrseite, Timeout), Herzschlag alle 5 Min.
  <...>/<US-Spieltag>/events.jsonl   dasselbe fuer den ganzen Tag (plus Start/Stopp und Scoreboard-Fehler)
  <...>/.recorder.lock               Sperrdatei: eine zweite Instanz startet nicht

Regeln: Scoreboard alle 30 s, Boxscore je laufendem Spiel etwa jede Minute; bei 403/429/Timeout wird die Wartezeit verdoppelt (30 -> 60 -> ... max. 300 s),
pro Durchlauf bricht der erste Fehler die weiteren Abrufe ab. Spiele, die schon laufen, werden sofort aufgezeichnet (Play-by-Play ist am Ende vollstaendig).
Beendet sich selbst NUR, wenn (1) mindestens ein Spiel des aktuellen US-Spieltags gesehen wurde, (2) alle bekannten Spiele dieses Spieltags beendet sind und
(3) danach 3 Stunden lang kein neues Spiel erschien. Der aktuelle US-Spieltag wechselt um 17:00 Uhr deutscher Zeit; zeigt das Scoreboard noch den Vortag, laeuft er weiter,
hoechstens 20 Stunden (Obergrenze) bzw. bis --bis. Alle Dateien werden ueber Temp-Datei + os.replace geschrieben.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from data.nba_headers import nba_headers                     # noqa: E402
from data.nba_live import NBA_BOXSCORE_URL, NBA_PLAYBYPLAY_URL, NBA_SCOREBOARD_URL   # noqa: E402
from engine import game_clock as gc                           # noqa: E402

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
DAY_SWITCH_HOUR = 17             # um 17:00 Uhr deutscher Zeit beginnt der naechste US-Spieltag
MAX_RUNTIME_SECONDS = 20 * 3600  # Obergrenze der Laufzeit
POLL_SECONDS = 30
BOX_SECONDS = 60
BOX_TOLERANCE = 5                 # Boxscore gilt ab 55 s als faellig (Takt 30 s)
HEARTBEAT_SECONDS = 300
BACKOFF_START, BACKOFF_MAX = 30, 300
IDLE_EXIT_SECONDS = 3 * 3600
REQUEST_GAP_SECONDS = 1.5         # Mindestabstand zwischen zwei Abrufen
TIMEOUT_SECONDS = 10
DEDUPE_SECONDS = 300              # identische Ereigniszeile frueher nicht noch einmal schreiben
LIVE_VERSION = 1


# ----------------------------------------------------------------------------- Pfade und Dateien
def live_root(override: str | None = None) -> Path:
    return Path(override or os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")


def game_day_us(game: dict) -> str:
    """US-Spieltag (Ostkueste) aus gameEt, sonst aus gameTimeUTC, sonst aus gameDate des Scoreboards."""
    et = str(game.get("gameEt") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", et):
        return et[:10]
    try:
        dt = datetime.fromisoformat(str(game.get("gameTimeUTC")).replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    except ValueError:
        return str(game.get("_scoreboard_date") or "unbekannt")


def current_us_day(t: float) -> str:
    """Aktueller US-Spieltag nach dem 17:00-Wechsel in Berliner Zeit: ab 17:00 gilt das Berliner Datum, davor der Vortag (Spiele des US-Tags D laufen bis ca. 6 Uhr am Folgetag)."""
    b = datetime.fromtimestamp(t, BERLIN)
    day = b.date() if b.hour >= DAY_SWITCH_HOUR else (b - timedelta(days=1)).date()
    return day.isoformat()


def parse_until(text: str, now: float) -> float:
    """--bis HH:MM (Berliner Zeit) -> Epoch des naechsten Vorkommens dieser Uhrzeit (spaeter als jetzt)."""
    hh, mm = (int(x) for x in str(text).strip().split(":", 1))
    b = datetime.fromtimestamp(now, BERLIN)
    target = b.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target.timestamp() <= now:
        target = (b + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return target.timestamp()


def game_dir(root: Path, day: str, game_id: str) -> Path:
    return Path(root) / day / str(game_id)


def box_filename(t: float) -> str:
    dt = datetime.fromtimestamp(t, timezone.utc)
    return f"{dt:%Y%m%d}-{dt:%H%M%S}.json.gz"


def iso_utc(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Temp-Datei im selben Ordner, fsync, os.replace; bei Fehler bleibt die alte Datei unveraendert und kein Temp-Rest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_json(path: Path, obj) -> None:
    atomic_write_bytes(path, (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))


def write_gz(path: Path, raw: bytes) -> None:
    atomic_write_bytes(path, gzip.compress(raw, mtime=0))


def append_jsonl(path: Path, row: dict) -> None:
    """Zeile anhaengen ueber Lesen + Temp-Datei + os.replace (Dateien bleiben klein: Ereignisse, keine Messreihen)."""
    path = Path(path)
    old = path.read_bytes() if path.exists() else b""
    atomic_write_bytes(path, old + (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


# ----------------------------------------------------------------------------- Sperrdatei, Wartezeit, Abruf
class InstanceLock:
    """Eine Instanz je Ordner: flock auf <root>/.recorder.lock (wird beim Prozessende automatisch frei)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


class Backoff:
    """Wartezeit nach Fehlern: 30, 60, 120, 240, 300, 300 ... Sekunden; ein Erfolg setzt zurueck."""

    def __init__(self, start=BACKOFF_START, maximum=BACKOFF_MAX):
        self.start, self.maximum, self.wait = start, maximum, 0

    def failure(self) -> int:
        self.wait = self.start if not self.wait else min(self.maximum, self.wait * 2)
        return self.wait

    def success(self) -> None:
        self.wait = 0


class FetchResult:
    def __init__(self, status=None, data=None, raw=b"", error=None, ref=""):
        self.status, self.data, self.raw, self.error, self.ref = status, data, raw, error, ref

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.data is not None


def ref_from_body(text: str) -> str:
    """Referenznummer der Sperrseite ('Reference #18.6e2a3517.1792...'), sonst leer."""
    m = re.search(r"Reference(?:&#32;|\s)(?:&#35;|#)([0-9a-fA-F.]+(?:&#46;[0-9a-fA-F]+)*)", str(text))
    return m.group(1).replace("&#46;", ".") if m else ""


def http_fetch(url: str, headers: dict, http_get=None) -> FetchResult:
    """Ein einzelner Abruf ohne Wiederholung. Jeder Fehler wird als FetchResult mit error/status/ref zurueckgegeben, nie geworfen."""
    if http_get is None:
        import requests
        http_get = requests.get
    try:
        r = http_get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    except Exception as e:                                           # Netz, DNS, Timeout
        return FetchResult(error=type(e).__name__)
    status = r.status_code
    if status != 200:
        return FetchResult(status=status, error=f"HTTP {status}", ref=ref_from_body(getattr(r, "text", "")))
    try:
        return FetchResult(status=200, data=r.json(), raw=r.content)
    except ValueError:
        return FetchResult(status=200, error="ungueltige Antwort (kein JSON)")


# ----------------------------------------------------------------------------- Auswertung
def classify_game(clock: gc.GameClock, seen_before: bool, finalized: bool) -> str:
    """'wartet' (vor dem Anpfiff) | 'laeuft_neu' (laeuft, zum ersten Mal gesehen) | 'laeuft' | 'beendet' (Abschluss steht aus) | 'fertig'."""
    if clock.is_final:
        return "fertig" if finalized else "beendet"
    if clock.is_live:
        return "laeuft" if seen_before else "laeuft_neu"
    return "wartet"


def team_name(team: dict) -> str:
    return f"{team.get('teamCity', '')} {team.get('teamName', '')}".strip()


def _names_match(full: str, team: dict) -> bool:
    nick = str(team.get("teamName") or "").lower()
    full = str(full or "").lower()
    return bool(nick) and (full == team_name(team).lower() or full.endswith(nick))


def compact_game(g: dict, clock: gc.GameClock | None = None) -> dict:
    clock = clock or gc.from_scoreboard_game(g)
    return {
        "game_id": g.get("gameId"), "status": g.get("gameStatus"), "period": g.get("period"), "clock": g.get("gameClock"),
        "phase": clock.phase, "score_home": (g.get("homeTeam") or {}).get("score"), "score_away": (g.get("awayTeam") or {}).get("score"),
    }


def build_result(day: str, game_id: str, box_game: dict, row: dict, recorded_at: float) -> dict:
    """Endstand getrennt nach regulaerer Zeit und Verlaengerung, Punkte je Viertel (aus den Perioden des finalen Boxscores, sonst der Scoreboard-Zeile)."""
    out = {"version": LIVE_VERSION, "game_id": game_id, "day": day, "recorded_at": iso_utc(recorded_at)}
    for side in ("homeTeam", "awayTeam"):
        team = box_game.get(side) or row.get(side) or {}
        periods = sorted((team.get("periods") or (row.get(side) or {}).get("periods") or []), key=lambda p: int(p.get("period") or 0))
        reg = [int(p.get("score") or 0) for p in periods if int(p.get("period") or 0) <= gc.REG_PERIODS]
        ot = [int(p.get("score") or 0) for p in periods if int(p.get("period") or 0) > gc.REG_PERIODS]
        key = "home" if side == "homeTeam" else "away"
        out[key] = {"team": team_name(team), "tricode": team.get("teamTricode"), "quarters": reg, "regulation": sum(reg),
                    "overtime_periods": ot, "overtime": sum(ot), "final": int(team.get("score") or 0)}
    out["went_to_overtime"] = bool(out["home"]["overtime_periods"] or out["away"]["overtime_periods"])
    out["ot_count"] = max(len(out["home"]["overtime_periods"]), len(out["away"]["overtime_periods"]))
    out["status_text"] = box_game.get("gameStatusText") or row.get("gameStatusText")
    return out


# ----------------------------------------------------------------------------- Kontext (Modell-Schnappschuss, Hauptlinien)
def _load_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _sha1(path: Path) -> dict | None:
    try:
        p = Path(path)
        st = p.stat()
        return {"file": p.name, "sha1": hashlib.sha1(p.read_bytes()).hexdigest(), "size": st.st_size, "mtime": iso_utc(st.st_mtime)}
    except OSError:
        return None


def build_context(row: dict, clock: gc.GameClock, day: str, first_seen: float, late: bool, after_end: bool, now: float,
                  tracking_dir: Path | None = None, pregame_path: Path | None = None, model_path: Path | None = None) -> dict:
    """context.json: letzter Modell-Schnappschuss, Eintrag der Pre-Match-Eingabe, Odds-Cache-Linie, Modell-SHA. Fehlt der Schnappschuss, steht das im Feld notes."""
    tracking = Path(tracking_dir or os.environ.get("NBAEDGE_TRACKING_DIR") or ROOT / "data" / "tracking")
    pregame = Path(pregame_path or os.environ.get("NBAEDGE_PREGAME_LINES") or ROOT / "data" / "pregame_lines.json")
    home, away = row.get("homeTeam") or {}, row.get("awayTeam") or {}
    ctx = {
        "version": LIVE_VERSION, "game_id": row.get("gameId"), "day": day, "recorded_at": iso_utc(now), "first_seen_at": iso_utc(first_seen),
        "late_start": bool(late), "first_seen_after_end": bool(after_end), "first_seen_phase": clock.phase,
        "home": team_name(home), "away": team_name(away), "home_tricode": home.get("teamTricode"), "away_tricode": away.get("teamTricode"),
        "start_utc": row.get("gameTimeUTC"), "start_et": row.get("gameEt"), "scoreboard_at_first_sight": compact_game(row, clock),
        "snapshot": None, "game_key": None, "pre_match_entry": None, "pregame_lines": None,
        "model": _sha1(model_path or ROOT / "data" / "elo_model.pkl"), "notes": [],
    }
    if late:
        ctx["notes"].append("Spiel lief beim ersten Sehen schon: Boxscore-Reihe beginnt erst ab dann")
    if after_end:
        ctx["notes"].append("Spiel war beim ersten Sehen schon beendet: nur Endstand, finaler Boxscore und Play-by-Play")

    snaps = (_load_json(tracking / "projection_snapshots.json") or {}).get("games", {})
    for key, g in snaps.items():
        if g.get("game_date") == day and _names_match(g.get("home"), home) and _names_match(g.get("away"), away) and g.get("versions"):
            ctx["game_key"] = key
            ctx["snapshot"] = g["versions"][-1]
            break
    if ctx["snapshot"] is None:
        ctx["notes"].append("kein Modell-Schnappschuss fuer dieses Spiel vorhanden (Anker muss live nachgerechnet werden)")
    if ctx["game_key"]:
        ctx["pre_match_entry"] = ((_load_json(tracking / "pre_match_entries.json") or {}).get("entries") or {}).get(ctx["game_key"])
    if ctx["pre_match_entry"] is None:
        ctx["notes"].append("keine Pre-Match-Eingabe (eigene/Betano-Linien) gefunden")

    start_ts = None
    try:
        start_ts = datetime.fromisoformat(str(row.get("gameTimeUTC")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    for ev_id, e in (_load_json(pregame) or {}).items():
        if not isinstance(e, dict):
            continue
        if _names_match(e.get("home_team"), home) and _names_match(e.get("away_team"), away):
            if start_ts is None or abs(float(e.get("commence") or start_ts) - start_ts) < 6 * 3600:
                ctx["pregame_lines"] = {"odds_event_id": ev_id, **{k: e.get(k) for k in ("commence", "fetched_at", "lines")}}
                break
    if ctx["pregame_lines"] is None:
        ctx["notes"].append("keine Vorab-Linie aus dem Odds-Cache (pregame_lines.json) gefunden")
    return ctx


# ----------------------------------------------------------------------------- Recorder
class Recorder:
    def __init__(self, root: Path, fetch=None, now=time.time, sleep=time.sleep, log=print, headers: dict | None = None,
                 tracking_dir: Path | None = None, pregame_path: Path | None = None, model_path: Path | None = None, until: float | None = None):
        self.root = Path(root)
        self.now, self.sleep, self.log = now, sleep, log
        self.headers = headers if headers is not None else nba_headers()
        self.fetch = fetch or (lambda url: http_fetch(url, self.headers))
        self.paths = dict(tracking_dir=tracking_dir, pregame_path=pregame_path, model_path=model_path)
        self.backoff = Backoff()
        self.games: dict[str, dict] = {}
        self.day = datetime.fromtimestamp(now(), ET).strftime("%Y-%m-%d")
        self.start_t = now()
        self.until = until
        self.last_today_activity: float | None = None    # letzter Zeitpunkt mit neuem oder nicht beendetem Spiel des AKTUELLEN US-Spieltags
        self.last_heartbeat = 0.0
        self.last_request = 0.0
        self._emitted: dict[str, tuple[str, float]] = {}
        self.requests = {"ok": 0, "fehler": 0}

    # -- Ereignisse
    def emit(self, day: str, game_id: str | None, row: dict) -> None:
        t = self.now()
        base = {"ts": iso_utc(t), "day": day, "game_id": game_id, "v": LIVE_VERSION}
        base.update(row)
        content = json.dumps({k: v for k, v in base.items() if k != "ts"}, sort_keys=True, ensure_ascii=False)
        targets = [self.root / day / "events.jsonl"] + ([game_dir(self.root, day, game_id) / "events.jsonl"] if game_id else [])
        for path in targets:
            last = self._emitted.get(str(path))
            if last and last[0] == content and t - last[1] < DEDUPE_SECONDS:
                continue                                                  # keine doppelten Zeilen
            append_jsonl(path, base)
            self._emitted[str(path)] = (content, t)

    def day_games(self) -> list[dict]:
        return [dict(s["compact"]) for s in self.games.values() if s["day"] == self.day]

    # -- Abrufe
    def _get(self, url: str) -> FetchResult:
        gap = REQUEST_GAP_SECONDS - (self.now() - self.last_request)
        if gap > 0:
            self.sleep(gap)
        self.last_request = self.now()
        res = self.fetch(url)
        self.requests["ok" if res.ok else "fehler"] += 1
        return res

    def _fail(self, what: str, res: FetchResult, game: dict | None = None) -> None:
        wait = self.backoff.failure()
        row = {"type": "error", "what": what, "http": res.status, "error": res.error, "ref": res.ref, "backoff_s": wait}
        if game:
            row.update(game["compact"])
            self.emit(game["day"], game["compact"]["game_id"], row)
        else:
            row["games"] = self.day_games()
            self.emit(self.day, None, row)
        self.log(f"[{time.strftime('%H:%M:%S')}] FEHLER {what}: {res.error or res.status}{' ref=' + res.ref if res.ref else ''} - warte {wait} s")

    # -- ein Durchlauf
    def cycle(self) -> bool:
        """Ein Scoreboard-Abruf und die faelligen Aktionen. Rueckgabe False bei einem Fehler (der Aufrufer wartet dann self.backoff.wait)."""
        t = self.now()
        res = self._get(NBA_SCOREBOARD_URL)
        if not res.ok:
            self._fail("scoreboard", res)
            return False
        self.backoff.success()
        board = (res.data or {}).get("scoreboard") or {}
        rows = board.get("games") or []
        if board.get("gameDate"):
            self.day = str(board["gameDate"])
        for row in rows:
            row["_scoreboard_date"] = self.day
            if not self._handle_game(row, t):
                return False
        if t - self.last_heartbeat >= HEARTBEAT_SECONDS:
            self._heartbeat(t)
        return True

    def _state(self, row: dict, t: float) -> dict:
        gid = str(row.get("gameId"))
        if gid not in self.games:
            day = game_day_us(row)
            gdir = game_dir(self.root, day, gid)
            self.games[gid] = {"day": day, "dir": gdir, "first_seen": t, "phase_key": None, "last_box": 0.0, "compact": {},
                               "seen_live": False, "context": (gdir / "context.json").exists(),
                               "finalized": all((gdir / n).exists() for n in ("final_box.json.gz", "final_pbp.json.gz", "result.json"))}
        return self.games[gid]

    def _handle_game(self, row: dict, t: float) -> bool:
        clock = gc.from_scoreboard_game(row)
        st = self._state(row, t)
        gid = str(row.get("gameId"))
        seen = st["seen_live"]
        kind = classify_game(clock, seen, st["finalized"])
        st["compact"] = compact_game(row, clock)
        if st["day"] == current_us_day(t) and (self.last_today_activity is None or kind != "fertig"):
            self.last_today_activity = t           # erstes Spiel des aktuellen Tags gesehen oder Spiel noch nicht abgeschlossen
        key = (clock.phase, clock.period)
        if st["phase_key"] != key:
            self.emit(st["day"], gid, {"type": "phase", "from": st["phase_key"][0] if st["phase_key"] else None, "clock_missing": clock.clock_missing, **st["compact"]})
            self.log(f"[{time.strftime('%H:%M:%S')}] {gid} {team_name(row.get('awayTeam') or {})} @ {team_name(row.get('homeTeam') or {})}: {clock.phase} (Periode {clock.period})")
            st["phase_key"] = key
        if kind in ("laeuft_neu", "laeuft", "beendet") and not st["context"]:
            late = kind == "laeuft_neu" and clock.elapsed_total_s > 60
            ctx = build_context(row, clock, st["day"], st["first_seen"], late, kind == "beendet", t, **self.paths)
            write_json(st["dir"] / "context.json", ctx)
            st["context"] = True
            self.emit(st["day"], gid, {"type": "context", "snapshot": ctx["snapshot"] is not None, "late_start": late, **st["compact"]})
        if clock.is_live:
            st["seen_live"] = True
            if t - st["last_box"] >= BOX_SECONDS - BOX_TOLERANCE:
                res = self._get(NBA_BOXSCORE_URL.format(game_id=gid))
                if not res.ok:
                    self._fail("box", res, st)
                    return False
                write_gz(st["dir"] / "box" / box_filename(t), res.raw)
                st["last_box"] = t
        elif kind == "beendet":
            return self._finalize(row, st, t)
        return True

    def _finalize(self, row: dict, st: dict, t: float) -> bool:
        gid = str(row.get("gameId"))
        for name, url in (("final_box.json.gz", NBA_BOXSCORE_URL.format(game_id=gid)), ("final_pbp.json.gz", NBA_PLAYBYPLAY_URL.format(game_id=gid))):
            if (st["dir"] / name).exists():
                continue
            res = self._get(url)
            if not res.ok:
                self._fail("final_box" if "box" in name else "final_pbp", res, st)
                return False
            write_gz(st["dir"] / name, res.raw)
        box = json.loads(gzip.decompress((st["dir"] / "final_box.json.gz").read_bytes()).decode("utf-8")).get("game", {})
        write_json(st["dir"] / "result.json", build_result(st["day"], gid, box, row, t))
        st["finalized"] = True
        self.emit(st["day"], gid, {"type": "final", **st["compact"]})
        self.log(f"[{time.strftime('%H:%M:%S')}] {gid}: Spielende gespeichert (final_box, final_pbp, result)")
        return True

    def _heartbeat(self, t: float) -> None:
        self.last_heartbeat = t
        games = self.day_games()
        for st in self.games.values():
            if st["compact"].get("status") == 2:
                self.emit(st["day"], st["compact"]["game_id"], {"type": "heartbeat", "backoff_s": self.backoff.wait, **st["compact"]})
        self.emit(self.day, None, {"type": "heartbeat", "games": games, "backoff_s": self.backoff.wait, "requests": dict(self.requests),
                                   "live": sum(1 for g in games if g["status"] == 2), "final": sum(1 for g in games if g["status"] == 3),
                                   "pre": sum(1 for g in games if g["status"] == 1)})

    def stop_reason(self) -> str | None:
        """Grund fuer das Beenden oder None. Regeln: harte Endzeit (--bis); Obergrenze 20 h; sonst nur wenn (1) ein Spiel des aktuellen US-Spieltags gesehen wurde,
        (2) alle bekannten Spiele dieses Tags beendet sind und (3) danach 3 h lang kein neues Spiel erschien. Zeigt das Scoreboard noch den Vortag: weiterlaufen."""
        t = self.now()
        if self.until is not None and t >= self.until:
            return "--bis erreicht"
        if t - self.start_t >= MAX_RUNTIME_SECONDS:
            return "Obergrenze von 20 Stunden Laufzeit erreicht"
        today = [s for s in self.games.values() if s["day"] == current_us_day(t)]
        if not today or any(s["compact"].get("status") != 3 for s in today):
            return None
        if self.last_today_activity is not None and t - self.last_today_activity >= IDLE_EXIT_SECONDS:
            return "alle Spiele des Spieltags beendet, 3 Stunden ohne neues Spiel"
        return None

    def should_stop(self) -> bool:
        return self.stop_reason() is not None

    def run(self, once: bool = False) -> None:
        self.emit(self.day, None, {"type": "start", "games": self.day_games(), "headers_user_agent": self.headers.get("User-Agent")})
        try:
            while True:
                ok = self.cycle()
                if once:
                    break
                reason = self.stop_reason()
                if reason:
                    self.emit(self.day, None, {"type": "stop", "reason": reason, "games": self.day_games()})
                    self.log(f"Ende: {reason}.")
                    break
                self.sleep(self.backoff.wait if not ok else POLL_SECONDS)
        except KeyboardInterrupt:
            self.emit(self.day, None, {"type": "stop", "reason": "Strg+C/SIGTERM", "games": self.day_games()})
            self.log("Beendet (Strg+C).")


# ----------------------------------------------------------------------------- Start
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NBA-Live-Roh-Recorder")
    ap.add_argument("--einmal", action="store_true", help="ein Durchlauf, dann Ende")
    ap.add_argument("--dir", help="Zielordner (sonst NBAEDGE_LIVE_DIR oder ~/NBAEdge_live_history)")
    ap.add_argument("--ohne-caffeinate", action="store_true")
    ap.add_argument("--bis", metavar="HH:MM", help="harte Endzeit (deutsche Zeit), z. B. 07:00")
    args = ap.parse_args(argv)
    root = live_root(args.dir)
    lock = InstanceLock(root / ".recorder.lock")
    if not lock.acquire():
        print(f"Der Recorder laeuft schon (Sperrdatei {root / '.recorder.lock'}). Zweite Instanz nicht gestartet.")
        return 1
    caff = None
    if not args.ohne_caffeinate and shutil.which("caffeinate"):
        caff = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])        # haelt den Mac wach, endet mit diesem Prozess
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        rec = Recorder(root, until=parse_until(args.bis, time.time()) if args.bis else None)
        print(f"Recorder gestartet. Daten: {root}  (Beenden: Strg+C)  Chrome-UA: {rec.headers['User-Agent'].split('Chrome/')[1].split(' ')[0]}")
        rec.run(once=args.einmal)
    finally:
        lock.release()
        if caff:
            caff.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
