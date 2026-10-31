"""
Betano-Automatik, Kern (Roadmap 3.2): EIN Lauf ohne Eingabe, Quoten als "auto" speichern (data/pre_match_store.save_auto).

  cd ~/Desktop/NBAEdge && venv/bin/python betano_auto.py        # ein Lauf; noch nirgends eingebunden (kein launchd-Job)

Ablauf: Sperre -> Zustand (pause/aus?) -> Spiele, die noch nicht begonnen haben und in den naechsten 12 Stunden beginnen (aus data/upcoming_cache.json, wie eingabe.py)
-> Spielliste bei Betano (1 Abruf) -> je Spiel 1 Abruf (3 s Pause) -> parsen -> save_auto. Handeingaben haben Vorrang und werden nie ueberschrieben.
Stopp: HTTP 429 -> sofort stoppen, 6 Stunden Pause; HTTP 403 -> sofort stoppen, Automatik AUS bis reset(); Timeout/Formatfehler -> nur dieses Spiel;
3 Fehler in einem Lauf -> Lauf abbrechen. Alles in data/automation.log (job=betano_auto, ohne URLs/Keys).
Zustand: data/betano_auto_state.json (neben automation.log, nicht in data/tracking). Zuruecksetzen von Hand:  venv/bin/python betano_auto.py --reset
Sperre: data/betano_auto.lock (flock). Belegt durch einen anderen Lauf oder einen Handabruf (betano_import.py) -> Lauf wird uebersprungen.
Recorder: run_once(respect_recorder=True) ueberspringt bei laufendem Recorder; main() ruft mit respect_recorder=False auf (Betrieb).
Exit-Code 0 bei OK/uebersprungen, 1 bei Fehler.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

import betano_import as bi
import eingabe as ei
from data import automation_log as alog
from data import job_lock
from data import pre_match_store as store
from data import rosters

JOB = "betano_auto"
WINDOW_SECONDS = 12 * 3600          # nur Spiele, die in den naechsten 12 Stunden beginnen
PAUSE_429_SECONDS = 6 * 3600
MAX_ERRORS = 3
STATES = ("ok", "pause", "aus")
SCHEDULE_MAX_AGE_SECONDS = 6 * 3600   # upcoming_cache.json juenger als 6 Stunden (und gleiches Fenster) gilt als aktuell, sonst einmal neu holen


class StopRun(Exception):
    """Lauf sofort beenden (429/403)."""


def state_path() -> Path:
    return alog.log_path().with_name("betano_auto_state.json")


def recorder_lock_path() -> Path:
    return Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history") / ".recorder.lock"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def load_state() -> dict:
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
        if d.get("state") in STATES:
            return {"state": d["state"], "pause_until": d.get("pause_until"), "last_run": d.get("last_run"), "last_error": d.get("last_error")}
    except (OSError, ValueError, AttributeError):
        pass
    return {"state": "ok", "pause_until": None, "last_run": None, "last_error": None}


def save_state(st: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def reset(now: float | None = None) -> dict:
    """Freigabe von Hand: Zustand ok, keine Pause, Fehler geloescht (letzter Lauf bleibt)."""
    st = load_state()
    st.update(state="ok", pause_until=None, last_error=None)
    save_state(st)
    alog.log_event(JOB, "OK", "Freigabe von Hand: Automatik wieder an", now=datetime.fromtimestamp(now).astimezone() if now else None)
    return st


def _log(result: str, detail: str, now: float) -> None:
    alog.log_event(JOB, result, detail, now=datetime.fromtimestamp(now).astimezone())


class ScheduleError(Exception):
    """Spielplan nicht verfuegbar; code = HTTP-Status (429/403/401), falls erkennbar."""

    def __init__(self, msg: str, code: int | None = None):
        super().__init__(msg)
        self.code = code


def _error_code(text: str) -> int | None:
    import re
    m = re.search(r"\b(429|403|401)\b", text or "")
    return int(m.group(1)) if m else None


def get_schedule(now: float, fetch_upcoming=None) -> tuple[list[dict], str]:
    """Spielplan (BallDontLie-Spiele) und Herkunft: ('Cache') wenn upcoming_cache.json juenger als 6 h und fuer dasselbe UTC-Fenster, sonst
    ('neu geholt') ueber die bestehende fetch_upcoming_games(now=now) (schreibt den Cache selbst, ein Abruf). Fehler -> ScheduleError.
    Ein von fetch_upcoming_games ersatzweise gelieferter alter Cache gilt als Fehler (nicht als aktuell)."""
    from data import fetcher
    from datetime import timezone
    fetch_upcoming = fetch_upcoming or fetcher.fetch_upcoming_games
    today = datetime.fromtimestamp(now, timezone.utc).date()
    want = {"start_date": (today - timedelta(days=1)).isoformat(), "end_date": today.isoformat(), "per_page": 100}
    try:
        cached = json.loads(fetcher._upcoming_cache_path().read_text())
        if cached.get("params") == want and 0 <= now - float(cached.get("fetched_at", 0)) < SCHEDULE_MAX_AGE_SECONDS:
            return [g for g in cached.get("games", []) if g.get("status") != "Final"], "Cache"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        games = fetch_upcoming(now=now)
    except Exception as e:
        raise ScheduleError(f"{type(e).__name__}: {e}", _error_code(f"{type(e).__name__}: {e}")) from None
    stale = fetcher.upcoming_status()
    if stale.get("stale"):
        err = stale.get("error") or "alter Cache"
        raise ScheduleError(err, _error_code(err))
    return games, "neu geholt"


def games_in_sight(now: float, games: list | None = None) -> list[dict]:
    """Noch nicht begonnene Spiele (ei.list_games: Cache, vor Anpfiff), die in den naechsten 12 Stunden beginnen."""
    out = []
    for g in ei.list_games(now, games):
        ts = store.parse_utc(g["start"])
        if ts is not None and now < ts <= now + WINDOW_SECONDS:
            out.append(g)
    return out


def _http_stop(e: urllib.error.HTTPError, st: dict, now: float, where: str) -> None:
    if e.code == 429:
        st.update(state="pause", pause_until=_iso(now + PAUSE_429_SECONDS), last_error=f"HTTP 429 ({where})")
        save_state(st)
        _log("ERROR", f"HTTP 429 ({where}), gestoppt, Pause 6 Stunden bis {st['pause_until']}", now)
    else:
        st.update(state="aus", pause_until=None, last_error=f"HTTP 403 ({where})")
        save_state(st)
        _log("ERROR", f"HTTP 403 ({where}), gestoppt, Automatik AUS bis zur Freigabe (betano_auto.py --reset)", now)
    raise StopRun(e.code)


def _noop(*_a, **_k):
    return None


def process_game(g: dict, ev: dict, data: dict, now: float) -> str:
    """Parsen und mit save_auto speichern. Rueckgabe 'saved' | 'unchanged' | 'skipped' (Hand hat Vorrang oder Spiel begonnen). Wirft bei Fehlern."""
    parsed = bi.parse_event(data, g["home"], g["away"])
    roster = rosters.load()
    key = store.game_key(g["date"], g["start"], g["home"], g["away"])
    entry = copy.deepcopy((store.load().get("entries") or {}).get(key))
    auto = bi.AutoAnswers(g, parsed, roster, real=lambda p: (_ for _ in ()).throw(bi.ImportAbort("Eingabe nicht erlaubt")), write=_noop)
    con = ei.Console(read=auto, write=_noop)
    plan = ei.build_plan(ei.Session(con), g, entry, roster, ei.cache_reference(g), False)     # False: keine Entfernungen (Automatik entfernt nie)
    try:
        res = ei.execute_plan(g, plan, entry, roster, ei.cache_reference(g), now=now, save_fn=store.save_auto)
    except store.GameStartedError:
        return "skipped"
    if res.get("status") == "skipped":
        return "skipped"
    return "saved" if res.get("status") == "saved" else "unchanged"


def run_once(now: float | None = None, fetch=bi.fetch_json, sleep=time.sleep, pause_seconds: float = bi.PAUSE_SECONDS, games: list | None = None,
             respect_recorder: bool = True) -> dict:
    """Ein Lauf. Rueckgabe {'result': 'OK'|'SKIP'|'WARN'|'ERROR', 'detail': str, 'games': {"Heim - Gast": 'saved'|'unchanged'|'skipped'|'error'}}.
    fetch(pfad) -> dict (wie betano_import.fetch_json; im Test ersetzbar), games = Spieleliste statt Cache (Test)."""
    now = time.time() if now is None else now
    out = {"result": "SKIP", "detail": "", "games": {}}
    src = {"note": ""}

    def done(result, detail):
        detail = src["note"] + detail
        out.update(result=result, detail=detail)
        _log(result, detail, now)
        return out

    lock = job_lock.FileLock(timeout=0.0)
    if not lock.acquire():
        return done("SKIP", "Sperre belegt (anderer Betano-Lauf oder Handabruf)")
    try:
        if respect_recorder and job_lock.is_locked(recorder_lock_path()):
            return done("SKIP", "Recorder läuft (Sperrdatei belegt)")
        st = load_state()
        if st["state"] == "aus":
            return done("SKIP", f"Automatik AUS ({st.get('last_error') or 'unbekannt'}); Freigabe: betano_auto.py --reset")
        if st["state"] == "pause":
            until = datetime.fromisoformat(st["pause_until"]).timestamp() if st.get("pause_until") else 0
            if now < until:
                return done("SKIP", f"Pause bis {st['pause_until']} ({st.get('last_error') or ''})")
        if games is None:
            try:
                games, source = get_schedule(now)
            except ScheduleError as e:
                if e.code in (429, 403, 401):
                    try:
                        _http_stop(urllib.error.HTTPError("", 429 if e.code == 429 else 403, "", {}, None), st, now, "Spielplan (BallDontLie)")
                    except StopRun:
                        out.update(result="ERROR", detail=st.get("last_error") or "gestoppt")
                        return out
                return done("SKIP", f"Spielplan nicht verfügbar ({str(e)[:80]})")
            src["note"] = f"Spielplan: {source}; "
        else:
            src["note"] = "Spielplan: übergeben; "
        todo = games_in_sight(now, games)
        if not todo:
            return done("SKIP", "kein Spiel in Sicht")
        errors, counts = 0, {"saved": 0, "unchanged": 0, "skipped": 0, "error": 0}
        st.update(state="ok", pause_until=None)
        try:
            try:
                payloads = [fetch(bi.LIST_PATH)["data"]]
                events = bi.list_events(payloads)
            except urllib.error.HTTPError as e:
                _http_stop(e, st, now, "Spielliste")
            except Exception as e:
                st.update(last_run=_iso(now), last_error=f"Spielliste: {type(e).__name__}")
                save_state(st)
                return done("ERROR", f"Spielliste nicht lesbar: {type(e).__name__}")
            if not events:
                st.update(last_run=_iso(now), last_error="Spielliste leer")
                save_state(st)
                return done("WARN", "Betano-Spielliste leer")
            for i, g in enumerate(todo):
                name = f"{ei.nick(g['home'])} - {ei.nick(g['away'])}"
                if errors >= MAX_ERRORS:
                    break
                try:
                    ev = bi.match_event(g, events)
                    if ev is None:
                        out["games"][name] = "skipped"
                        counts["skipped"] += 1
                        continue
                    if i:
                        sleep(pause_seconds)
                    data = fetch(f"{ev['url']}{bi.EVENT_REQ}".replace("/quoten/", "/api/quoten/", 1))["data"]
                    r = process_game(g, ev, data, now)
                except urllib.error.HTTPError as e:
                    if e.code in (403, 429):
                        _http_stop(e, st, now, name)
                    errors += 1
                    r = "error"
                    st["last_error"] = f"HTTP {e.code} ({name})"
                except Exception as e:                                  # Timeout, Netz, Formatfehler, Pruefung: nur dieses Spiel
                    errors += 1
                    r = "error"
                    st["last_error"] = f"{type(e).__name__} ({name})"
                out["games"][name] = r
                counts[r] += 1
        except StopRun:                                           # 429/403: Zustand und Protokoll sind in _http_stop schon geschrieben
            out.update(result="ERROR", detail=st.get("last_error") or "gestoppt")
            return out
        st["last_run"] = _iso(now)
        summary = f"{counts['saved']} gespeichert, {counts['unchanged']} unverändert, {counts['skipped']} übersprungen (Hand/ohne Betano-Spiel), {counts['error']} Fehler"
        if errors >= MAX_ERRORS:
            save_state(st)
            return done("ERROR", f"abgebrochen nach {MAX_ERRORS} Fehlern: {summary}")
        if errors:
            save_state(st)
            return done("WARN", summary)
        st["last_error"] = None
        save_state(st)
        return done("OK", summary)
    finally:
        lock.release()


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--reset"]:
        reset()
        print("Betano-Automatik freigegeben (Zustand ok).")
        return 0
    if args:
        print(__doc__)
        return 2
    try:
        res = run_once(respect_recorder=False)          # Betrieb: der Recorder blockiert die Automatik nicht (Entscheidung 31.10.)
    except Exception as e:                                   # nie ohne Spur abbrechen
        alog.log_event(JOB, "ERROR", f"{type(e).__name__}: {e}")
        print(f"Fehler: {type(e).__name__}")
        return 1
    print(f"{res['result']}: {res['detail']}")
    return 1 if res["result"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
