from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Optional


def parse_clock_to_seconds(value) -> int:
    """Accepts values like '6:34', '40.8', '6', or numeric seconds and returns seconds left."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value))))
    text = str(value).strip()
    if not text:
        return 0
    if ":" in text:
        parts = text.split(":", 1)
        try:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return max(0, int(round(minutes * 60 + seconds)))
        except ValueError:
            return 0
    try:
        # If user writes 6.5 we treat it as seconds, not minutes. For minutes use 6:30.
        return max(0, int(round(float(text))))
    except ValueError:
        return 0


def format_seconds(seconds: int) -> str:
    seconds = max(0, int(round(seconds)))
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


def build_game_state(
    score_home: int,
    score_away: int,
    quarter: int,
    clock: str,
) -> str:
    try:
        score_diff = abs(int(score_home) - int(score_away))
        quarter = int(quarter)
    except Exception:
        return "normal"

    seconds_left = parse_clock_to_seconds(clock)

    if score_diff <= 6:
        return "close"
    if score_diff >= 18 and quarter >= 3:
        return "blowout"
    if score_diff >= 14 and quarter == 4 and seconds_left <= 6 * 60:
        return "blowout"
    return "normal"


def build_pace_mode(pace_per_48: float | None) -> str:
    try:
        pace = float(pace_per_48 or 0)
    except Exception:
        return "normal"

    if pace <= 0:
        return "normal"
    if pace < 92:
        return "slow"
    if pace <= 101:
        return "normal"
    if pace <= 108:
        return "fast"
    return "chaotic"


@dataclass
class LiveProjectionInput:
    pregame_team_total: float
    current_points: int
    quarter: int
    seconds_left_in_quarter: int
    team_in_bonus: bool = False
    opponent_team_fouls: int = 0
    pace_mode: str = "normal"  # slow, normal, fast, chaotic
    game_state: str = "close"  # close, normal, blowout
    recent_run_for_team: int = 0
    recent_run_against_team: int = 0
    empty_possessions: int = 0
    key_player_foul_trouble: bool = False
    pbp_signal: str = "NORMAL"
    possession_pace_per_48: float | None = None
    possession_empty_count: int = 0
    possession_off_rating: float | None = None
    momentum_signal: str = "STABLE"
    momentum_factor: float = 1.0
    selected_team_side: str | None = None
    betting_line: float | None = None


@dataclass
class QuarterProjectionInput:
    line: float
    current_total_points: int
    seconds_left_in_quarter: int
    pregame_game_total: float = 225.0
    quarter: int = 1
    pace_mode: str = "normal"
    team_fouls_a: int = 0
    team_fouls_b: int = 0
    close_game: bool = True
    game_state: str = "close"
    recent_total_points_last_2min: int = 0
    empty_possessions: int = 0
    overtime_risk: bool = False
    pbp_signal: str = "NORMAL"
    possession_pace_per_48: float | None = None
    possession_empty_count: int = 0
    possession_off_rating: float | None = None
    momentum_signal: str = "STABLE"
    momentum_factor: float = 1.0


@dataclass
class QuarterTeamTotalInput:
    line: float
    current_team_points_q: int
    seconds_left_in_quarter: int
    pregame_team_total: float = 112.5
    quarter: int = 1
    pace_mode: str = "normal"
    opponent_team_fouls: int = 0
    team_in_bonus: bool = False
    game_state: str = "close"
    recent_run_for_team: int = 0
    recent_run_against_team: int = 0
    empty_possessions: int = 0
    key_player_foul_trouble: bool = False
    pbp_signal: str = "NORMAL"
    possession_pace_per_48: float | None = None
    possession_empty_count: int = 0
    possession_off_rating: float | None = None
    momentum_signal: str = "STABLE"
    momentum_factor: float = 1.0
    selected_team_side: str | None = None


def elapsed_minutes(quarter: int, seconds_left_in_quarter: int) -> float:
    quarter = max(1, min(int(quarter), 4))
    seconds_left_in_quarter = max(0, min(int(seconds_left_in_quarter), 12 * 60))
    elapsed_seconds = (quarter - 1) * 12 * 60 + (12 * 60 - seconds_left_in_quarter)
    return elapsed_seconds / 60


def quarter_elapsed_minutes(seconds_left_in_quarter: int) -> float:
    seconds_left = max(0, min(int(seconds_left_in_quarter), 12 * 60))
    return (12 * 60 - seconds_left) / 60


def _pace_factor(mode: str) -> float:
    return {
        "very slow": 0.88,
        "slow": 0.94,
        "normal": 1.00,
        "fast": 1.07,
        "very fast": 1.13,
        "chaotic": 1.13,
    }.get(str(mode).lower(), 1.0)


def _game_state_factor(game_state: str, quarter: int) -> float:
    state = str(game_state).lower()
    if state == "blowout":
        return 0.93 if int(quarter) == 4 else 0.97
    if state == "close":
        return 1.05 if int(quarter) == 4 else 1.02
    return 1.0


def _momentum_factor(run_for: int = 0, run_against: int = 0, empty_possessions: int = 0) -> float:
    factor = 1.0
    if run_for >= 12:
        factor += 0.06
    elif run_for >= 8:
        factor += 0.035
    elif run_for >= 5:
        factor += 0.02
    if run_against >= 10:
        factor -= 0.035
    elif run_against >= 6:
        factor -= 0.02
    factor -= min(max(empty_possessions, 0), 5) * 0.015
    return max(0.86, min(1.16, factor))


def _team_foul_factor(team_fouls: int, in_bonus: bool) -> float:
    fouls = min(max(int(team_fouls), 0), 5)
    factor = 1.0 + fouls * 0.012
    if in_bonus or fouls >= 5:
        factor += 0.07
    elif fouls == 4:
        factor += 0.035
    return factor



def _pbp_signal_factor(signal: str) -> float:
    """Modifier from recent play-by-play signal."""
    signal = str(signal or "NORMAL").upper()

    if signal == "FREE_THROW_HEAVY":
        return 1.055
    if signal == "SCORING_BURST":
        return 1.045
    if signal == "OFFENSE_STUCK":
        return 0.94

    return 1.0


def _possession_factor(pace_per_48=None, empty_count=0, off_rating=None) -> float:
    factor = 1.0

    try:
        pace = float(pace_per_48) if pace_per_48 is not None else None
    except Exception:
        pace = None

    try:
        empty = int(empty_count or 0)
    except Exception:
        empty = 0

    try:
        rating = float(off_rating) if off_rating is not None else None
    except Exception:
        rating = None

    if pace is not None:
        if pace >= 105:
            factor += 0.05
        elif pace >= 100:
            factor += 0.03
        elif pace <= 88:
            factor -= 0.06
        elif pace <= 92:
            factor -= 0.04

    if empty >= 14:
        factor -= 0.06
    elif empty >= 10:
        factor -= 0.04

    if rating is not None:
        if rating >= 120:
            factor += 0.04
        elif rating >= 110:
            factor += 0.02
        elif rating <= 85:
            factor -= 0.05
        elif rating <= 95:
            factor -= 0.03

    return max(0.88, min(1.12, factor))


def _safe_momentum_factor(value: float) -> float:
    try:
        factor = float(value)
    except Exception:
        factor = 1.0
    return max(0.90, min(1.10, factor))


def _team_specific_momentum_factor(
    selected_team_side: str | None,
    momentum_signal: str,
    base_factor: float,
) -> float:
    factor = _safe_momentum_factor(base_factor)
    side = str(selected_team_side or "").strip().lower()
    signal = str(momentum_signal or "STABLE").strip().upper()

    if signal == "HOME_SURGE":
        if side == "home":
            factor += 0.03
        elif side == "away":
            factor -= 0.02
    elif signal == "AWAY_SURGE":
        if side == "away":
            factor += 0.03
        elif side == "home":
            factor -= 0.02

    return max(0.88, min(1.12, factor))


def _build_master_live_factor(
    pbp_factor: float,
    possession_factor: float,
    momentum_factor: float,
) -> dict:
    master_factor = (
        pbp_factor * 0.45
        + possession_factor * 0.35
        + momentum_factor * 0.20
    )

    stability_score = 100
    if abs(pbp_factor - possession_factor) > 0.08:
        stability_score -= 15
    if abs(momentum_factor - possession_factor) > 0.08:
        stability_score -= 10
    if abs(pbp_factor - momentum_factor) > 0.08:
        stability_score -= 10
    stability_score = max(40, min(100, stability_score))

    confidence_score = 50
    factors = [pbp_factor, possession_factor, momentum_factor]
    if all(factor > 1.02 for factor in factors):
        confidence_score += 20
    if all(factor < 0.98 for factor in factors):
        confidence_score += 20
    if stability_score >= 85:
        confidence_score += 10
    if stability_score <= 60:
        confidence_score -= 10
    confidence_score = max(0, min(100, confidence_score))

    return {
        "master_live_factor": round(master_factor, 3),
        "stability_score": stability_score,
        "confidence_score": confidence_score,
    }


def _build_edge_detection(
    projected_total: float,
    betting_line: float,
    master_factor: float,
    confidence_score: int,
    stability_score: int,
    pbp_factor: float,
    possession_factor: float,
    momentum_factor: float,
) -> dict:
    edge_value = projected_total - betting_line

    if stability_score <= 55:
        edge_signal = "UNSTABLE"
    elif master_factor > 1.03 and possession_factor < 0.96:
        edge_signal = "TRAP_OVER"
    elif (
        edge_value >= 8
        and confidence_score >= 65
        and stability_score >= 75
    ):
        edge_signal = "STRONG_OVER_EDGE"
    elif edge_value >= 4 and confidence_score >= 55:
        edge_signal = "OVER_EDGE"
    elif (
        edge_value <= -8
        and confidence_score >= 65
        and stability_score >= 75
    ):
        edge_signal = "STRONG_UNDER_EDGE"
    elif edge_value <= -4 and confidence_score >= 55:
        edge_signal = "UNDER_EDGE"
    else:
        edge_signal = "NO_EDGE"

    edge_strength = abs(edge_value) * 5
    edge_strength += confidence_score * 0.3
    edge_strength += stability_score * 0.2
    edge_strength = max(0, min(100, edge_strength))
    if edge_signal == "NO_EDGE":
        edge_strength = min(edge_strength, 40)

    return {
        "edge_signal": edge_signal,
        "edge_strength": round(edge_strength, 0),
        "edge_value": round(edge_value, 1),
    }


def live_team_total_projection(data: LiveProjectionInput) -> dict:
    elapsed = elapsed_minutes(data.quarter, data.seconds_left_in_quarter)
    remaining = max(0.0, 48.0 - elapsed)

    current_rate = data.pregame_team_total / 48.0 if elapsed <= 0 else data.current_points / elapsed
    pregame_rate = data.pregame_team_total / 48.0

    live_weight = 0.62 if elapsed >= 18 else 0.50 if elapsed >= 8 else 0.35
    projected_rate = (current_rate * live_weight) + (pregame_rate * (1 - live_weight))
    projected_rate *= _pace_factor(data.pace_mode)
    projected_rate *= _team_foul_factor(data.opponent_team_fouls, data.team_in_bonus)
    projected_rate *= _game_state_factor(data.game_state, data.quarter)
    projected_rate *= _momentum_factor(data.recent_run_for_team, data.recent_run_against_team, data.empty_possessions)
    if data.key_player_foul_trouble:
        projected_rate *= 1.025

    pbp_factor = _pbp_signal_factor(data.pbp_signal)
    possession_factor = _possession_factor(
        data.possession_pace_per_48,
        data.possession_empty_count,
        data.possession_off_rating,
    )
    momentum_factor = _safe_momentum_factor(data.momentum_factor)
    team_momentum_factor = _team_specific_momentum_factor(
        data.selected_team_side,
        data.momentum_signal,
        momentum_factor,
    )
    master_live = _build_master_live_factor(
        pbp_factor,
        possession_factor,
        team_momentum_factor,
    )
    projected_rate *= master_live["master_live_factor"]

    projected_remaining_points = projected_rate * remaining
    projected_final = data.current_points + projected_remaining_points
    betting_line = data.betting_line if data.betting_line is not None else data.pregame_team_total
    edge_detection = _build_edge_detection(
        projected_final,
        float(betting_line),
        master_live["master_live_factor"],
        master_live["confidence_score"],
        master_live["stability_score"],
        pbp_factor,
        possession_factor,
        team_momentum_factor,
    )

    return {
        "elapsed_minutes": round(elapsed, 2),
        "remaining_minutes": round(remaining, 2),
        "current_rate_per_min": round(current_rate, 3),
        "pregame_rate_per_min": round(pregame_rate, 3),
        "projected_rate_per_min": round(projected_rate, 3),
        "projected_remaining_points": round(projected_remaining_points, 1),
        "projected_final_points": round(projected_final, 1),
        "possession_factor": round(possession_factor, 2),
        "possession_pace_per_48": data.possession_pace_per_48,
        "possession_empty_count": data.possession_empty_count,
        "possession_off_rating": data.possession_off_rating,
        "momentum_signal": data.momentum_signal,
        "momentum_factor": round(momentum_factor, 2),
        "team_momentum_factor": round(team_momentum_factor, 2),
        "selected_team_side": data.selected_team_side,
        "pbp_signal": data.pbp_signal,
        "pbp_signal_factor": round(pbp_factor, 3),
        **master_live,
        **edge_detection,
    }


def live_quarter_projection(data: QuarterProjectionInput) -> dict:
    seconds_left = max(0, min(int(data.seconds_left_in_quarter), 12 * 60))
    elapsed_minutes_q = quarter_elapsed_minutes(seconds_left)
    remaining_minutes_q = seconds_left / 60

    base_quarter_total = data.pregame_game_total / 4.0
    if int(data.quarter) == 4:
        base_quarter_total *= 1.02

    pregame_q_rate = base_quarter_total / 12.0
    live_q_rate = pregame_q_rate if elapsed_minutes_q <= 0 else data.current_total_points / elapsed_minutes_q

    if elapsed_minutes_q < 3:
        live_weight = 0.35
    elif elapsed_minutes_q < 6:
        live_weight = 0.50
    elif elapsed_minutes_q < 9:
        live_weight = 0.65
    else:
        live_weight = 0.78

    projected_rate = (live_q_rate * live_weight) + (pregame_q_rate * (1 - live_weight))
    projected_rate *= _pace_factor(data.pace_mode)
    projected_rate *= _game_state_factor(data.game_state, data.quarter)

    max_fouls = max(data.team_fouls_a, data.team_fouls_b)
    min_fouls = min(data.team_fouls_a, data.team_fouls_b)
    bonus_factor = 1.0
    if max_fouls >= 5 and min_fouls >= 5:
        bonus_factor += 0.11
    elif max_fouls >= 5:
        bonus_factor += 0.06
    elif max_fouls == 4:
        bonus_factor += 0.035
    projected_rate *= bonus_factor

    # Recent pace: if last ~2 minutes had lots of scoring, nudge up.
    if data.recent_total_points_last_2min >= 12:
        projected_rate *= 1.06
    elif data.recent_total_points_last_2min >= 8:
        projected_rate *= 1.035
    elif data.recent_total_points_last_2min <= 2 and elapsed_minutes_q >= 4:
        projected_rate *= 0.97

    projected_rate *= _momentum_factor(empty_possessions=data.empty_possessions)

    pbp_factor = _pbp_signal_factor(data.pbp_signal)
    possession_factor = _possession_factor(
        data.possession_pace_per_48,
        data.possession_empty_count,
        data.possession_off_rating,
    )
    momentum_factor = _safe_momentum_factor(data.momentum_factor)
    master_live = _build_master_live_factor(
        pbp_factor,
        possession_factor,
        momentum_factor,
    )
    projected_rate *= master_live["master_live_factor"]

    if data.overtime_risk and int(data.quarter) == 4:
        projected_rate *= 1.02

    projected_remaining = projected_rate * remaining_minutes_q
    projected_quarter_total = data.current_total_points + projected_remaining
    needed_for_over = max(0.0, (data.line + 0.5) - data.current_total_points)
    margin = projected_quarter_total - data.line
    edge_detection = _build_edge_detection(
        projected_quarter_total,
        data.line,
        master_live["master_live_factor"],
        master_live["confidence_score"],
        master_live["stability_score"],
        pbp_factor,
        possession_factor,
        momentum_factor,
    )

    return {
        "quarter": int(data.quarter),
        "elapsed_minutes_q": round(elapsed_minutes_q, 2),
        "remaining_minutes_q": round(remaining_minutes_q, 2),
        "current_q_rate": round(live_q_rate, 3),
        "pregame_q_rate": round(pregame_q_rate, 3),
        "projected_q_rate": round(projected_rate, 3),
        "projected_remaining_q_points": round(projected_remaining, 1),
        "projected_quarter_total": round(projected_quarter_total, 1),
        "needed_for_over": round(needed_for_over, 1),
        "margin_to_line": round(margin, 1),
        "lean": lean_from_margin(margin),
        "over_probability": over_probability(projected_quarter_total, data.line),
        "possession_factor": round(possession_factor, 2),
        "possession_pace_per_48": data.possession_pace_per_48,
        "possession_empty_count": data.possession_empty_count,
        "possession_off_rating": data.possession_off_rating,
        "momentum_signal": data.momentum_signal,
        "momentum_factor": round(momentum_factor, 2),
        "pbp_signal": data.pbp_signal,
        "pbp_signal_factor": round(pbp_factor, 3),
        **master_live,
        **edge_detection,
    }


def live_quarter_team_total_projection(data: QuarterTeamTotalInput) -> dict:
    seconds_left = max(0, min(int(data.seconds_left_in_quarter), 12 * 60))
    elapsed_minutes_q = quarter_elapsed_minutes(seconds_left)
    remaining_minutes_q = seconds_left / 60

    # Team quarter baseline from full-game team total.
    base_q_team_total = data.pregame_team_total / 4.0
    if int(data.quarter) == 4:
        base_q_team_total *= 1.02
    pregame_q_rate = base_q_team_total / 12.0
    live_q_rate = pregame_q_rate if elapsed_minutes_q <= 0 else data.current_team_points_q / elapsed_minutes_q

    if elapsed_minutes_q < 3:
        live_weight = 0.38
    elif elapsed_minutes_q < 6:
        live_weight = 0.55
    elif elapsed_minutes_q < 9:
        live_weight = 0.70
    else:
        live_weight = 0.82

    projected_rate = (live_q_rate * live_weight) + (pregame_q_rate * (1 - live_weight))
    projected_rate *= _pace_factor(data.pace_mode)
    projected_rate *= _team_foul_factor(data.opponent_team_fouls, data.team_in_bonus)
    projected_rate *= _game_state_factor(data.game_state, data.quarter)
    projected_rate *= _momentum_factor(data.recent_run_for_team, data.recent_run_against_team, data.empty_possessions)
    if data.key_player_foul_trouble:
        projected_rate *= 1.025

    pbp_factor = _pbp_signal_factor(data.pbp_signal)
    possession_factor = _possession_factor(
        data.possession_pace_per_48,
        data.possession_empty_count,
        data.possession_off_rating,
    )
    momentum_factor = _safe_momentum_factor(data.momentum_factor)
    team_momentum_factor = _team_specific_momentum_factor(
        data.selected_team_side,
        data.momentum_signal,
        momentum_factor,
    )
    master_live = _build_master_live_factor(
        pbp_factor,
        possession_factor,
        team_momentum_factor,
    )
    projected_rate *= master_live["master_live_factor"]

    projected_remaining = projected_rate * remaining_minutes_q
    projected_q_team_total = data.current_team_points_q + projected_remaining
    needed_for_over = max(0.0, (data.line + 0.5) - data.current_team_points_q)
    margin = projected_q_team_total - data.line
    edge_detection = _build_edge_detection(
        projected_q_team_total,
        data.line,
        master_live["master_live_factor"],
        master_live["confidence_score"],
        master_live["stability_score"],
        pbp_factor,
        possession_factor,
        team_momentum_factor,
    )

    return {
        "quarter": int(data.quarter),
        "elapsed_minutes_q": round(elapsed_minutes_q, 2),
        "remaining_minutes_q": round(remaining_minutes_q, 2),
        "current_q_team_rate": round(live_q_rate, 3),
        "pregame_q_team_rate": round(pregame_q_rate, 3),
        "projected_q_team_rate": round(projected_rate, 3),
        "projected_remaining_q_team_points": round(projected_remaining, 1),
        "projected_quarter_team_total": round(projected_q_team_total, 1),
        "needed_for_over": round(needed_for_over, 1),
        "margin_to_line": round(margin, 1),
        "lean": lean_from_margin(margin),
        "over_probability": over_probability(projected_q_team_total, data.line),
        "possession_factor": round(possession_factor, 2),
        "possession_pace_per_48": data.possession_pace_per_48,
        "possession_empty_count": data.possession_empty_count,
        "possession_off_rating": data.possession_off_rating,
        "momentum_signal": data.momentum_signal,
        "momentum_factor": round(momentum_factor, 2),
        "team_momentum_factor": round(team_momentum_factor, 2),
        "selected_team_side": data.selected_team_side,
        "pbp_signal": data.pbp_signal,
        "pbp_signal_factor": round(pbp_factor, 3),
        **master_live,
        **edge_detection,
    }


def lean_from_margin(margin: float) -> str:
    if margin >= 7:
        return "STRONG OVER"
    if margin >= 3:
        return "OVER"
    if margin > -3:
        return "COINFLIP"
    if margin > -7:
        return "UNDER"
    return "STRONG UNDER"


def over_probability(projected_final: float, target_line: float) -> int:
    margin = projected_final - target_line
    if margin >= 10:
        return 88
    if margin >= 6:
        return 78
    if margin >= 3:
        return 66
    if margin >= 0:
        return 55
    if margin >= -3:
        return 44
    if margin >= -6:
        return 32
    return 20
