"""
NBAEdge EV Engine
-----------------
Combines model probabilities + sharp-book fair odds → Value Bets
"""

import pandas as pd
from datetime import datetime
from config.settings import MIN_EV_THRESHOLD, MIN_KELLY, MAX_KELLY, SOFT_BOOKS


def blend_probabilities(model_prob: float, sharp_prob: float | None,
                        model_weight: float = 0.3) -> float:
    """
    Blend model probability with sharp-book fair prob.
    If no sharp book available, use model only.
    """
    if sharp_prob is None:
        return model_prob
    return model_weight * model_prob + (1 - model_weight) * sharp_prob


def calculate_ev(win_prob: float, decimal_odds: float) -> float:
    """
    EV = win_prob * (odds - 1) - (1 - win_prob)
    Positive EV = value bet.
    """
    return win_prob * (decimal_odds - 1) - (1 - win_prob)


def kelly_fraction(win_prob: float, decimal_odds: float) -> float:
    """
    Full Kelly: f = (p*(b+1) - 1) / b   where b = decimal_odds - 1
    Capped at MAX_KELLY for bankroll safety.
    """
    b = decimal_odds - 1
    f = (win_prob * (b + 1) - 1) / b
    f = max(0, f)                    # no negative stakes
    f = min(f, MAX_KELLY)            # cap
    return round(f, 4)


def find_value_bets(
    model_predictions: list[dict],
    odds_games: list[dict],
) -> list[dict]:
    """
    Match model predictions to odds games, calculate EV for each soft book.
    Returns sorted list of value bets above MIN_EV_THRESHOLD.
    """
    from data.odds import get_sharp_fair_odds

    value_bets = []

    for pred in model_predictions:
        home = pred["home_team"]
        away = pred["away_team"]

        # Find matching odds game (fuzzy name match)
        matched = _match_game(home, away, odds_games)
        if not matched:
            continue

        bookmakers = matched["bookmakers"]
        sharp_fair = get_sharp_fair_odds(bookmakers)

        sharp_home_prob = sharp_fair["fair_home_prob"] if sharp_fair else None
        sharp_away_prob = sharp_fair["fair_away_prob"] if sharp_fair else None

        # Blended probabilities
        blended_home = blend_probabilities(pred["home_win_prob"], sharp_home_prob)
        blended_away = blend_probabilities(pred["away_win_prob"], sharp_away_prob)

        for book_key, book_odds in bookmakers.items():
            if book_key not in SOFT_BOOKS:
                continue

            for side, prob, odds_key in [
                ("home", blended_home, "home_odds"),
                ("away", blended_away, "away_odds"),
            ]:
                dec_odds = book_odds[odds_key]
                ev = calculate_ev(prob, dec_odds)

                if ev < MIN_EV_THRESHOLD:
                    continue

                kelly = kelly_fraction(prob, dec_odds)
                if kelly < MIN_KELLY:
                    continue

                team_name = home if side == "home" else away
                value_bets.append({
                    "home_team": home,
                    "away_team": away,
                    "bet_on": team_name,
                    "side": side,
                    "bookmaker": book_key,
                    "decimal_odds": dec_odds,
                    "model_prob": round(pred[f"{side}_win_prob"], 4),
                    "sharp_prob": sharp_home_prob if side == "home" else sharp_away_prob,
                    "blended_prob": round(prob, 4),
                    "ev_pct": round(ev * 100, 2),
                    "kelly_pct": round(kelly * 100, 2),
                    "sharp_source": sharp_fair["source"] if sharp_fair else "model_only",
                    "vig": sharp_fair["vig"] if sharp_fair else None,
                    "commence_time": matched["commence_time"],
                    "home_elo": pred["home_elo"],
                    "away_elo": pred["away_elo"],
                    "home_form": pred["home_form"],
                    "away_form": pred["away_form"],
                    "home_rest_days": pred["home_rest_days"],
                    "away_rest_days": pred["away_rest_days"],
                    "expected_total": pred["expected_total"],
                })

    value_bets.sort(key=lambda x: x["ev_pct"], reverse=True)
    return value_bets


def _match_game(home: str, away: str, odds_games: list[dict]) -> dict | None:
    """Simple fuzzy team name matching."""
    home_kw = home.split()[-1].lower()
    away_kw = away.split()[-1].lower()
    for g in odds_games:
        oh = g["home_team"].lower()
        oa = g["away_team"].lower()
        if home_kw in oh and away_kw in oa:
            return g
        if away_kw in oh and home_kw in oa:
            # Reversed — swap perspective handled by caller
            return g
    return None
