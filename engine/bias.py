from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

BIAS_FILE = Path(__file__).resolve().parents[1] / "data" / "bias_adjustments.json"


def load_bias_adjustments() -> dict:
    if not BIAS_FILE.exists():
        return {}
    try:
        return json.loads(BIAS_FILE.read_text())
    except Exception:
        return {}


def save_bias_adjustments(adjustments: dict) -> None:
    BIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BIAS_FILE.write_text(json.dumps(adjustments, indent=2, ensure_ascii=False))


def build_bias_adjustments(team_bias_stats: Dict[str, dict], min_games: int = 2, max_adjustment: float = 6.0) -> dict:
    """Convert observed historical errors into conservative per-team point adjustments.

    If a team is mostly overvalued, future projection receives a negative adjustment.
    If a team is mostly undervalued, future projection receives a positive adjustment.
    """
    result = {}
    for team, stats in team_bias_stats.items():
        games = int(stats.get("games", 0))
        if games < min_games:
            continue
        avg_error = float(stats.get("total_error", 0)) / max(games, 1)
        overvalued = int(stats.get("overvalued", 0))
        undervalued = int(stats.get("undervalued", 0))
        if overvalued == undervalued:
            direction = 0
        elif overvalued > undervalued:
            direction = -1
        else:
            direction = 1
        adjustment = direction * min(max_adjustment, round(avg_error * 0.35, 1))
        result[team] = {
            "adjustment": adjustment,
            "games": games,
            "avg_error": round(avg_error, 1),
            "overvalued": overvalued,
            "undervalued": undervalued,
        }
    return result
