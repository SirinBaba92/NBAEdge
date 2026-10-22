from __future__ import annotations

from datetime import date, datetime
from typing import Any

from config.settings import ELO_TO_SPREAD_FACTOR
from engine import line_probabilities as lp


PLAYOFF_START_MONTH_DAY = (4, 15)
PLAYOFF_END_MONTH_DAY = (6, 25)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except Exception:
            try:
                return date.fromisoformat(value[:10])
            except Exception:
                return None
    return None


def is_playoff_date(value: Any) -> bool:
    d = _as_date(value)
    if not d:
        return False
    start = date(d.year, *PLAYOFF_START_MONTH_DAY)
    end = date(d.year, *PLAYOFF_END_MONTH_DAY)
    return start <= d <= end


def get_team_bias_adjustment(team: str, bias_adjustments: dict | None) -> float:
    if not bias_adjustments:
        return 0.0
    data = bias_adjustments.get(team) or {}
    return float(data.get("adjustment", 0.0) or 0.0)


def compute_projection(
    pred: dict,
    market_total: float | None = None,
    market_spread: float | None = None,
    game_date: Any = None,
    is_playoff: bool | None = None,
    bias_adjustments: dict | None = None,
) -> dict:
    """Build score projection from model, market and optional self-correction.

    Spread-Konvention: positiv = Heimteam ist Favorit (gilt fuer model_spread, exp_spread
    und market_spread). Der Odds-API-Spread wird in data/odds.py beim Einlesen umgedreht.

    model_total: raw model total before market/playoff/bias
    exp_total: final total used for projected score
    market_diff: absolute raw model vs Vegas total difference
    """
    home = pred["home_team"]
    away = pred["away_team"]

    elo_diff = pred["home_elo"] - pred["away_elo"]
    model_spread = elo_diff / ELO_TO_SPREAD_FACTOR
    exp_spread = model_spread

    model_total = pred["expected_total"] if pred.get("expected_total", 0) > 0 else 225.0
    market_weight = 0.0
    market_diff = 0.0

    if market_total:
        market_diff = abs(model_total - market_total)
        if market_diff >= 14:
            market_weight = 0.55
        elif market_diff >= 10:
            market_weight = 0.48
        elif market_diff >= 7:
            market_weight = 0.40
        else:
            market_weight = 0.32
        exp_total = (model_total * (1 - market_weight)) + (market_total * market_weight)
    else:
        exp_total = model_total

    # Blend spread only when a market spread exists. Keep model in charge.
    spread_market_weight = 0.25 if market_spread is not None else 0.0
    if market_spread is not None:
        exp_spread = (model_spread * (1 - spread_market_weight)) + (market_spread * spread_market_weight)

    if is_playoff is None:
        is_playoff = is_playoff_date(game_date)

    playoff_adjustment = 0.0
    if is_playoff:
        # Real playoff adjustment: not only market blend. Totals slow down and big spreads compress slightly.
        playoff_adjustment = -4.0
        exp_total += playoff_adjustment
        exp_spread *= 0.96

    home_bias = get_team_bias_adjustment(home, bias_adjustments)
    away_bias = get_team_bias_adjustment(away, bias_adjustments)

    home_score_float = (exp_total + exp_spread) / 2 + home_bias
    away_score_float = (exp_total - exp_spread) / 2 + away_bias

    home_score = round(home_score_float)
    away_score = round(away_score_float)
    final_total = home_score + away_score
    win_p = lp.win_prob_home(round(exp_spread, 1))

    return {
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "exp_total": round(final_total, 1),
        "blended_total_before_rounding": round(exp_total, 1),
        "model_total": round(model_total, 1),
        "market_total_used": market_total,
        "market_weight": round(market_weight, 2),
        "market_diff": round(market_diff, 1),
        "lineup_warning": market_diff >= 10,
        "model_spread": round(model_spread, 1),
        "exp_spread": round(exp_spread, 1),
        "market_spread_used": market_spread,
        "spread_market_weight": round(spread_market_weight, 2),
        "is_playoff": bool(is_playoff),
        "playoff_adjustment": playoff_adjustment,
        "home_bias_adjustment": round(home_bias, 1),
        "away_bias_adjustment": round(away_bias, 1),
        # Siegchance und Spread aus derselben Verteilung (Variante A, sigmas_version 2): Normalverteilung um den ANGEZEIGTEN Spread (exp_spread, 1 Nachkommastelle,
        # wie in den Spread-Tabellen) mit SPREAD_SIGMA. Die kalibrierte Elo-Logistik des Modells bleibt zur Nachvollziehbarkeit in *_elo erhalten.
        "home_win_prob": round(win_p, 4),
        "away_win_prob": round(1.0 - win_p, 4),
        "home_win_prob_elo": pred["home_win_prob"],
        "away_win_prob_elo": pred["away_win_prob"],
        "win_prob_source": "normal_spread",
        "sigma_spread": lp.SPREAD_SIGMA,
        "sigmas_version": lp.SIGMAS_VERSION,
    }
