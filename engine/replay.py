from __future__ import annotations


REPLAY_FOUL_SUBTYPES = {
    "personal",
    "shooting",
    "loose ball",
    "offensive",
}


def clock_to_seconds(raw_clock) -> int:
    """
    NBA Clock wie PT08M09.00S oder 8:09 in Sekunden Restzeit umwandeln.
    """
    if raw_clock is None:
        return 0

    text = str(raw_clock)

    if text.startswith("PT"):
        try:
            mins = int(text.split("PT")[1].split("M")[0])
            secs = int(float(text.split("M")[1].replace("S", "")))
            return mins * 60 + secs
        except Exception:
            return 0

    if ":" in text:
        try:
            m, s = text.split(":", 1)
            return int(m) * 60 + int(float(s))
        except Exception:
            return 0

    try:
        return int(float(text))
    except Exception:
        return 0


def action_game_seconds(action: dict) -> int:
    """
    Gibt vergangene Spielsekunden einer Play-by-Play-Aktion zurück.
    Q1 Start = 0
    Q4 Ende = 2880
    """
    period = int(action.get("period") or 1)
    clock = action.get("clock")

    seconds_left = clock_to_seconds(clock)
    elapsed_in_period = 12 * 60 - seconds_left

    return ((period - 1) * 12 * 60) + elapsed_in_period


def filter_actions_until(actions: list, max_game_seconds: int) -> list:
    """
    Gibt alle Aktionen bis zu einem Replay-Zeitpunkt zurück.
    """
    return [a for a in actions if action_game_seconds(a) <= max_game_seconds]


def build_replay_snapshot(actions: list, max_game_seconds: int) -> dict:
    """
    Baut einen Snapshot aus Play-by-Play bis zu einem bestimmten Zeitpunkt.
    """
    filtered = filter_actions_until(actions, max_game_seconds)

    score_home = 0
    score_away = 0
    period = 1
    clock = "12:00"

    if filtered:
        last = filtered[-1]
        score_home = int(last.get("scoreHome") or 0)
        score_away = int(last.get("scoreAway") or 0)
        period = int(last.get("period") or 1)
        clock = last.get("clock") or "PT12M00.00S"

    return {
        "actions": filtered,
        "score_home": score_home,
        "score_away": score_away,
        "period": period,
        "clock": clock,
        "game_seconds": max_game_seconds,
    }


def _action_score(action: dict):
    try:
        return int(action.get("scoreHome") or 0), int(action.get("scoreAway") or 0)
    except Exception:
        return None


def build_replay_quarter_points(actions: list, quarter: int) -> dict:
    """
    Berechnet Quarter-Punkte aus bereits gefilterten Replay-Actions.

    Die Werte entstehen aus der Differenz zwischen dem Score zu Quarter-Start
    und dem letzten bekannten Score im ausgewählten Quarter.
    """
    result = {
        "home_q_points": 0,
        "away_q_points": 0,
        "quarter_total": 0,
    }

    try:
        target_quarter = int(quarter)
    except Exception:
        return result

    quarter_actions = []
    for action in actions:
        try:
            period = int(action.get("period") or 0)
        except Exception:
            continue

        if period == target_quarter:
            quarter_actions.append(action)

    if not quarter_actions:
        return result

    start_home = 0
    start_away = 0
    for action in actions:
        try:
            period = int(action.get("period") or 0)
        except Exception:
            continue

        if period < target_quarter:
            score = _action_score(action)
            if score is not None:
                start_home, start_away = score

    current_home = start_home
    current_away = start_away
    for action in quarter_actions:
        score = _action_score(action)
        if score is not None:
            current_home, current_away = score

    home_q_points = max(0, current_home - start_home)
    away_q_points = max(0, current_away - start_away)

    return {
        "home_q_points": home_q_points,
        "away_q_points": away_q_points,
        "quarter_total": home_q_points + away_q_points,
    }


def _is_replay_foul_action(action: dict) -> bool:
    """
    True für Foul-Aktionen, die im Replay-Foul-State zählen sollen.
    """
    action_type = str(action.get("actionType") or "").strip().lower()
    if action_type != "foul":
        return False

    subtype = str(action.get("subType") or "").strip().lower()
    if subtype in REPLAY_FOUL_SUBTYPES:
        return True

    description = str(action.get("description") or "").lower()
    return any(f"{subtype} foul" in description for subtype in REPLAY_FOUL_SUBTYPES)


def build_current_team_fouls_from_pbp(actions: list, current_quarter: int) -> dict:
    """
    Zählt Team Fouls im aktuellen Quarter aus Play-by-Play-Actions.
    Technische Fouls werden möglichst ausgeschlossen.
    """
    result = {
        "home_team_fouls": 0,
        "away_team_fouls": 0,
        "team_fouls_by_tricode": {},
    }

    try:
        target_quarter = int(current_quarter)
    except Exception:
        return result

    team_fouls_by_tricode = {}
    team_ids = []
    team_sides = {}
    prev_home = 0
    prev_away = 0

    for action in actions:
        try:
            period = int(action.get("period") or 0)
        except Exception:
            continue

        team_id = action.get("teamId")
        team_tricode = action.get("teamTricode") or str(team_id or "UNKNOWN")

        score = _action_score(action)
        if score is not None and team_tricode != "UNKNOWN":
            home_score, away_score = score
            if home_score > prev_home and away_score == prev_away:
                team_sides[team_tricode] = "home"
            elif away_score > prev_away and home_score == prev_home:
                team_sides[team_tricode] = "away"
            prev_home, prev_away = home_score, away_score

        if period != target_quarter:
            continue

        if team_tricode not in team_ids:
            team_ids.append(team_tricode)

        if not _is_replay_foul_action(action):
            continue

        subtype = str(action.get("subType") or "").strip().lower()
        description = str(action.get("description") or "").strip().lower()
        if "technical" in subtype or "technical foul" in description:
            continue

        team_fouls_by_tricode[team_tricode] = team_fouls_by_tricode.get(team_tricode, 0) + 1

    result["team_fouls_by_tricode"] = team_fouls_by_tricode

    for team_tricode, side in team_sides.items():
        if side == "home":
            result["home_team_fouls"] = int(team_fouls_by_tricode.get(team_tricode, 0))
        elif side == "away":
            result["away_team_fouls"] = int(team_fouls_by_tricode.get(team_tricode, 0))

    if result["home_team_fouls"] == 0 and team_ids:
        result["home_team_fouls"] = int(team_fouls_by_tricode.get(team_ids[0], 0))
    if result["away_team_fouls"] == 0 and len(team_ids) > 1:
        result["away_team_fouls"] = int(team_fouls_by_tricode.get(team_ids[1], 0))

    return result


def build_replay_foul_state(actions: list) -> dict:
    """
    Baut historische Foul-Zähler aus Replay-Play-by-Play-Actions.

    Rückgabe:
    {
        "player_fouls": {
            "<personId>": {
                "player": "...",
                "team": "...",
                "team_id": ...,
                "fouls": 0,
            }
        },
        "team_fouls": {
            1: {"CLE": 0, "DET": 0},
            ...
        },
    }
    """
    player_fouls = {}
    team_fouls = {}

    for action in actions:
        if not _is_replay_foul_action(action):
            continue

        person_id = action.get("personId")
        if not person_id:
            continue

        player_key = str(person_id)
        player_name = (
            action.get("playerNameI")
            or action.get("playerName")
            or f"Player {player_key}"
        )
        team = action.get("teamTricode") or str(action.get("teamId") or "UNKNOWN")
        team_id = action.get("teamId")
        period = int(action.get("period") or 1)

        if player_key not in player_fouls:
            player_fouls[player_key] = {
                "player": player_name,
                "team": team,
                "team_id": team_id,
                "fouls": 0,
            }

        player_fouls[player_key]["fouls"] += 1
        team_fouls.setdefault(period, {})
        team_fouls[period][team] = team_fouls[period].get(team, 0) + 1

    return {
        "player_fouls": player_fouls,
        "team_fouls": team_fouls,
    }
