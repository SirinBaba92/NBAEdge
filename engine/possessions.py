from __future__ import annotations

import re

from engine.replay import action_game_seconds


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _score(action: dict) -> tuple[int, int]:
    return (
        _safe_int(action.get("scoreHome")),
        _safe_int(action.get("scoreAway")),
    )


def _action_type(action: dict) -> str:
    return str(action.get("actionType") or "").strip().lower()


def _subtype(action: dict) -> str:
    return str(action.get("subType") or "").strip().lower()


def _description(action: dict) -> str:
    return str(action.get("description") or "").strip().lower()


def _team_id(action: dict):
    team_id = action.get("teamId") or action.get("possession")
    return str(team_id) if team_id else None


def _infer_team_sides(actions: list) -> dict:
    team_sides = {}
    team_ids = []
    prev_home = 0
    prev_away = 0

    for action in actions:
        team_id = _team_id(action)
        if team_id and team_id not in team_ids:
            team_ids.append(team_id)

        home_score, away_score = _score(action)
        if team_id:
            if home_score > prev_home and away_score == prev_away:
                team_sides[team_id] = "home"
            elif away_score > prev_away and home_score == prev_home:
                team_sides[team_id] = "away"

        prev_home, prev_away = home_score, away_score

    known_sides = set(team_sides.values())
    if len(team_ids) == 2 and len(team_sides) == 1:
        known_team = next(iter(team_sides))
        other_side = "away" if "home" in known_sides else "home"
        for team_id in team_ids:
            if team_id != known_team:
                team_sides[team_id] = other_side

    return team_sides


def _team_side(action: dict, team_sides: dict):
    team_id = _team_id(action)
    return team_sides.get(team_id)


def _opponent_side(side: str | None):
    if side == "home":
        return "away"
    if side == "away":
        return "home"
    return None


def _made_field_goal(action: dict) -> bool:
    if _action_type(action) not in {"2pt", "3pt"}:
        return False

    shot_result = str(action.get("shotResult") or "").strip().lower()
    return shot_result == "made" or not _description(action).startswith("miss")


def _turnover(action: dict) -> bool:
    action_type = _action_type(action)
    desc = _description(action)
    return action_type == "turnover" or "shot clock turnover" in desc


def _defensive_rebound(action: dict) -> bool:
    if _action_type(action) != "rebound":
        return False

    subtype = _subtype(action)
    desc = _description(action)
    return "defensive" in subtype or "defensive rebound" in desc


def _last_successful_free_throw(action: dict) -> bool:
    if _action_type(action) != "freethrow":
        return False

    shot_result = str(action.get("shotResult") or "").strip().lower()
    if shot_result != "made":
        return False

    subtype = _subtype(action)
    match = re.search(r"(\d+)\s+of\s+(\d+)", subtype)
    if match:
        return match.group(1) == match.group(2)

    return "free throw" in _description(action)


def _elapsed_minutes(actions: list) -> float:
    if not actions:
        return 0.0

    try:
        elapsed_seconds = max(action_game_seconds(action) for action in actions)
    except Exception:
        elapsed_seconds = 0

    return max(0.0, elapsed_seconds / 60)


def _rating(points: int, possessions: int) -> float:
    if possessions <= 0:
        return 0.0
    return round((points / possessions) * 100, 1)


def estimate_possessions(actions: list) -> dict:
    """
    Schätzt echte Possessions aus Play-by-Play-Actions.
    """
    result = {
        "home_possessions": 0,
        "away_possessions": 0,
        "total_possessions": 0,
        "average_possessions": 0.0,
        "pace_per_48": 0.0,
        "home_off_rating": 0.0,
        "away_off_rating": 0.0,
        "empty_possessions": 0,
        "empty_possessions_recent": 0,
    }

    if not actions:
        return result

    team_sides = _infer_team_sides(actions)
    possession_starts = {"home": 0, "away": 0}
    possession_counts = {"home": 0, "away": 0}
    empty_possessions = 0
    possession_empty_events = []

    for action in actions:
        home_score, away_score = _score(action)
        possession_side = None

        if _made_field_goal(action) or _turnover(action) or _last_successful_free_throw(action):
            possession_side = _team_side(action, team_sides)
        elif _defensive_rebound(action):
            possession_side = _opponent_side(_team_side(action, team_sides))

        if possession_side not in possession_counts:
            continue

        possession_counts[possession_side] += 1
        current_score = home_score if possession_side == "home" else away_score

        is_empty = current_score <= possession_starts[possession_side]
        possession_empty_events.append(is_empty)

        if is_empty:
            empty_possessions += 1

        possession_starts[possession_side] = current_score

    final_home, final_away = _score(actions[-1])
    total_possessions = possession_counts["home"] + possession_counts["away"]
    average_possessions = total_possessions / 2
    empty_possessions_recent = sum(1 for is_empty in possession_empty_events[-20:] if is_empty)
    elapsed_minutes = _elapsed_minutes(actions)
    pace_per_48 = 0.0
    if elapsed_minutes > 0:
        pace_per_48 = round((average_possessions / elapsed_minutes) * 48, 1)

    return {
        "home_possessions": possession_counts["home"],
        "away_possessions": possession_counts["away"],
        "total_possessions": total_possessions,
        "average_possessions": round(average_possessions, 1),
        "pace_per_48": pace_per_48,
        "home_off_rating": _rating(final_home, possession_counts["home"]),
        "away_off_rating": _rating(final_away, possession_counts["away"]),
        "empty_possessions": empty_possessions,
        "empty_possessions_recent": empty_possessions_recent,
    }


def empty_possessions_default(possession_summary: dict | None) -> int:
    if not possession_summary:
        return 0

    if possession_summary.get("empty_possessions_recent") is not None:
        value = possession_summary.get("empty_possessions_recent")
    elif possession_summary.get("empty_possessions") is not None:
        value = possession_summary.get("empty_possessions")
    else:
        value = 0

    try:
        return max(0, min(5, int(value or 0)))
    except Exception:
        return 0
