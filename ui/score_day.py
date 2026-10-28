"""Spieltag-Logik fuer den Tab "Score Projections": welcher US-Spieltag gerade angezeigt wird. Reine Funktionen, ohne Streamlit, ohne Dateizugriff, ohne Netz.

Aktiv ist der fruehste US-Spieltag (Datum in New York), an dem mindestens ein Spiel noch nicht beendet ist. Als beendet zaehlt ein Spiel bei BallDontLie-Status "Final", bei einem
Ergebnis im Schnappschuss, bei Live-Feed FINAL und bei verschobenen, abgesagten oder abgebrochenen Spielen (die blockieren den Wechsel nie). Notausstieg: Ein Spieltag D gilt
spaetestens ab 08:00 Uhr deutscher Zeit am Kalendertag nach D als abgeschlossen. Es aendert sich nur, welche Karten gezeigt werden; Prognosen und gespeicherte Daten bleiben unberuehrt.

Ein Spiel ist ein dict mit: "date" (US-Spieltag 'YYYY-MM-DD', BallDontLie-Feld date), optional "start" (Anpfiff UTC, ersatzweise fuer das Datum), "status" (BallDontLie-Status),
"has_result" (Ergebnis im Schnappschuss) und "feed_status" (GameView.status des Live-Feeds)."""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
CLOSE_HOUR = 8                                          # 08:00 deutscher Zeit am Kalendertag nach dem US-Spieltag
_VOID = ("postpone", "cancel", "abandon", "abort", "suspend", "forfeit")      # verschoben / abgesagt / abgebrochen


def _parse_utc(text) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def game_day(game: dict) -> date | None:
    """US-Spieltag des Spiels: das Feld date, sonst das Datum des Anpfiffs in New York; None, wenn beides fehlt."""
    try:
        return date.fromisoformat(str(game.get("date"))[:10])
    except ValueError:
        pass
    start = _parse_utc(game.get("start"))
    return start.astimezone(NEW_YORK).date() if start else None


def is_done(game: dict) -> bool:
    """Beendet im Sinne des Spieltag-Wechsels (siehe Modulkopf)."""
    status = str(game.get("status") or "").strip().lower()
    return (status == "final" or any(w in status for w in _VOID) or bool(game.get("has_result")) or str(game.get("feed_status") or "").upper() == "FINAL")


def day_closed(day: date, now: datetime) -> bool:
    """Notausstieg: ab 08:00 deutscher Zeit am Tag nach `day` gilt der Spieltag als abgeschlossen."""
    return now >= datetime.combine(day + timedelta(days=1), dtime(CLOSE_HOUR), tzinfo=BERLIN)


def active_day(games: list[dict], now) -> date | None:
    """Aktiver US-Spieltag oder None. `now`: Unix-Zeit (float) oder datetime (ohne Zeitzone gilt UTC)."""
    if isinstance(now, datetime):
        now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    else:
        now_dt = datetime.fromtimestamp(float(now), timezone.utc)
    days = sorted({d for d in (game_day(g) for g in games) if d is not None})
    for day in days:
        if day_closed(day, now_dt):
            continue
        if any(not is_done(g) for g in games if game_day(g) == day):
            return day
    return None


def display_day(games: list[dict], now, other_days=()) -> date | None:
    """Tag, den der Tab zeigt: der aktive Spieltag; gibt es keinen (alles beendet), der zuletzt gespielte Tag unter den geladenen Spielen und `other_days` (Tage beendeter
    Schnappschuss-Karten), bis ein neuer Spieltag mit Spielen geladen ist. None nur, wenn es gar keinen Tag gibt."""
    active = active_day(games, now)
    if active is not None:
        return active
    days = [d for d in (game_day(g) for g in games) if d is not None] + [d for d in other_days if d is not None]
    return max(days) if days else None
