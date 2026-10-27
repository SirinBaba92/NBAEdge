"""
Vorab-Linien: Die Projektion (Marktmischung fuer Spread und Total) darf nur die Linie nutzen, die VOR dem Anpfiff galt.

Erkennung einer Live-Linie (siehe Antwort in PHASE-Bericht / Chat):
  Jedes Event der Odds API hat `commence_time` (geplanter Anpfiff), jeder Bookmaker und jeder Markt ein `last_update`.
  Ein Abruf-Schnappschuss gilt als LIVE, wenn
    * der Abrufzeitpunkt (fetched_at) >= commence_time ist, oder
    * irgendein last_update > commence_time ist.
  Sonst sind es Vorab-Linien.

Gespeichert wird die letzte Vorab-Linie je Event in data/pregame_lines.json (jeder erfolgreiche Odds-Abruf und jede
Cache-Auswertung vor dem Anpfiff aktualisiert sie, danach nicht mehr). Fuer Spiele, die schon laufen, kommt die Linie
aus diesem Speicher; fehlt sie, gibt es keine Marktlinie (reines Modell).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HORIZON_HOURS = 72        # nur Spiele der naechsten 3 Tage speichern
KEEP_DAYS = 14            # Eintraege nach 14 Tagen verwerfen
MATCH_TOLERANCE_HOURS = 6 # Anpfiff laut BallDontLie und Odds API duerfen so weit auseinanderliegen


def store_path() -> Path:
    return Path(os.environ.get("NBAEDGE_PREGAME_LINES") or ROOT / "data" / "pregame_lines.json")


def parse_utc(text) -> float | None:
    """ISO-Zeit (mit Z oder Offset) -> Epoch-Sekunden; None bei ungueltigem Wert."""
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_live_snapshot(event: dict, fetched_at: float) -> bool:
    """True, wenn die Linien dieses Events im Schnappschuss (abgerufen um fetched_at) Live-Linien sein koennen."""
    commence = parse_utc(event.get("commence_time"))
    if commence is None:
        return True                      # unklar -> vorsichtshalber nicht als Vorab-Linie behandeln
    if fetched_at >= commence:
        return True
    for b in event.get("bookmakers", []):
        for ts in [b.get("last_update")] + [m.get("last_update") for m in b.get("markets", [])]:
            lu = parse_utc(ts) if ts else None
            if lu is not None and lu > commence:
                return True
    return False


def event_lines(event: dict) -> dict | None:
    """Gemittelte Linien eines Events (gleiche Rechnung wie parse_totals_spreads) oder None ohne Total und Spread."""
    from data.odds import parse_totals_spreads
    parsed = parse_totals_spreads([event])
    lines = next(iter(parsed.values()), None)
    if not lines or (lines.get("total") is None and lines.get("spread") is None):
        return None
    return lines


def _event_id(ev: dict) -> str:
    return str(ev.get("id") or f"{ev.get('commence_time')}|{ev.get('home_team')}|{ev.get('away_team')}")


def _load() -> dict:
    try:
        d = json.loads(store_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(store: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def update_from_snapshot(events: list[dict], fetched_at: float, now: float | None = None) -> int:
    """Speichert die Vorab-Linien aller noch nicht gestarteten Events der naechsten HORIZON_HOURS Stunden.
    Idempotent: ein Eintrag wird nur durch einen neueren Vorab-Schnappschuss ersetzt. Gibt die Zahl der Aenderungen zurueck."""
    now = now or time.time()
    store = _load()
    changed = 0
    for ev in events or []:
        commence = parse_utc(ev.get("commence_time"))
        if commence is None or is_live_snapshot(ev, fetched_at) or commence - now > HORIZON_HOURS * 3600:
            continue
        lines = event_lines(ev)
        if lines is None:
            continue
        key = _event_id(ev)
        old = store.get(key)
        if old is None or old.get("fetched_at", 0) < fetched_at:
            store[key] = {"commence": commence, "home_team": ev["home_team"], "away_team": ev["away_team"],
                          "fetched_at": fetched_at, "lines": lines}
            changed += 1
    stale = [k for k, v in store.items() if v.get("commence", 0) < now - KEEP_DAYS * 86400]
    for k in stale:
        del store[k]
    if changed or stale:
        _save(store)
    return changed


def _kw(name: str) -> str:
    return (name or "").split()[-1].lower() if name else ""


def _pick(cands: list, key_time, game_start: float | None, now: float):
    """Waehlt den Kandidaten, dessen Anpfiff zum Spiel passt (sonst den naechstliegenden zu jetzt)."""
    if not cands:
        return None
    if game_start is not None:
        best = min(cands, key=lambda c: abs(key_time(c) - game_start))
        return best if abs(key_time(best) - game_start) <= MATCH_TOLERANCE_HOURS * 3600 else None
    cands = [c for c in cands if key_time(c) >= now - 12 * 3600] or cands
    return min(cands, key=lambda c: abs(key_time(c) - now))


def _orient(lines: dict, home: str) -> dict:
    """Linien aus Sicht des Heimteams `home`: ist das Event vertauscht (Heim/Gast der Odds API umgekehrt), werden
    Spread-Vorzeichen (positiv = Heim stark), Spread-Quoten und Teamnamen mitgedreht."""
    if _kw(lines.get("home_team")) == _kw(home):
        return lines
    out = dict(lines, home_team=lines.get("away_team"), away_team=lines.get("home_team"),
               spread_home_odds=lines.get("spread_away_odds"), spread_away_odds=lines.get("spread_home_odds"))
    for k in ("spread", "spread_home_point"):
        if lines.get(k) is not None:
            out[k] = -lines[k] + 0.0
    return out


def line_for_game_ex(events: list[dict], fetched_at: float | None, home: str, away: str,
                     game_start: float | None = None, now: float | None = None) -> tuple[dict | None, str | None, float | None]:
    """Vorab-Linie fuer ein Spiel: (Linien-Dict wie parse_totals_spreads, Quelle, Zeitpunkt der Linie) oder (None, None, None).
    Zeitpunkt = Abrufzeit des Schnappschusses (Cache) bzw. des gespeicherten Eintrags.
    Quelle: 'cache_vorab' (Schnappschuss vor dem Anpfiff), 'gespeichert' (letzte Vorab-Linie aus data/pregame_lines.json)."""
    now = now or time.time()
    hk, ak = _kw(home), _kw(away)

    def teams_match(h, a):
        return (_kw(h) == hk and _kw(a) == ak) or (_kw(h) == ak and _kw(a) == hk)   # wie bisher auch vertauscht

    cands = [e for e in events or [] if teams_match(e.get("home_team"), e.get("away_team")) and parse_utc(e.get("commence_time")) is not None]
    ev = _pick(cands, lambda e: parse_utc(e["commence_time"]), game_start, now)
    if ev is not None and fetched_at is not None and not is_live_snapshot(ev, fetched_at):
        lines = event_lines(ev)
        if lines is not None:
            return _orient(lines, home), "cache_vorab", fetched_at

    store = _load()
    scands = [(k, v) for k, v in store.items() if teams_match(v.get("home_team"), v.get("away_team"))]
    if ev is not None and ev.get("id") is not None and _event_id(ev) in store:
        entry = store[_event_id(ev)]
    else:
        picked = _pick(scands, lambda kv: kv[1]["commence"], game_start, now)
        entry = picked[1] if picked else None
    if entry is not None:
        lines = dict(entry["lines"], home_team=entry.get("home_team"), away_team=entry.get("away_team"))
        return _orient(lines, home), "gespeichert", entry.get("fetched_at")
    return None, None, None


def line_for_game(events: list[dict], fetched_at: float | None, home: str, away: str,
                  game_start: float | None = None, now: float | None = None) -> tuple[dict | None, str | None]:
    """Wie line_for_game_ex, aber nur (Linien-Dict, Quelle) wie bisher."""
    lines, source, _at = line_for_game_ex(events, fetched_at, home, away, game_start, now)
    return lines, source
