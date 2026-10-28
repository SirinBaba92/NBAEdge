"""Vergangene Spieltage im Tab "Score Projections": rein lesende Aufbereitung des Inhalts von data/tracking/projection_snapshots.json (Parameter `games` = load()["games"]).
Reine Funktionen, ohne Streamlit, ohne Dateizugriff, ohne Netz; nichts wird gespeichert oder abgerufen. Je Spiel: Karte, Tabellen und Ergebnis der letzten Version vor dem Anpfiff."""
from __future__ import annotations

from datetime import date

from data import pre_match_store as store
from data import projection_snapshots as ps

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def day_counts(games: dict, active: date | None = None, active_keys=()) -> list[tuple[date, int, bool]]:
    """Tage fuer die Auswahlliste, aufsteigend: (Tag, Spielzahl, ist_aktiver_Spieltag). Alle Tage mit Spielen im Schnappschuss (Karte und Version vorhanden) und der aktive Spieltag;
    dessen Spielzahl = Schnappschuss-Spiele des Tages plus `active_keys` (Schluessel der geladenen Spiele, ohne Doppelzaehlung)."""
    keys: dict[date, set] = {}
    for key, g in games.items():
        d = _day(g.get("game_date"))
        if d is not None and g.get("card") and ps.final_version(g):
            keys.setdefault(d, set()).add(key)
    if active is not None:
        keys.setdefault(active, set()).update(active_keys)
    return [(d, len(keys[d]), d == active) for d in sorted(keys)]


def day_label(day: date, count: int, is_active: bool) -> str:
    """'Di 27.10. · 4 Spiele' bzw. 'Mi 28.10. · 12 Spiele · aktueller Spieltag'."""
    text = f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')} · {count} {'Spiel' if count == 1 else 'Spiele'}"
    return text + " · aktueller Spieltag" if is_active else text


def neighbours(days: list[date], selected: date | None) -> tuple[date | None, date | None]:
    """(Vortag, Folgetag) in der Liste; None an den Enden (Pfeil deaktiviert) oder wenn `selected` nicht in der Liste steht."""
    if selected not in days:
        return None, None
    i = days.index(selected)
    return (days[i - 1] if i > 0 else None), (days[i + 1] if i + 1 < len(days) else None)


def past_items(games: dict, day: date) -> list[dict]:
    """Alle Spiele des Tages nach Anpfiff (bei gleichem Anpfiff nach Schluessel): {'key', 'card', 'tables', 'result', 'start'}; result None = kein Ergebnis gespeichert."""
    out = []
    for key, g in games.items():
        ver = ps.final_version(g)
        if _day(g.get("game_date")) != day or not g.get("card") or not ver:
            continue
        out.append({"key": key, "card": g["card"], "tables": ver.get("tables"), "result": g.get("result") or None, "team2": ver.get("team2"),
                    "start": g.get("start_utc") or g["card"].get("game_start")})
    inf = float("inf")
    return sorted(out, key=lambda x: ((store.parse_utc(x["start"]) if x["start"] else None) or inf, x["key"]))


def t2_active(team2: dict | None) -> bool:
    """Ausfaelle haben die Prognose veraendert: gespeicherter team2-Block mit Ausfall-Mass != 0 bei mindestens einem Team."""
    return bool(team2 and (team2.get("measure_home") or team2.get("measure_away")))


def card_inputs(item: dict) -> tuple[dict, dict]:
    """(Projektion fuer die Karte, past-Angaben fuer build_card_vm). Mit aktivem team2 gelten dessen gespeicherte Werte (Spread, Punkte, Siegchance; das Total bleibt), sonst die Standard-Prognose.
    past = {'result': (Gast, Heim) | None, 'pred': (Gast, Heim), 't2': bool}. Rechnet nichts neu."""
    card = {k: v for k, v in item["card"].items() if k != "team2"}
    t2 = t2_active(item.get("team2"))
    if t2:
        b = item["team2"]
        card.update(exp_spread=b["exp_spread"], home_score=b["home_score"], away_score=b["away_score"], home_win_prob=b["home_win_prob"], away_win_prob=b["away_win_prob"])
    res = item.get("result")
    result = (int(res["away_points"]), int(res["home_points"])) if res else None
    try:
        pred = (int(round(float(card["away_score"]))), int(round(float(card["home_score"]))))
    except (KeyError, TypeError, ValueError):
        pred = None                                      # keine Prognose gespeichert: die Prognose-Zeile entfaellt
    return card, {"result": result, "pred": pred, "t2": t2}
