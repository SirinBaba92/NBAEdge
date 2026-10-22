from __future__ import annotations

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.balldontlie.io/v1"


def _default_season_averages() -> dict:
    return {"season_ppg": 0.0, "season_minutes": 0.0, "games_played": 0}


def _default_last_games() -> dict:
    return {"last5_ppg": 0.0, "last5_minutes": 0.0, "games": 0}


def _api_key() -> str | None:
    return os.getenv("BALLDONTLIE_API_KEY")


def _headers() -> dict:
    key = _api_key()
    return {"Authorization": key} if key else {}


def _get(endpoint: str, params: dict | None = None, retries: int = 2) -> dict:
    if not _api_key():
        return {}

    for attempt in range(retries + 1):
        try:
            response = requests.get(
                f"{BASE}/{endpoint}",
                headers=_headers(),
                params=params,
                timeout=15,
            )
            if response.status_code == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            if response.status_code != 200:
                return {}
            return response.json()
        except Exception:
            return {}
    return {}


def _to_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _minutes_to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return _to_float(minutes) + (_to_float(seconds) / 60)
    return _to_float(text)


def search_players(query: str) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    data = _get("players", {"search": query, "per_page": 25})
    players = []
    for player in data.get("data", []) or []:
        first_name = player.get("first_name") or ""
        last_name = player.get("last_name") or ""
        full_name = f"{first_name} {last_name}".strip() or player.get("full_name") or ""
        team = player.get("team") or {}
        team_name = team.get("full_name") or team.get("abbreviation") or ""
        try:
            player_id = int(player.get("id"))
        except (TypeError, ValueError):
            continue
        players.append(
            {
                "id": player_id,
                "full_name": full_name,
                "team": team_name,
            }
        )
    return players


def fetch_player_season_averages(player_id: int, season: int) -> dict:
    params = {
        "season": int(season),
        "player_ids[]": int(player_id),
    }
    data = _get("season_averages", params)
    rows = data.get("data", []) or []
    if not rows:
        return _default_season_averages()

    row = rows[0]
    return {
        "season_ppg": round(_to_float(row.get("pts")), 1),
        "season_minutes": round(_minutes_to_float(row.get("min")), 1),
        "games_played": int(_to_float(row.get("games_played"))),
    }


def fetch_player_last_games(player_id: int, season: int, limit: int = 5) -> dict:
    params = {
        "seasons[]": int(season),
        "player_ids[]": int(player_id),
        "per_page": min(max(int(limit), 1), 25),
    }
    data = _get("stats", params)
    rows = data.get("data", []) or []
    rows = sorted(
        rows,
        key=lambda row: ((row.get("game") or {}).get("date") or ""),
        reverse=True,
    )[:limit]

    if not rows:
        return _default_last_games()

    games = len(rows)
    points = sum(_to_float(row.get("pts")) for row in rows)
    minutes = sum(_minutes_to_float(row.get("min")) for row in rows)
    return {
        "last5_ppg": round(points / games, 1),
        "last5_minutes": round(minutes / games, 1),
        "games": games,
    }
