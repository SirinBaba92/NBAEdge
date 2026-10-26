"""Reihenfolge der Karten im Tab "Score Projections": nicht begonnene Spiele zuerst, dann laufende, dann beendete; je Gruppe nach Anpfiff aufsteigend, bei gleichem Anpfiff bleibt die bisherige
Reihenfolge (Eingabe-Reihenfolge, in app.py nach |Spread|). Der Status kommt aus dem Live-Feed-Stand (ohne Abruf), sonst wie im Tab Pre-Match aus Uhrzeit und BallDontLie-Status
(ui/pre_match_tab.game_state). Reine Funktionen, ohne Streamlit."""
from __future__ import annotations

from data import pre_match_store as store
from ui.pre_match_tab import game_state

PRE, LIVE, FINAL = 0, 1, 2
_FEED = {"PRE": PRE, "LIVE": LIVE, "PAUSE": LIVE, "FINAL": FINAL}
_TIME = {"vorab": PRE, "läuft": LIVE, "beendet": FINAL}


def status_group(start_utc, bdl_status, now: float, feed_status: str | None = None) -> int:
    """0 = nicht begonnen, 1 = laeuft, 2 = beendet. feed_status: GameView.status des Live-Feeds (PRE/LIVE/PAUSE/FINAL), falls das Spiel dort steht; unbekannt zaehlt als nicht begonnen."""
    if feed_status in _FEED:
        return _FEED[feed_status]
    return _TIME.get(game_state(start_utc, bdl_status, now), PRE)


def order(items: list, group_of, start_of) -> list:
    """Stabil nach (Gruppe, Anpfiff); items in der bisherigen Reihenfolge uebergeben."""
    def key(x):
        ts = store.parse_utc(start_of(x)) if start_of(x) else None
        return (group_of(x), ts if ts is not None else float("inf"))
    return sorted(items, key=key)
