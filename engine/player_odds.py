"""
Spieler-Tab, Baustein P1: Buchmacher-Chance aus den Betano-Meilensteinen (Markt "Spielerpunkte"). Reine Logik, keine Oberflaeche, kein Netz, schreibt nichts.

Betano bietet bei Meilensteinen nur die Over-Seite an ("mindestens N Punkte", entspricht Over N - 0,5). Eine Gegenquote fehlt, die Marge laesst sich daher
nicht berechnen: die Chance 1 / Quote ENTHAELT die Buchmacher-Marge (MARGIN_LABEL) und wird nicht korrigiert.

Aufruf der Oberflaeche spaeter:
    game_player_odds(store.load()["entries"], game_key)   -> Spieler eines Spiels mit Zeilen und Warnungen
    milestone_rows(player_block)                          -> Zeilen eines einzelnen Spielerblocks
    implied_probability(odds)                             -> Anteil 0 bis 1 oder None
"""
from __future__ import annotations

import math

from data import pre_match_store as store

MARGIN_LABEL = "Buchmacher-Chance (inkl. Marge)"


def implied_probability(odds) -> float | None:
    """1 / Quote als Anteil 0 bis 1 (inklusive Marge). Ungueltig (fehlt, keine Zahl, nicht endlich, <= 1) -> None."""
    if odds is None or isinstance(odds, bool):
        return None
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 1.0:
        return None
    return 1.0 / value


def _percent(p: float) -> int:
    return int(p * 100 + 0.5)                         # kaufmaennisch gerundet (1,80 -> 55,6 -> 56)


def milestone_rows(entry_player: dict | None) -> list[dict]:
    """Eine Zeile je AKTIVER Meilenstein-Linie, aufsteigend nach Meilenstein: {milestone, over_line, odds, bookmaker, probability, percent}.
    Linien ohne Meilenstein (Einzellinie) und ohne gueltige Quote werden uebersprungen."""
    rows = []
    for line in store.player_lines(entry_player or {}):
        threshold = line.get("threshold")
        p = implied_probability(line.get("odds"))
        if threshold is None or p is None:
            continue
        rows.append({"milestone": int(threshold), "over_line": int(threshold) - 0.5, "odds": float(line["odds"]), "bookmaker": line.get("bookmaker"),
                     "probability": p, "percent": _percent(p)})
    rows.sort(key=lambda r: r["milestone"])
    return rows


def monotonic_warnings(rows: list[dict], player: str = "") -> list[str]:
    """Warnungen, wenn die Chance mit steigendem Meilenstein nicht fallen (hoehere oder gleiche Chance bei hoeherem Meilenstein). Keine Korrektur."""
    out = []
    for low, high in zip(rows, rows[1:]):
        if high["probability"] >= low["probability"]:
            who = f"{player}: " if player else ""
            out.append(f"{who}{high['milestone']}+ (Quote {high['odds']:g}, {high['percent']} %) ist nicht unwahrscheinlicher als "
                       f"{low['milestone']}+ (Quote {low['odds']:g}, {low['percent']} %)")
    return out


def game_player_odds(entries: dict | None, game_key: str) -> list[dict]:
    """Alle aktiven Spieler eines Spiels: {name, team, team_abbreviation, person_id, rows, warnings}, sortiert nach Team, niedrigstem Meilenstein, Name.
    entries = Inhalt von store.load()["entries"]. Spiel oder Spieler fehlen -> leere Liste. Spieler ohne aktive Linie werden weggelassen."""
    entry = (entries or {}).get(game_key)
    out = []
    for block in store.active_player_blocks(entry):
        rows = milestone_rows(block)
        if not rows:
            continue
        name = block.get("name") or ""
        out.append({"name": name, "team": block.get("team"), "team_abbreviation": block.get("team_abbreviation"), "person_id": block.get("person_id"),
                    "rows": rows, "warnings": monotonic_warnings(rows, name)})
    out.sort(key=lambda p: (p["team"] or "", p["rows"][0]["milestone"], p["name"]))
    return out


def game_warnings(players: list[dict]) -> list[str]:
    return [w for p in players for w in p["warnings"]]
