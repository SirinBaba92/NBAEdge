from __future__ import annotations

from html import escape

import streamlit as st

from data.live_market import (
    append_market_history_snapshot,
    build_market_movement_signal,
    fetch_live_market_lines,
    get_market_history,
    load_market_history,
    update_market_history,
)
from engine.live import QuarterProjectionInput, live_quarter_projection, parse_clock_to_seconds
from engine.live_context import build_live_context


EDGE_STYLES = {
    "STRONG_OVER_EDGE": ("🔥", "#f97316", "#431407"),
    "STRONG_UNDER_EDGE": ("❄️", "#38bdf8", "#082f49"),
    "TRAP_OVER": ("⚠️", "#facc15", "#422006"),
    "OVER_EDGE": ("↗", "#fb923c", "#431407"),
    "UNDER_EDGE": ("↘", "#60a5fa", "#172554"),
    "UNSTABLE": ("⚠️", "#ef4444", "#450a0a"),
    "NO_EDGE": ("•", "#94a3b8", "#111827"),
}
EDGE_SIGNALS = {
    "STRONG_OVER_EDGE",
    "STRONG_UNDER_EDGE",
    "OVER_EDGE",
    "UNDER_EDGE",
}
STRONG_EDGE_SIGNALS = {"STRONG_OVER_EDGE", "STRONG_UNDER_EDGE"}
WARNING_SIGNALS = {"TRAP_OVER", "UNSTABLE"}
MARKET_DISAGREEMENT = "MARKET_DISAGREEMENT"
POSSIBLE_FAKE_LINE = "POSSIBLE_FAKE_LINE"
HIGH_CONVICTION_EDGE = "HIGH_CONVICTION_EDGE"
MOVEMENT_COLORS = {
    "STEAM_MOVE": "#f97316",
    "REVERSE_STEAM": "#facc15",
    "LINE_FREEZE": "#22d3ee",
    "MARKET_OVERREACTION": "#ef4444",
    "MARKET_LAG": "#22c55e",
    "NONE": "#94a3b8",
}


def render_live_trading_dashboard(
    live_games,
    live_source,
    replay_mode=False,
    replay_minute=None,
) -> None:
    if not live_games:
        st.info("Keine Games für das Live Trading Dashboard verfügbar.")
        return

    items = []
    for game in live_games:
        try:
            context = build_live_context(
                game,
                live_source,
                replay_mode=replay_mode,
                replay_minute=replay_minute,
            )
            market_lines = fetch_live_market_lines(game)
            projection = _build_dashboard_projection(context, market_lines)
            items.append(_build_dashboard_item(game, context, projection, market_lines))
        except Exception as exc:
            away, home = _game_names(game)
            st.warning(f"Dashboard übersprungen: {away} @ {home}: {exc}")

    if not items:
        st.info("Keine Dashboard Items berechnet.")
        return

    items = sorted(
        items,
        key=lambda item: (
            item["edge_strength"],
            item["confidence_score"],
            item["stability_score"],
        ),
        reverse=True,
    )

    _render_summary(items)
    filtered_items = _render_filters(items)

    if not filtered_items:
        st.info("Keine Games passen zu den aktuellen Dashboard-Filtern.")
        return

    for item in filtered_items:
        _render_game_card(item)


def format_clock(raw_clock, fallback="12:00") -> str:
    if not raw_clock:
        return fallback
    raw_clock = str(raw_clock)
    if ":" in raw_clock and not raw_clock.startswith("PT"):
        return raw_clock
    try:
        mins = raw_clock.split("PT")[1].split("M")[0]
        secs = raw_clock.split("M")[1].split(".")[0].replace("S", "")
        return f"{int(mins)}:{str(int(secs)).zfill(2)}"
    except Exception:
        return fallback


def _build_dashboard_projection(context: dict, market_lines: dict) -> dict:
    quarter_points = context.get("quarter_points") or {}
    team_fouls = context.get("team_fouls") or {}
    recent = context.get("recent_pbp_summary") or {}
    possession = context.get("possession_summary") or {}
    momentum = context.get("momentum_summary") or {}

    return live_quarter_projection(
        QuarterProjectionInput(
            line=float(market_lines.get("quarter_line") or 55.5),
            current_total_points=int(quarter_points.get("quarter_total") or 0),
            seconds_left_in_quarter=parse_clock_to_seconds(context.get("clock")),
            pregame_game_total=225.0,
            quarter=int(context.get("quarter") or 1),
            pace_mode="normal",
            team_fouls_a=int(team_fouls.get("home_team_fouls") or 0),
            team_fouls_b=int(team_fouls.get("away_team_fouls") or 0),
            game_state="close",
            recent_total_points_last_2min=int(recent.get("points") or 0),
            empty_possessions=int(possession.get("empty_possessions_recent") or 0),
            pbp_signal=recent.get("pace_signal") or "NORMAL",
            possession_pace_per_48=possession.get("pace_per_48"),
            possession_empty_count=int(possession.get("empty_possessions_recent") or 0),
            possession_off_rating=_average_off_rating(possession),
            momentum_signal=momentum.get("momentum_signal") or "STABLE",
            momentum_factor=float(momentum.get("momentum_factor") or 1.0),
        )
    )


def _build_dashboard_item(
    game: dict,
    context: dict,
    projection: dict,
    market_lines: dict,
) -> dict:
    edge_signal = projection.get("edge_signal") or "NO_EDGE"
    market_line = float(market_lines.get("quarter_line") or 55.5)
    projected_total = float(projection.get("projected_quarter_total") or 0)
    projection_delta = round(projected_total - market_line, 1)
    confidence = int(projection.get("confidence_score") or 0)
    stability = int(projection.get("stability_score") or 0)
    game_key = _game_key(game)
    previous = get_market_history(game_key) or {}
    movement = build_market_movement_signal(
        market_line,
        previous.get("last_market_line"),
        projected_total,
        previous.get("last_projection"),
        confidence,
        stability,
    )
    update_market_history(game_key, market_line, projected_total)
    append_market_history_snapshot(
        game_key,
        market_line,
        projected_total,
        projection_delta,
        movement.get("signal") or "NONE",
    )
    persisted_history = load_market_history(game_key, limit=50)

    return {
        "game": game,
        "context": context,
        "projection": projection,
        "market_lines": market_lines,
        "projection_delta": projection_delta,
        "market_signal": _market_signal(
            projection_delta,
            confidence,
            stability,
            edge_signal,
        ),
        "market_movement": movement,
        "recent_market_signals": _recent_market_signals(persisted_history),
        "delta_trend": _delta_trend(persisted_history),
        "edge_strength": float(projection.get("edge_strength") or 0),
        "confidence_score": confidence,
        "stability_score": stability,
        "edge_signal": edge_signal,
    }


def _render_summary(items: list[dict]) -> None:
    edge_count = sum(1 for item in items if item["edge_signal"] in EDGE_SIGNALS)
    strong_count = sum(1 for item in items if item["edge_signal"] in STRONG_EDGE_SIGNALS)
    warning_count = sum(1 for item in items if item["edge_signal"] in WARNING_SIGNALS)
    best_strength = max((item["edge_strength"] for item in items), default=0)
    strongest_delta = max(
        (abs(item["projection_delta"]) for item in items),
        default=0,
    )
    disagreement_count = sum(
        1
        for item in items
        if item["market_signal"] == MARKET_DISAGREEMENT
    )
    conviction_count = sum(
        1
        for item in items
        if item["market_signal"] == HIGH_CONVICTION_EDGE
    )
    steam_count = sum(
        1
        for item in items
        if item["market_movement"].get("signal") == "STEAM_MOVE"
    )
    freeze_count = sum(
        1
        for item in items
        if item["market_movement"].get("signal") == "LINE_FREEZE"
    )
    lag_count = sum(
        1
        for item in items
        if item["market_movement"].get("signal") == "MARKET_LAG"
    )
    active_market_signals = sum(
        1
        for item in items
        if item["market_movement"].get("signal") != "NONE"
    )
    latest_lag_count = sum(
        1
        for item in items
        if item["recent_market_signals"][:1] == ["MARKET_LAG"]
    )
    latest_freeze_count = sum(
        1
        for item in items
        if item["recent_market_signals"][:1] == ["LINE_FREEZE"]
    )

    cols = st.columns(14)
    cols[0].metric("Games", len(items))
    cols[1].metric("Edges", edge_count)
    cols[2].metric("Strong", strong_count)
    cols[3].metric("Warnings", warning_count)
    cols[4].metric("Best Strength", int(round(best_strength)))
    cols[5].metric("Strongest Delta", _signed(strongest_delta))
    cols[6].metric("Disagreements", disagreement_count)
    cols[7].metric("High Conviction", conviction_count)
    cols[8].metric("Steam", steam_count)
    cols[9].metric("Freeze", freeze_count)
    cols[10].metric("Lag", lag_count)
    cols[11].metric("Active Signals", active_market_signals)
    cols[12].metric("Latest Lag", latest_lag_count)
    cols[13].metric("Latest Freeze", latest_freeze_count)


def _render_filters(items: list[dict]) -> list[dict]:
    c1, c2, c3 = st.columns(3)
    edges_only = c1.checkbox("Nur Edges anzeigen", value=False)
    show_warnings = c2.checkbox("Warnings anzeigen", value=True)
    confidence_60 = c3.checkbox("Nur Confidence >= 60", value=False)

    filtered = items
    if edges_only:
        filtered = [
            item
            for item in filtered
            if item["edge_signal"] in EDGE_SIGNALS
        ]
    if not show_warnings:
        filtered = [
            item
            for item in filtered
            if item["edge_signal"] not in WARNING_SIGNALS
        ]
    if confidence_60:
        filtered = [
            item
            for item in filtered
            if item["confidence_score"] >= 60
        ]
    return filtered


def _render_game_card(item: dict) -> None:
    game = item["game"]
    context = item["context"]
    projection = item["projection"]
    market_lines = item["market_lines"]
    away, home = _game_names(game)
    edge_signal = item["edge_signal"]
    icon, accent, bg = EDGE_STYLES.get(edge_signal, EDGE_STYLES["NO_EDGE"])
    team_fouls = context.get("team_fouls") or {}
    possession = context.get("possession_summary") or {}
    momentum = context.get("momentum_summary") or {}
    recent = context.get("recent_pbp_summary") or {}

    score = f"{context.get('score_away', 0)} - {context.get('score_home', 0)}"
    game_line = f"{escape(away)} @ {escape(home)}"
    quarter_clock = f"Q{int(context.get('quarter') or 1)} · {escape(str(context.get('clock') or '12:00'))}"
    ticker_line = (
        f"{game_line}"
        f"<span style='display:inline-block;margin:0 14px;color:#f97316;'>{escape(score)}</span>"
        f"{quarter_clock}"
    )
    fouls = (
        f"Home {int(team_fouls.get('home_team_fouls') or 0)} · "
        f"Away {int(team_fouls.get('away_team_fouls') or 0)}"
    )
    bonus = (
        f"Home {'YES' if context.get('bonus_home') else 'NO'} · "
        f"Away {'YES' if context.get('bonus_away') else 'NO'}"
    )
    delta = item["projection_delta"]
    delta_color = _delta_color(delta)
    market_signal = item["market_signal"]
    market_signal_color = _market_signal_color(market_signal)
    movement = item["market_movement"]
    movement_signal = movement.get("signal") or "NONE"
    movement_color = MOVEMENT_COLORS.get(movement_signal, "#94a3b8")
    recent_signals = ", ".join(item["recent_market_signals"]) or "NONE"
    delta_trend = item["delta_trend"]
    trend_color = _trend_color(delta_trend)

    st.markdown(
        f"""
        <div style="background:#111827;border:1px solid #2b3550;border-left:4px solid {accent};border-radius:10px;padding:12px 14px;margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;min-width:0;">
                <div style="min-width:0;flex:1;overflow:hidden;">
                    <div style="color:#e8e8f0;font-family:Space Mono,monospace;font-size:0.95rem;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.35;padding:2px 0;">
                        {ticker_line}
                    </div>
                </div>
                <div style="background:{bg};border:1px solid {accent};color:{accent};border-radius:6px;padding:6px 9px;font-family:Space Mono,monospace;font-size:0.72rem;font-weight:700;white-space:nowrap;">
                    {icon} {escape(edge_signal)}
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin-top:9px;">
                {_metric("Team Fouls", fouls)}
                {_metric("Bonus", bonus)}
                {_metric("PBP", recent.get("pace_signal") or "NORMAL")}
                {_metric("Pace/48", possession.get("pace_per_48", "0.0"))}
                {_metric("Momentum", momentum.get("momentum_signal") or "STABLE")}
                {_metric("Master", projection.get("master_live_factor", "1.000"))}
                {_metric("Stability", projection.get("stability_score", "0"))}
                {_metric("Confidence", projection.get("confidence_score", "0"))}
                {_metric("Market Q Line", market_lines.get("quarter_line", "55.5"))}
                {_metric("Model Projection", projection.get("projected_quarter_total", "0.0"))}
                {_metric("Projection Delta", _signed(delta), value_color=delta_color)}
                {_metric("Market Source", market_lines.get("market_source", "MOCK_FALLBACK"))}
                {_metric("Edge Value", _signed(projection.get("edge_value", 0)))}
                {_metric("Edge Strength", int(item["edge_strength"]))}
                {_metric("Over Chance", f"{projection.get('over_probability', 0)}%")}
                {_metric("Lean", projection.get("lean", "COINFLIP"))}
                {_metric("Market Signal", market_signal, value_color=market_signal_color)}
                {_metric("Market Move", _signed(movement.get("market_move", 0)), value_color=movement_color)}
                {_metric("Projection Move", _signed(movement.get("projection_move", 0)), value_color=movement_color)}
                {_metric("Movement Signal", movement_signal, value_color=movement_color)}
                {_metric("Last 3 Signals", recent_signals)}
                {_metric("Delta Trend", delta_trend, value_color=trend_color)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric(label: str, value, value_color: str = "#e8e8f0") -> str:
    return (
        "<div style='background:#0b1220;border:1px solid #243044;border-radius:8px;padding:8px 9px;'>"
        f"<div style='color:#64748b;font-family:Space Mono,monospace;font-size:0.66rem;text-transform:uppercase;'>{escape(str(label))}</div>"
        f"<div style='color:{value_color};font-family:Space Mono,monospace;font-size:0.82rem;margin-top:2px;'>{escape(str(value))}</div>"
        "</div>"
    )


def _signed(value) -> str:
    try:
        return f"{float(value):+.1f}"
    except Exception:
        return str(value)


def _market_signal(
    delta: float,
    confidence: int,
    stability: int,
    edge_signal: str,
) -> str:
    abs_delta = abs(delta)
    if confidence >= 80 and stability >= 85 and abs_delta >= 6:
        return HIGH_CONVICTION_EDGE
    if abs_delta >= 8 and confidence >= 70:
        return MARKET_DISAGREEMENT
    if edge_signal == "NO_EDGE" and abs_delta >= 10:
        return POSSIBLE_FAKE_LINE
    return "NONE"


def _delta_color(delta: float) -> str:
    if delta > 5:
        return "#22c55e"
    if delta < -5:
        return "#ef4444"
    return "#e8e8f0"


def _market_signal_color(signal: str) -> str:
    return {
        HIGH_CONVICTION_EDGE: "#22c55e",
        MARKET_DISAGREEMENT: "#f97316",
        POSSIBLE_FAKE_LINE: "#facc15",
    }.get(signal, "#94a3b8")


def _recent_market_signals(history: list[dict]) -> list[str]:
    signals = []
    for row in reversed(history[-3:]):
        signal = str(row.get("movement_signal") or "NONE")
        signals.append(signal)
    return signals


def _delta_trend(history: list[dict]) -> str:
    if len(history) < 2:
        return "flat"

    try:
        previous = float(history[-2].get("delta") or 0)
        current = float(history[-1].get("delta") or 0)
    except Exception:
        return "flat"

    if current > previous:
        return "rising"
    if current < previous:
        return "falling"
    return "flat"


def _trend_color(trend: str) -> str:
    return {
        "rising": "#22c55e",
        "falling": "#ef4444",
        "flat": "#94a3b8",
    }.get(trend, "#94a3b8")


def _game_names(game: dict) -> tuple[str, str]:
    away = f"{game.get('away_city', '')} {game.get('away_team', '')}".strip()
    home = f"{game.get('home_city', '')} {game.get('home_team', '')}".strip()
    return away or "Away", home or "Home"


def _game_key(game: dict) -> str:
    if game.get("game_id"):
        return str(game["game_id"])
    away, home = _game_names(game)
    return f"{away.lower()}@{home.lower()}"


def _average_off_rating(possession: dict):
    ratings = []
    for key in ["home_off_rating", "away_off_rating"]:
        try:
            rating = float(possession.get(key))
        except Exception:
            continue
        if rating > 0:
            ratings.append(rating)
    if not ratings:
        return None
    return sum(ratings) / len(ratings)
