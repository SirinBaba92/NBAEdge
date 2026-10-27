"""
Zentrale Odds-API-Abrufe (einzige Stelle im Projekt, die api.the-odds-api.com aufruft).

- Zwischenspeicher auf der Festplatte (data/odds_cache.json): ueberlebt Neuladen, neue Sitzungen und Neustarts.
- Es wird nur abgefragt, wenn
    * refresh=True (ausdruecklicher Knopfdruck), oder
    * es noch gar keinen Cache fuer diesen Markt gibt (einmaliger Abruf beim ersten Start), oder
    * max_age gesetzt ist und der Cache aelter ist (Auto-Refresh der Live-Linien, standardmaessig aus).
  Ein abgelaufener Cache (TTL 20 Min.) loest KEINEN Abruf aus, er wird mit Altersangabe angezeigt.
- Credit-Schutz: Unter ODDS_MIN_CREDITS_RESERVE gibt es keine automatischen Abrufe, nur noch manuelle.
  Nach einem Fehler gibt es ODDS_FAILURE_BACKOFF_SECONDS lang keinen automatischen Wiederholungsversuch.
- Protokoll jedes tatsaechlichen Abrufs in data/odds_calls.log (Zeit, Aufrufer, Markt, Regionen, Credits).
- Der API-Key steht nie im Cache, im Log oder in Meldungen (Exception-Texte von requests enthalten die URL und
  damit den Key; sie werden deshalb nie weitergereicht).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from config.settings import (
    ODDS_FAILURE_BACKOFF_SECONDS,
    ODDS_MIN_CREDITS_RESERVE,
    ODDS_REGIONS,
    ODDS_SPORT,
    ODDS_TOTALS_TTL_SECONDS,
)

load_dotenv()

BASE = "https://api.the-odds-api.com/v4"
ROOT = Path(__file__).resolve().parent.parent
KINDS = {"totals_spreads": "totals,spreads", "h2h": "h2h"}

_lock = threading.RLock()
_mem = {"path": None, "mtime": None, "obj": None}
_problem = {"at": None, "path": None, "error": None}     # unlesbarer Odds-Cache (fuer den Hinweis in der App)
PROBLEM_SHOW_SECONDS = 3600


def cache_problem(now: float | None = None) -> dict | None:
    """Hinweis, wenn der Odds-Cache zuletzt nicht lesbar war (eine Stunde lang sichtbar, auch nach dem Neuaufbau), sonst None."""
    now = now or time.time()
    if _problem["at"] is not None and now - _problem["at"] < PROBLEM_SHOW_SECONDS:
        return dict(_problem)
    return None


class OddsError(Exception):
    """Kurze deutsche Meldung ohne URL und ohne Key."""


@dataclass
class OddsResult:
    kind: str
    data: list | None = None          # Roh-Antwort der Odds API (Liste von Events) oder None
    fetched_at: float | None = None   # Zeitpunkt des Abrufs (Epoch) der Daten
    age: float | None = None          # Alter der Daten in Sekunden
    from_cache: bool = False
    fetched: bool = False             # True, wenn in DIESEM Aufruf wirklich abgefragt wurde
    stale: bool = False               # Cache aelter als ODDS_TOTALS_TTL_SECONDS
    blocked: str | None = None        # 'reserve' oder 'backoff': automatischer Abruf unterdrueckt
    error: str | None = None
    remaining: int | None = None      # Credits laut letztem x-requests-remaining
    low_credits: bool = False         # unter der Reserve


def cache_path() -> Path:
    return Path(os.environ.get("NBAEDGE_ODDS_CACHE") or ROOT / "data" / "odds_cache.json")


def log_path() -> Path:
    return Path(os.environ.get("NBAEDGE_ODDS_LOG") or ROOT / "data" / "odds_calls.log")


# ------------------------------------------------------------------------------ Speicher
def _read() -> dict:
    path = cache_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        _mem.update(path=None, mtime=None, obj=None)
        return {"entries": {}, "credits": {}, "last_error": {}}
    if _mem["path"] == str(path) and _mem["mtime"] == mtime and _mem["obj"] is not None:
        return _mem["obj"]
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError
    except Exception as e:
        obj = {}
        _problem.update(at=time.time(), path=str(path), error=f"{type(e).__name__}")
        print(f"  Odds-Cache nicht lesbar ({path.name}): {type(e).__name__}")
    obj.setdefault("entries", {})
    obj.setdefault("credits", {})
    obj.setdefault("last_error", {})
    _mem.update(path=str(path), mtime=mtime, obj=obj)
    return obj


def _write(obj: dict) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    _mem.update(path=str(path), mtime=path.stat().st_mtime_ns, obj=obj)


def _log(caller: str, kind: str, status, remaining, cost, error: str | None = None) -> None:
    try:
        line = (
            f"{datetime.now().astimezone().isoformat(timespec='seconds')} | caller={caller} | kind={kind} | "
            f"markets={KINDS[kind]} | regions={','.join(ODDS_REGIONS)} | status={status} | "
            f"remaining={remaining if remaining is not None else '?'} | cost={cost if cost is not None else '?'}"
            + (f" | error={error}" if error else "")
        )
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_skip(caller: str, kind: str, reason: str) -> None:
    """Protokolliert einen bewusst NICHT ausgefuehrten Abruf (z. B. geplanter Lauf bei zu wenig Credits)."""
    try:
        reason = " ".join(str(reason).replace("|", "/").split())[:160]
        line = (f"{datetime.now().astimezone().isoformat(timespec='seconds')} | caller={caller} | kind={kind} | "
                f"markets={KINDS[kind]} | regions={','.join(ODDS_REGIONS)} | status=uebersprungen | reason={reason}")
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------ Abruf
def _http_fetch(kind: str, caller: str):
    """Der einzige echte Netzwerkabruf. Gibt (daten, remaining, cost) zurueck oder wirft OddsError."""
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise OddsError("Odds API: ODDS_API_KEY fehlt (.env).")
    params = {
        "apiKey": key,
        "regions": ",".join(ODDS_REGIONS),
        "markets": KINDS[kind],
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    try:
        r = requests.get(f"{BASE}/sports/{ODDS_SPORT}/odds", params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        _log(caller, kind, "netzwerkfehler", None, None, error=type(e).__name__)
        raise OddsError("Odds API: keine Verbindung.") from None
    remaining = _to_int(r.headers.get("x-requests-remaining"))
    cost = _to_int(r.headers.get("x-requests-last"))
    _log(caller, kind, r.status_code, remaining, cost)
    print(f"  Odds API requests remaining ({KINDS[kind]}): {remaining if remaining is not None else '?'}")
    if r.status_code != 200:
        reasons = {401: "Key ungueltig oder Kontingent erschoepft (HTTP 401)", 429: "zu viele Anfragen (HTTP 429)",
                   422: "ungueltige Anfrage (HTTP 422)"}
        raise _OddsHttpError(f"Odds API: {reasons.get(r.status_code, f'Abruf fehlgeschlagen (HTTP {r.status_code})')}.", remaining, cost)
    try:
        return r.json(), remaining, cost
    except ValueError:
        raise _OddsHttpError("Odds API: ungueltige Antwort.", remaining, cost) from None


class _OddsHttpError(OddsError):
    def __init__(self, msg, remaining=None, cost=None):
        super().__init__(msg)
        self.remaining, self.cost = remaining, cost


def get_odds(kind: str, caller: str, refresh: bool = False, cache_only: bool = False,
             max_age: float | None = None) -> OddsResult:
    """Liefert Odds-Daten fuer 'totals_spreads' oder 'h2h' (siehe Modul-Docstring fuer die Regeln)."""
    if kind not in KINDS:
        raise ValueError(f"unbekannte Art: {kind}")
    with _lock:
        now = time.time()
        store = _read()
        entry = store["entries"].get(kind)
        remaining = _to_int(store["credits"].get("remaining"))
        age = (now - entry["fetched_at"]) if entry else None
        res = OddsResult(
            kind=kind, data=entry["data"] if entry else None, fetched_at=entry["fetched_at"] if entry else None, age=age,
            from_cache=entry is not None, stale=age is not None and age > ODDS_TOTALS_TTL_SECONDS,
            remaining=remaining, low_credits=remaining is not None and remaining < ODDS_MIN_CREDITS_RESERVE,
        )
        if cache_only:
            return res
        need = bool(refresh) or entry is None or (max_age is not None and age is not None and age > max_age)
        if not need:
            return res
        if not refresh:                                    # automatischer Abruf: Schutzregeln
            if res.low_credits:
                res.blocked = "reserve"
                return res
            last = store["last_error"].get(kind)
            if last and now - last["at"] < ODDS_FAILURE_BACKOFF_SECONDS:
                res.blocked, res.error = "backoff", last["msg"]
                return res
        try:
            data, remaining, cost = _http_fetch(kind, caller)
        except OddsError as e:
            store["last_error"][kind] = {"at": now, "msg": str(e)}
            if isinstance(e, _OddsHttpError) and e.remaining is not None:
                store["credits"].update(remaining=e.remaining, updated_at=now)
                res.remaining = e.remaining
                res.low_credits = e.remaining < ODDS_MIN_CREDITS_RESERVE
            _write(store)
            res.error = str(e)
            return res
        store["entries"][kind] = {"fetched_at": now, "markets": KINDS[kind], "regions": ",".join(ODDS_REGIONS), "data": data}
        store["last_error"].pop(kind, None)
        if remaining is not None:
            store["credits"].update(remaining=remaining, updated_at=now, last_cost=cost)
        _write(store)
        try:                                   # letzte Vorab-Linie je Spiel merken (data/pregame_lines.py)
            from data.pregame_lines import update_from_snapshot
            update_from_snapshot(data, now)
        except Exception:
            pass
        res.data, res.fetched_at, res.age, res.from_cache, res.fetched, res.stale = data, now, 0.0, False, True, False
        res.remaining = remaining if remaining is not None else res.remaining
        res.low_credits = res.remaining is not None and res.remaining < ODDS_MIN_CREDITS_RESERVE
        return res


# ------------------------------------------------------------------------------ Anzeige-Helfer
def credits_info() -> dict:
    with _lock:
        c = _read()["credits"]
    remaining = _to_int(c.get("remaining"))
    return {"remaining": remaining, "updated_at": c.get("updated_at"),
            "low": remaining is not None and remaining < ODDS_MIN_CREDITS_RESERVE}


def describe_age(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    s = int(max(0, seconds))
    if s < 60:
        return f"vor {s} Sek."
    m = s // 60
    if m < 60:
        return f"vor {m} Min."
    h, m = divmod(m, 60)
    return f"vor {h} Std. {m} Min." if m else f"vor {h} Std."
