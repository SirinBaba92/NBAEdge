from __future__ import annotations

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


def _is_made_field_goal(action: dict) -> bool:
    if _action_type(action) not in {"2pt", "3pt"}:
        return False

    shot_result = str(action.get("shotResult") or "").strip().lower()
    description = str(action.get("description") or "").strip().lower()
    return shot_result == "made" or not description.startswith("miss")


def _elapsed_minutes_between(start_action: dict, end_action: dict) -> float:
    try:
        seconds = action_game_seconds(end_action) - action_game_seconds(start_action)
    except Exception:
        seconds = 0
    return max(0.0, seconds / 60)


def _recent_run(actions: list) -> tuple[int, int]:
    recent = actions[-15:] if actions else []
    if not recent:
        return 0, 0

    start_home, start_away = _score(recent[0])
    end_home, end_away = _score(recent[-1])
    return max(0, end_home - start_home), max(0, end_away - start_away)


def _lead_changes(actions: list) -> int:
    lead_changes = 0
    previous_leader = None

    for action in actions:
        home_score, away_score = _score(action)
        if home_score > away_score:
            leader = "home"
        elif away_score > home_score:
            leader = "away"
        else:
            continue

        if previous_leader and leader != previous_leader:
            lead_changes += 1
        previous_leader = leader

    return lead_changes


def _scoring_drought_minutes(actions: list) -> float:
    if not actions:
        return 0.0

    last_field_goal = None
    for action in actions:
        if _is_made_field_goal(action):
            last_field_goal = action

    if last_field_goal is None:
        return round(action_game_seconds(actions[-1]) / 60, 2)

    return round(_elapsed_minutes_between(last_field_goal, actions[-1]), 2)


def _scoring_events(actions: list) -> list[tuple[dict, int, int]]:
    events = []
    previous_home = 0
    previous_away = 0

    for action in actions:
        home_score, away_score = _score(action)
        home_delta = max(0, home_score - previous_home)
        away_delta = max(0, away_score - previous_away)
        if home_delta or away_delta:
            events.append((action, home_delta, away_delta))
        previous_home, previous_away = home_score, away_score

    return events


def build_team_run_state(actions: list, selected_team_side: str | None) -> dict:
    """
    Builds the current unanswered run for a selected team side.

    selected_team_side accepts "home", "away" or None. Runs below 5 unanswered
    points are treated as no clear run for live-input defaults.
    """
    result = {
        "run_for_team": 0,
        "run_against_team": 0,
        "run_label": "NONE",
    }
    events = _scoring_events(actions)
    if not events:
        return result

    run_side = None
    run_points = 0

    for _, home_delta, away_delta in reversed(events):
        if home_delta > 0 and away_delta == 0:
            side = "home"
            points = home_delta
        elif away_delta > 0 and home_delta == 0:
            side = "away"
            points = away_delta
        else:
            break

        if run_side is None:
            run_side = side
        elif side != run_side:
            break

        run_points += points

    if not run_side or run_points < 5:
        return result

    selected_side = str(selected_team_side or "").strip().lower()
    if selected_side == run_side:
        return {
            "run_for_team": run_points,
            "run_against_team": 0,
            "run_label": f"FOR {run_points}-0",
        }
    if selected_side in {"home", "away"}:
        return {
            "run_for_team": 0,
            "run_against_team": run_points,
            "run_label": f"AGAINST {run_points}-0",
        }

    return {
        "run_for_team": 0,
        "run_against_team": 0,
        "run_label": f"{run_side.upper()} {run_points}-0",
    }


def _largest_run(actions: list) -> int:
    events = _scoring_events(actions)
    largest = 0
    current_team = None
    current_points = 0

    for _, home_delta, away_delta in events:
        if home_delta > 0 and away_delta == 0:
            team = "home"
            points = home_delta
        elif away_delta > 0 and home_delta == 0:
            team = "away"
            points = away_delta
        else:
            current_team = None
            current_points = 0
            continue

        if team == current_team:
            current_points += points
        else:
            current_team = team
            current_points = points

        largest = max(largest, current_points)

    return largest


def _volatility_score(actions: list, largest_run: int, lead_changes: int) -> float:
    if not actions:
        return 0.0

    events = _scoring_events(actions[-30:])
    quick_swings = 0
    previous_team = None

    for _, home_delta, away_delta in events:
        team = "home" if home_delta > away_delta else "away"
        points = max(home_delta, away_delta)
        if previous_team and team != previous_team and points >= 3:
            quick_swings += 1
        previous_team = team

    start_home, start_away = _score(actions[0])
    end_home, end_away = _score(actions[-1])
    elapsed_minutes = max(0.1, action_game_seconds(actions[-1]) / 60)
    points_per_minute = ((end_home + end_away) - (start_home + start_away)) / elapsed_minutes

    score = 0.0
    score += min(4.0, lead_changes * 0.8)
    score += min(3.0, largest_run / 4)
    score += min(3.0, quick_swings * 0.75)
    if points_per_minute >= 5:
        score += 2.0
    elif points_per_minute >= 4:
        score += 1.0

    return round(score, 1)


def _momentum_signal(home_run: int, away_run: int, drought: float, volatility: float) -> str:
    if home_run >= 10:
        return "HOME_SURGE"
    if away_run >= 10:
        return "AWAY_SURGE"
    if drought >= 3.5:
        return "OFFENSE_COLLAPSE"
    if volatility >= 8:
        return "HIGH_VOLATILITY"
    return "STABLE"


def _momentum_factor(signal: str) -> float:
    factor = 1.0

    if signal in {"HOME_SURGE", "AWAY_SURGE"}:
        factor += 0.04
    elif signal == "HIGH_VOLATILITY":
        factor += 0.03
    elif signal == "OFFENSE_COLLAPSE":
        factor -= 0.06

    return max(0.90, min(1.10, factor))


def analyze_momentum(actions: list) -> dict:
    home_run, away_run = _recent_run(actions)
    largest_run = _largest_run(actions)
    drought = _scoring_drought_minutes(actions)
    lead_changes = _lead_changes(actions)
    volatility = _volatility_score(actions, largest_run, lead_changes)
    signal = _momentum_signal(home_run, away_run, drought, volatility)
    factor = _momentum_factor(signal)

    return {
        "home_run": home_run,
        "away_run": away_run,
        "largest_run": largest_run,
        "scoring_drought_minutes": drought,
        "lead_changes": lead_changes,
        "volatility_score": volatility,
        "momentum_signal": signal,
        "momentum_factor": factor,
    }
