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
    events = read_events()
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
