"""
Geplanter Odds-Abruf (taeglich 22:00 per launchd, siehe automation/): fuellt data/odds_cache.json.

  cd ~/Desktop/NBAEdge && venv/bin/python fetch_odds_daily.py

- Ein einziger Abruf Totals/Spreads (4 Credits) ueber die zentrale Funktion data/odds_client.get_odds
  (refresh=True, caller="scheduled"): Protokoll data/odds_calls.log, Credit-Schutz und Key-Schutz gelten weiter.
- Kein Abruf (nur Eintrag in odds_calls.log und data/automation.log), wenn
    * die Credits unter ODDS_MIN_CREDITS_RESERVE liegen, oder
    * der Cache juenger als 60 Minuten ist (z. B. weil gerade manuell aktualisiert wurde).
- Bei einem Fehler: 5 Minuten spaeter genau ein weiterer Versuch, danach aufgeben (Ergebnis im Protokoll).
Exit-Code 0 bei OK und uebersprungen, 1 bei Fehler.
"""
import sys
import time

sys.path.insert(0, ".")

from config.settings import ODDS_MIN_CREDITS_RESERVE
from data import automation_log as alog
from data import odds_client as oc

JOB = "fetch_odds_daily"
MIN_CACHE_AGE_SECONDS = 60 * 60
RETRY_WAIT_SECONDS = 5 * 60


def run(sleep=time.sleep, log=print) -> dict:
    info = oc.credits_info()
    if info["low"]:
        reason = f"Credits {info['remaining']} unter Reserve {ODDS_MIN_CREDITS_RESERVE}"
        oc.log_skip("scheduled", "totals_spreads", reason)
        alog.log_event(JOB, "SKIP", reason)
        log(f"Uebersprungen: {reason}")
        return {"result": "SKIP", "reason": reason}

    cached = oc.get_odds("totals_spreads", caller="scheduled.check", cache_only=True)
    if cached.data is not None and cached.age is not None and cached.age < MIN_CACHE_AGE_SECONDS:
        reason = f"Cache jünger als 60 Min. ({oc.describe_age(cached.age)})"
        oc.log_skip("scheduled", "totals_spreads", reason)
        alog.log_event(JOB, "SKIP", reason)
        log(f"Uebersprungen: {reason}")
        return {"result": "SKIP", "reason": reason}

    res = oc.get_odds("totals_spreads", caller="scheduled", refresh=True)
    attempts = 1
    if not res.fetched:
        log(f"Fehler beim ersten Versuch: {res.error}. Neuer Versuch in {RETRY_WAIT_SECONDS // 60} Minuten.")
        sleep(RETRY_WAIT_SECONDS)
        res = oc.get_odds("totals_spreads", caller="scheduled", refresh=True)
        attempts = 2
    if res.fetched:
        detail = f"{len(res.data)} Spiele, noch {res.remaining if res.remaining is not None else '?'} Credits"
        if attempts == 2:
            detail += " (nach Wiederholung)"
        alog.log_event(JOB, "OK", detail)
        log(f"OK: {detail}")
        return {"result": "OK", "attempts": attempts, "remaining": res.remaining}
    detail = f"aufgegeben nach 2 Versuchen: {res.error}"
    alog.log_event(JOB, "ERROR", detail)
    log(f"Fehler: {detail}")
    return {"result": "ERROR", "attempts": attempts, "error": res.error}


def main() -> int:
    try:
        res = run()
    except Exception as e:                      # nie ohne Spur abbrechen; Text wird bereinigt (keine URL, kein Key)
        alog.log_event(JOB, "ERROR", f"{type(e).__name__}: {e}")
        print(f"Fehler: {type(e).__name__}")
        return 1
    return 1 if res["result"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
