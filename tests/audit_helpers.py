from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.mock_loader import load_mock_scoreboard
from engine.live import QuarterProjectionInput, live_quarter_projection
from engine.live_context import build_live_context
from engine.replay import clock_to_seconds

REPLAY_MINUTES = [5, 10, 15, 20, 30, 40]
VALID_EDGE_SIGNALS = {
    "STRONG_OVER_EDGE",
    "OVER_EDGE",
    "NO_EDGE",
    "UNDER_EDGE",
    "STRONG_UNDER_EDGE",
    "TRAP_OVER",
    "UNSTABLE",
}
VALID_MOMENTUM_SIGNALS = {
    "HOME_SURGE",
    "AWAY_SURGE",
    "OFFENSE_COLLAPSE",
    "HIGH_VOLATILITY",
    "STABLE",
}


def has_bad_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isnan(float(value)) or math.isinf(float(value))
    if isinstance(value, dict):
        return any(has_bad_number(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(has_bad_number(item) for item in value)
    return False


def build_audit_row(minute: int) -> dict:
    games = load_mock_scoreboard()
    if not games:
        raise AssertionError("mock_scoreboard.json contains no games")

    context = build_live_context(
        games[0],
        "MOCK",
        replay_mode=True,
        replay_minute=minute,
    )
    snapshot = context["snapshot"]
    quarter = int(context.get("quarter") or 1)
    q_points = context["q_points"]
    foul_state = context["replay_foul_state"]
    team_fouls = context["team_fouls"]
    possession = context["possession_summary"]
    momentum = context["momentum_summary"]
    recent = context["recent_pbp_summary"]

    seconds_left = clock_to_seconds(context.get("clock"))
    projected = live_quarter_projection(
        QuarterProjectionInput(
            line=55.5,
            current_total_points=int(q_points["quarter_total"]),
            seconds_left_in_quarter=seconds_left,
            pregame_game_total=225.0,
            quarter=quarter,
            pace_mode="normal",
            team_fouls_a=int(team_fouls["home_team_fouls"]),
            team_fouls_b=int(team_fouls["away_team_fouls"]),
            game_state="close",
            recent_total_points_last_2min=int(recent["points"]),
            empty_possessions=int(possession["empty_possessions_recent"]),
            pbp_signal=recent["pace_signal"],
            possession_pace_per_48=possession["pace_per_48"],
            possession_empty_count=possession["empty_possessions_recent"],
            possession_off_rating=_average_off_rating(possession),
            momentum_signal=momentum["momentum_signal"],
            momentum_factor=momentum["momentum_factor"],
        )
    )

    return {
        "minute": minute,
        "snapshot": snapshot,
        "quarter_points": q_points,
        "foul_state": foul_state,
        "team_fouls": team_fouls,
        "possession": possession,
        "momentum": momentum,
        "context": context,
        "projection": projected,
    }


def validate_audit_row(row: dict) -> list[str]:
    problems = []
    snapshot = row["snapshot"]
    q_points = row["quarter_points"]
    foul_state = row["foul_state"]
    team_fouls = row["team_fouls"]
    possession = row["possession"]
    momentum = row["momentum"]
    projection = row["projection"]

    quarter = int(snapshot.get("period") or 0)
    if quarter < 1 or quarter > 4:
        problems.append(f"invalid quarter: {quarter}")
    if snapshot.get("clock") in (None, ""):
        problems.append("missing clock")
    if int(snapshot.get("score_home") or 0) < 0 or int(snapshot.get("score_away") or 0) < 0:
        problems.append("negative score")

    for key in ["home_q_points", "away_q_points", "quarter_total"]:
        if int(q_points.get(key) or 0) < 0:
            problems.append(f"negative quarter points: {key}")

    for key in ["home_team_fouls", "away_team_fouls"]:
        fouls = int(team_fouls.get(key) or 0)
        if fouls < 0 or fouls > 20:
            problems.append(f"implausible team fouls: {key}={fouls}")
    for quarter_fouls in foul_state.get("team_fouls", {}).values():
        for team, fouls in quarter_fouls.items():
            if int(fouls) < 0 or int(fouls) > 20:
                problems.append(f"implausible replay foul count: {team}={fouls}")

    pace = float(possession.get("pace_per_48") or 0)
    if int(possession.get("home_possessions") or 0) < 0 or int(possession.get("away_possessions") or 0) < 0:
        problems.append("negative possessions")
    if pace < 0 or pace > 150:
        problems.append(f"impossible pace: {pace}")
    if row["minute"] >= 5 and pace <= 0:
        problems.append(f"missing pace after minute {row['minute']}: {pace}")

    signal = momentum.get("momentum_signal")
    factor = float(momentum.get("momentum_factor") or 0)
    if signal not in VALID_MOMENTUM_SIGNALS:
        problems.append(f"invalid momentum signal: {signal}")
    if factor < 0.90 or factor > 1.10:
        problems.append(f"momentum factor out of bounds: {factor}")

    master = float(projection.get("master_live_factor") or 0)
    if master < 0.90 or master > 1.10:
        problems.append(f"master factor out of bounds: {master}")
    edge_signal = projection.get("edge_signal")
    edge_strength = float(projection.get("edge_strength") or -1)
    if edge_signal not in VALID_EDGE_SIGNALS:
        problems.append(f"invalid edge signal: {edge_signal}")
    if edge_strength < 0 or edge_strength > 100:
        problems.append(f"edge strength out of bounds: {edge_strength}")

    projected_total = float(projection.get("projected_quarter_total") or -1)
    if projected_total < 0:
        problems.append(f"negative projection: {projected_total}")
    if has_bad_number(row):
        problems.append("NaN or infinite numeric value detected")

    return problems


def run_full_audit() -> list[dict]:
    rows = []
    for minute in REPLAY_MINUTES:
        row = build_audit_row(minute)
        row["problems"] = validate_audit_row(row)
        rows.append(row)
    return rows


def _average_off_rating(possession: dict) -> float:
    ratings = [
        float(possession.get("home_off_rating") or 0),
        float(possession.get("away_off_rating") or 0),
    ]
    ratings = [rating for rating in ratings if rating > 0]
    if not ratings:
        return 0.0
    return sum(ratings) / len(ratings)
