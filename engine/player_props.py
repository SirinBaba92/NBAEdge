from __future__ import annotations


BLOWOUT_FACTORS = {
    "normal": 1.00,
    "risk": 0.94,
    "high": 0.88,
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_ts(value: float) -> float:
    ts = float(value or 0.0)
    if 0 < ts <= 1:
        return ts * 100
    return ts


def project_player_points_prop(
    season_ppg: float,
    last5_ppg: float,
    expected_minutes: float,
    season_minutes: float,
    team_pace_factor: float = 1.0,
    opponent_defense_factor: float = 1.0,
    blowout_risk: str = "normal",
    playoff_mode: bool = False,
    line: float = 0.0,
    season_fga: float = 0.0,
    last5_fga: float = 0.0,
    season_fta: float = 0.0,
    last5_fta: float = 0.0,
    season_ts: float = 0.0,
    last5_ts: float = 0.0,
) -> dict:
    base = (float(season_ppg) * 0.55) + (float(last5_ppg) * 0.45)
    season_minutes = float(season_minutes)
    minutes_factor = (
        float(expected_minutes) / season_minutes if season_minutes > 0 else 1.0
    )

    season_fga = float(season_fga)
    last5_fga = float(last5_fga)
    season_fta = float(season_fta)
    last5_fta = float(last5_fta)
    has_fga_data = season_fga > 0 or last5_fga > 0
    has_fta_data = season_fta > 0 or last5_fta > 0
    usage_score = (last5_fga * 0.70) + (last5_fta * 0.90)
    season_usage_score = (season_fga * 0.70) + (season_fta * 0.90)
    usage_ratio = (
        usage_score / season_usage_score if season_usage_score > 0 else 1.0
    )
    usage_ratio = _clamp(usage_ratio, 0.85, 1.15)

    if not has_fta_data:
        fta_factor = 1.00
    elif last5_fta >= 7:
        fta_factor = 1.06
    elif last5_fta >= 4:
        fta_factor = 1.03
    elif last5_fta <= 1:
        fta_factor = 0.93
    else:
        fta_factor = 1.00

    normalized_last5_ts = _normalize_ts(last5_ts)
    normalized_season_ts = _normalize_ts(season_ts)
    if normalized_last5_ts >= 70:
        ts_factor = 0.94
    elif 0 < normalized_last5_ts <= 45:
        ts_factor = 1.04
    else:
        ts_factor = 1.00

    blowout_key = str(blowout_risk or "normal").lower()
    blowout_factor = BLOWOUT_FACTORS.get(blowout_key, BLOWOUT_FACTORS["normal"])

    projected_points = (
        base
        * minutes_factor
        * float(team_pace_factor)
        * float(opponent_defense_factor)
        * usage_ratio
        * fta_factor
        * ts_factor
        * blowout_factor
    )

    if playoff_mode:
        projected_points *= 0.97

    line = float(line)
    difference = projected_points - line
    if difference >= 2.5:
        lean = "OVER"
    elif -difference >= 2.5:
        lean = "UNDER"
    else:
        lean = "NO_EDGE"

    edge_conf = abs(difference) * 10
    if last5_fga >= 15:
        usage_conf = 12
    elif last5_fga >= 10:
        usage_conf = 7
    elif has_fga_data and last5_fga < 7:
        usage_conf = -8
    else:
        usage_conf = 0

    if last5_fta >= 6:
        fta_conf = 10
    elif last5_fta >= 3:
        fta_conf = 4
    elif has_fta_data and last5_fta <= 1:
        fta_conf = -8
    else:
        fta_conf = 0

    if normalized_last5_ts >= 70:
        volatility_penalty = -10
    elif 0 < normalized_last5_ts <= 42:
        volatility_penalty = -8
    else:
        volatility_penalty = 0

    confidence = _clamp(
        edge_conf + usage_conf + fta_conf + volatility_penalty, 0, 100
    )

    return {
        "projected_points": round(projected_points, 1),
        "line": round(line, 1),
        "difference": round(difference, 1),
        "lean": lean,
        "confidence": round(confidence, 0),
        "base": round(base, 2),
        "minutes_factor": round(minutes_factor, 3),
        "team_pace_factor": float(team_pace_factor),
        "opponent_defense_factor": float(opponent_defense_factor),
        "usage_score": round(usage_score, 2),
        "season_usage_score": round(season_usage_score, 2),
        "usage_ratio": round(usage_ratio, 3),
        "fta_factor": round(fta_factor, 3),
        "ts_factor": round(ts_factor, 3),
        "season_ts": round(normalized_season_ts, 1),
        "last5_ts": round(normalized_last5_ts, 1),
        "confidence_components": {
            "edge_conf": round(edge_conf, 1),
            "usage_conf": usage_conf,
            "fta_conf": fta_conf,
            "volatility_penalty": volatility_penalty,
        },
        "model_version": "v2",
        "blowout_risk": blowout_key if blowout_key in BLOWOUT_FACTORS else "normal",
        "blowout_factor": blowout_factor,
        "playoff_mode": bool(playoff_mode),
    }
