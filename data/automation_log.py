"""Protokoll der geplanten Auftraege: data/automation.log (klein gehalten, ohne Keys und URLs).

Format je Zeile:  <ISO-Zeit> | job=<Auftrag> | result=OK|SKIP|WARN|ERROR | detail=<kurze Meldung>
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 1_000_000          # darueber wird auf die letzten KEEP_LINES Zeilen gekuerzt
KEEP_LINES = 500
STALE_HOURS = 36
JOBS = ("update_model", "fetch_odds_daily")
SEPARATE_JOBS = ("betano_auto",)
BETANO_JOB = "betano_auto"
BETANO_MAX_AGE_HOURS = 3
BETANO_WINDOW_HOURS = 12
_LINE = re.compile(r"^(?P<ts>\S+) \| job=(?P<job>\S+) \| result=(?P<result>OK|SKIP|WARN|ERROR) \| detail=(?P<detail>.*)$")


def log_path() -> Path:
    return Path(os.environ.get("NBAEDGE_AUTOMATION_LOG") or ROOT / "data" / "automation.log")


def sanitize(text: object) -> str:
    """Eine Zeile, ohne URLs, apiKey-Parameter und ohne die echten Key-Werte aus der Umgebung."""
    t = " ".join(str(text).split())
    t = re.sub(r"https?://\S+", "<URL>", t)
    t = re.sub(r"(?i)api[_-]?key\s*[=:]\s*\S+", "apiKey=<verborgen>", t)
    for name in ("ODDS_API_KEY", "BALLDONTLIE_API_KEY", "NEWS_API_KEY"):
        val = os.environ.get(name)
        if val and len(val) >= 6:
            t = t.replace(val, "<verborgen>")
    return t.replace("|", "/")[:200]


def log_event(job: str, result: str, detail: str = "", now: datetime | None = None) -> None:
    """Haengt eine Zeile an. Wirft nie (ein kaputtes Protokoll darf keinen Auftrag abbrechen)."""
    try:
        ts = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
        line = f"{ts} | job={job} | result={result} | detail={sanitize(detail)}\n"
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        if path.stat().st_size > MAX_BYTES:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)[-KEEP_LINES:]
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(lines), encoding="utf-8")
            os.replace(tmp, path)
    except Exception:
        pass


def read_events(limit: int = 400) -> list[dict]:
    """Die letzten Eintraege (aelteste zuerst). Fehlt die Datei: []"""
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        m = _LINE.match(line)
        if not m:
            continue
        try:
            ts = datetime.fromisoformat(m.group("ts"))
        except ValueError:
            continue
        out.append({"time": ts, "job": m.group("job"), "result": m.group("result"), "detail": m.group("detail")})
    return out


def sidebar_status(now: datetime | None = None) -> dict | None:
    """Daten fuer die Sidebar-Zeile oder None, wenn es noch kein Protokoll gibt.
    warn=True bei einem Fehler im letzten Lauf oder wenn ein Auftrag laenger als STALE_HOURS ohne OK/SKIP-Lauf ist."""
    events = [e for e in read_events(2000) if e["job"] not in SEPARATE_JOBS]     # betano_auto hat eine eigene Zeile (betano_status) und darf diese hier nicht veraendern
    if not events:
        return None
    now = now or datetime.now().astimezone()
    last = events[-1]
    warn, hint = last["result"] in ("ERROR", "WARN"), ""
    if warn:
        hint = "Letzter Lauf mit Fehler, Details in data/automation.log" if last["result"] == "ERROR" else "Letzter Lauf mit Warnung (Modell aktualisiert, Ergebnisse nicht gespeichert), Details in data/automation.log"
    stale = []
    for job in {e["job"] for e in events}:
        good = [e for e in events if e["job"] == job and e["result"] in ("OK", "SKIP", "WARN")]
        if not good or now - good[-1]["time"] > timedelta(hours=STALE_HOURS):
            stale.append(job)
    if stale:
        warn = True
        hint = (hint + "; " if hint else "") + f"seit über {STALE_HOURS} Std. kein erfolgreicher Lauf: {', '.join(sorted(stale))}"
    return {"job": last["job"], "time": last["time"], "result": last["result"], "detail": last["detail"], "warn": warn, "hint": hint}


def betano_state_path() -> Path:
    return log_path().with_name("betano_auto_state.json")


def games_in_sight_cached(now: datetime | None = None) -> bool:
    """Beginnt laut data/upcoming_cache.json (nur Lesen, kein Abruf) ein noch nicht begonnenes Spiel in den naechsten 12 Stunden?"""
    try:
        import json
        from data import fetcher
        from data import pre_match_store as store
        ts_now = (now or datetime.now().astimezone()).timestamp()
        games = json.loads(fetcher._upcoming_cache_path().read_text()).get("games", [])
        for g in games:
            if str(g.get("status") or "").lower() == "final":
                continue
            t = store.parse_utc(store.normalize_start(g.get("datetime")))
            if t is not None and ts_now < t <= ts_now + BETANO_WINDOW_HOURS * 3600:
                return True
    except Exception:
        pass
    return False


def betano_status(now: datetime | None = None, game_in_sight: bool | None = None) -> dict:
    """Daten fuer die Sidebar-Zeile 'Betano-Automatik' aus data/automation.log (job=betano_auto) und dem Zustandsfile (nur Lesen, kein Netz).
    level: 'none' (nie gelaufen: 'nicht aktiv', keine Warnung) | 'green' | 'yellow' | 'red'.
    rot: AUS (403) oder letzter Lauf ERROR; gelb: Pause, Spielplan nicht verfuegbar, Warnung, oder letzter Lauf aelter als 3 Std. waehrend ein Spiel in Sicht ist;
    gruen sonst (ok, auch 'kein Spiel in Sicht'). Das Zustandsfile hat Vorrang fuer AUS und Pause (Pause nur, solange sie nicht abgelaufen ist)."""
    now = now or datetime.now().astimezone()
    events = [e for e in read_events(2000) if e["job"] == BETANO_JOB]
    state = {}
    try:
        import json
        state = json.loads(betano_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not events and not state:
        return {"level": "none", "text": "Betano-Automatik: nicht aktiv", "hint": ""}
    if game_in_sight is None:
        game_in_sight = games_in_sight_cached(now)
    last = events[-1] if events else None
    fmt = lambda t: t.strftime("%d.%m. %H:%M")
    res = {"OK": "OK", "SKIP": "übersprungen", "WARN": "Warnung", "ERROR": "Fehler"}
    text = "Betano-Automatik: " + (f"letzter Lauf {fmt(last['time'])}, {res[last['result']]}" if last else "noch kein Lauf")
    level, hint, zustand = "green", "", "ok"
    st = state.get("state")
    pause_until = None
    if st == "pause" and state.get("pause_until"):
        try:
            pause_until = datetime.fromisoformat(state["pause_until"])
        except ValueError:
            pause_until = None
    if st == "aus":
        level, zustand = "red", "AUS bis Freigabe"
        hint = "Freigabe: venv/bin/python betano_auto.py --reset"
    elif pause_until is not None and pause_until > now:
        level, zustand = "yellow", f"Pause bis {fmt(pause_until)}"
    elif last and last["result"] == "ERROR":
        level, hint = "red", "Letzter Lauf mit Fehler, Details in data/automation.log"
    elif last and "Spielplan nicht verfügbar" in last["detail"]:
        level, hint = "yellow", "Spielplan nicht verfügbar"
    elif last and last["result"] == "WARN":
        level, hint = "yellow", "Letzter Lauf mit Warnung (einzelne Spiele fehlgeschlagen)"
    elif game_in_sight and (last is None or now - last["time"] > timedelta(hours=BETANO_MAX_AGE_HOURS)):
        level, hint = "yellow", f"Spiel in Sicht, aber seit über {BETANO_MAX_AGE_HOURS} Std. kein Lauf"
    return {"level": level, "text": f"{text} · Zustand: {zustand}", "hint": hint}
