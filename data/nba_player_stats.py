from __future__ import annotations

from typing import Any


def _default_base_stats() -> dict:
    return {
        "gp": 0,
        "minutes": 0.0,
        "ppg": 0.0,
        "fga": 0.0,
        "fta": 0.0,
        "ts": 0.0,
    }


def _default_last_games() -> dict:
    return {
        "games": 0,
        "minutes": 0.0,
        "ppg": 0.0,
        "fga": 0.0,
        "fta": 0.0,
        "ts": 0.0,
    }


def _to_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    return int(_to_float(value))


def _minutes_to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return _to_float(minutes) + (_to_float(seconds) / 60.0)
    return _to_float(text)


def _ts_to_percent(value: Any) -> float:
    ts = _to_float(value)
    if 0 < ts <= 1:
        ts *= 100.0
    return round(ts, 1) if ts > 0 else 0.0


def _season_to_nba_format(season: str | int) -> str:
    text = str(season or "").strip()
    if "-" in text:
        return text
    try:
        start_year = int(text)
    except ValueError:
        return text
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _row_value(row: dict, *keys: str) -> Any:
    upper_row = {str(key).upper(): value for key, value in row.items()}
    for key in keys:
        if key in row:
            return row[key]
        value = upper_row.get(key.upper())
        if value is not None:
            return value
    return None


def _data_frame_rows(data_set: Any) -> list[dict]:
    try:
        frame = data_set.get_data_frame()
        if frame is None or frame.empty:
            return []
        return frame.to_dict("records")
    except Exception:
        return []


def _calculate_ts(points: float, fga: float, fta: float) -> float:
    denominator = 2.0 * (fga + (0.44 * fta))
    if denominator <= 0:
        return 0.0
    return round((points / denominator) * 100.0, 1)


def search_nba_players(query: str) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    try:
        from nba_api.stats.static import players
    except Exception:
        return []

    query_lower = query.lower()
    try:
        found_players = players.find_players_by_full_name(query)
        if not found_players:
            found_players = [
                player
                for player in players.get_players()
                if query_lower in str(player.get("full_name", "")).lower()
            ]
    except Exception:
        return []

    results = []
    seen_ids = set()
    for player in found_players or []:
        try:
            player_id = int(player.get("id"))
        except (TypeError, ValueError):
            continue
        if player_id in seen_ids:
            continue
        full_name = str(player.get("full_name") or "").strip()
        if not full_name:
            continue
        seen_ids.add(player_id)
        results.append({"id": player_id, "full_name": full_name})
    return results


def fetch_player_base_stats(player_id: int, season: str, season_type: str) -> dict:
    try:
        from nba_api.stats.endpoints import playerdashboardbygeneralsplits
    except Exception:
        return _default_base_stats()

    nba_season = _season_to_nba_format(season)
    season_type = season_type if season_type in ("Regular Season", "Playoffs") else "Regular Season"

    try:
        base_endpoint = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
            player_id=int(player_id),
            season=nba_season,
            season_type_playoffs=season_type,
            measure_type_detailed="Base",
            timeout=20,
        )
        base_rows = _data_frame_rows(base_endpoint.overall_player_dashboard)
    except Exception:
        return _default_base_stats()

    if not base_rows:
        return _default_base_stats()

    base_row = base_rows[0]
    gp = _to_int(_row_value(base_row, "GP"))
    if gp <= 0:
        return _default_base_stats()

    total_minutes = _minutes_to_float(_row_value(base_row, "MIN"))
    total_points = _to_float(_row_value(base_row, "PTS"))
    total_fga = _to_float(_row_value(base_row, "FGA"))
    total_fta = _to_float(_row_value(base_row, "FTA"))
    result = {
        "gp": gp,
        "minutes": round(total_minutes / gp, 1),
        "ppg": round(total_points / gp, 1),
        "fga": round(total_fga / gp, 1),
        "fta": round(total_fta / gp, 1),
        "ts": 0.0,
    }

    try:
        advanced_endpoint = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
            player_id=int(player_id),
            season=nba_season,
            season_type_playoffs=season_type,
            measure_type_detailed="Advanced",
            timeout=20,
        )
        advanced_rows = _data_frame_rows(advanced_endpoint.overall_player_dashboard)
        if advanced_rows:
            result["ts"] = _ts_to_percent(_row_value(advanced_rows[0], "TS_PCT"))
    except Exception:
        result["ts"] = 0.0

    return result


def fetch_player_last_games(
    player_id: int, season: str, season_type: str, limit: int = 5
) -> dict:
    try:
        from nba_api.stats.endpoints import playergamelog
    except Exception:
        return _default_last_games()

    nba_season = _season_to_nba_format(season)
    season_type = season_type if season_type in ("Regular Season", "Playoffs") else "Regular Season"
    limit = min(max(int(limit or 5), 1), 25)

    try:
        endpoint = playergamelog.PlayerGameLog(
            player_id=int(player_id),
            season=nba_season,
            season_type_all_star=season_type,
            timeout=20,
        )
        rows = _data_frame_rows(endpoint.player_game_log)
    except Exception:
        return _default_last_games()

    if not rows:
        return _default_last_games()

    rows = rows[:limit]
    games = len(rows)
    points = sum(_to_float(_row_value(row, "PTS")) for row in rows)
    minutes = sum(_minutes_to_float(_row_value(row, "MIN")) for row in rows)
    fga = sum(_to_float(_row_value(row, "FGA")) for row in rows)
    fta = sum(_to_float(_row_value(row, "FTA")) for row in rows)
    ts_values = [_ts_to_percent(_row_value(row, "TS_PCT")) for row in rows]
    ts_values = [value for value in ts_values if value > 0]
    ts = (
        round(sum(ts_values) / len(ts_values), 1)
        if ts_values
        else _calculate_ts(points, fga, fta)
    )

    return {
        "games": games,
        "minutes": round(minutes / games, 1),
        "ppg": round(points / games, 1),
        "fga": round(fga / games, 1),
        "fta": round(fta / games, 1),
        "ts": ts,
    }
