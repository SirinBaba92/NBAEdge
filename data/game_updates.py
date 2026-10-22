"""Abruf neuer, beendeter Spiele fuer das taegliche Fortschreiben (update_model.py).

Datum: BallDontLie fuehrt Spiele unter dem US-Spieldatum (Ostkueste). Das Zeitfenster wird deshalb
mit der Datumsgrenze America/New_York gebildet, nicht mit date.today() der deutschen Systemzeit.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

US_TZ = ZoneInfo("America/New_York")


def us_today() -> date:
    return datetime.now(US_TZ).date()


def fetch_final_games(start: date, end: date) -> list[dict]:
    """Beendete Spiele (status == 'Final', nicht verschoben) von start bis end (inklusive, US-Datum)."""
    from data.fetcher import _get, _is_finished   # _get behandelt 429 mit Wartezeit und Wiederholung

    games, cursor = [], None
    while True:
        params = {"start_date": start.isoformat(), "end_date": end.isoformat(), "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("games", params)
        games.extend(g for g in data.get("data", []) if _is_finished(g))
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1.0)
    return games
