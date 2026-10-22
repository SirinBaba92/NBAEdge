from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from config.runtime import OFFLINE_AUDIT_MODE

MARKET_HISTORY_DIR = Path("data/market_history")
MOCK_MARKET_LINES = {
    "game_total_line": 225.0,
    "quarter_line": 55.5,
    "home_team_total": 112.5,
    "away_team_total": 112.5,
    "market_source": "MOCK_FALLBACK",
}
MARKET_HISTORY_CACHE = {}

_CACHE = {
    "fetched_at": 0.0,
    "lines": {},
}
_CACHE_TTL_SECONDS = 90


def update_market_history(
    game_key: str,
    market_line: float,
    projection: float,
):
    try:
        market_line = float(market_line)
        projection = float(projection)
    except Exception:
        return

    MARKET_HISTORY_CACHE[str(game_key)] = {
        "last_market_line": market_line,
        "last_projection": projection,
        "last_delta": round(projection - market_line, 1),
        "timestamp": time.time(),
    }


def get_market_history(game_key: str):
    return MARKET_HISTORY_CACHE.get(str(game_key))


def append_market_history_snapshot(
    game_key,
    market_line,
    projection,
    delta,
    movement_signal,
):
    try:
        MARKET_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_line": float(market_line),
            "projection": float(projection),
            "delta": float(delta),
            "movement_signal": str(movement_signal or "NONE"),
        }
        path = _history_path(game_key)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:
        return


def load_market_history(game_key, limit=50):
    try:
        path = _history_path(game_key)
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        rows = []
        for line in lines[-int(limit or 50):]:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows
    except Exception:
        return []


def build_market_movement_signal(
    current_market_line,
    previous_market_line,
    current_projection,
    previous_projection,
    confidence_score,
    stability_score,
) -> dict:
    if previous_market_line is None or previous_projection is None:
        return _empty_movement_signal()

    try:
        market_move = round(float(current_market_line) - float(previous_market_line), 1)
        projection_move = round(float(current_projection) - float(previous_projection), 1)
        confidence = int(confidence_score or 0)
        stability = int(stability_score or 0)
    except Exception:
        return _empty_movement_signal()

    delta_shift = round(projection_move - market_move, 1)
    signal = "NONE"

    if abs(delta_shift) >= 6 and confidence >= 75 and stability >= 75:
        signal = "MARKET_LAG"
    elif abs(market_move) >= 5 and abs(projection_move) <= 2:
        signal = "MARKET_OVERREACTION"
    elif abs(projection_move) >= 5 and abs(market_move) <= 1:
        signal = "LINE_FREEZE"
    elif (market_move > 0 and projection_move < 0) or (
        market_move < 0 and projection_move > 0
    ):
        signal = "REVERSE_STEAM"
    elif abs(market_move) >= 3 and confidence >= 70:
        signal = "STEAM_MOVE"

    return {
        "market_move": market_move,
        "projection_move": projection_move,
        "delta_shift": delta_shift,
        "signal": signal,
    }


def _empty_movement_signal() -> dict:
    return {
        "market_move": 0.0,
        "projection_move": 0.0,
        "delta_shift": 0.0,
        "signal": "NONE",
    }


def _history_path(game_key) -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(game_key or "unknown")).strip("_")
    return MARKET_HISTORY_DIR / f"{safe_key or 'unknown'}.jsonl"


def fetch_live_market_lines(game) -> dict:
    """
    Returns defensive live market lines for dashboard use.

    v1 uses available Odds API totals when possible and derives the dashboard
    quarter line from game total / 4. If no market is available, stable mock
    values are returned.
    """
    fallback = dict(MOCK_MARKET_LINES)
    if not game or OFFLINE_AUDIT_MODE:
        return fallback

    try:
        market = _find_real_market(game)
        if not market:
            return fallback

        game_total = _safe_float(market.get("total"))
        if game_total is None:
            return fallback

        home_total, away_total = _team_totals(game, market, game_total)
        return {
            "game_total_line": game_total,
            "quarter_line": round(game_total / 4.0, 1),
            "home_team_total": home_total,
            "away_team_total": away_total,
            "market_source": "ODDS_API_TOTAL_DERIVED",
        }
    except Exception:
        return fallback


def _find_real_market(game: dict) -> dict | None:
    if not os.getenv("ODDS_API_KEY"):
        return None

    markets = _load_market_cache()
    home_key = _normalize(f"{game.get('home_city', '')} {game.get('home_team', '')}")
    away_key = _normalize(f"{game.get('away_city', '')} {game.get('away_team', '')}")

    return (
        markets.get((home_key, away_key))
        or markets.get((away_key, home_key))
        or markets.get((game.get("home_team", "").lower(), game.get("away_team", "").lower()))
        or markets.get((game.get("away_team", "").lower(), game.get("home_team", "").lower()))
    )


def _load_market_cache() -> dict:
    """Live-Linien NUR aus dem Festplatten-Cache (data/odds_cache.json). Kein Odds-API-Abruf:
    aktualisiert wird ausschliesslich ueber den Knopf bzw. den Auto-Refresh im Live-Tab (app.py)."""
    from data.odds import parse_totals_spreads
    from data.odds_client import get_odds

    res = get_odds("totals_spreads", caller="live_market.cache_only", cache_only=True)
    if not res.data:
        return {}
    if _CACHE["lines"] and _CACHE["fetched_at"] == res.fetched_at:
        return _CACHE["lines"]
    lines = parse_totals_spreads(res.data)
    _CACHE["fetched_at"] = res.fetched_at
    _CACHE["lines"] = lines
    return lines
