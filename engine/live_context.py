from __future__ import annotations

from data.mock_loader import load_mock_boxscore, load_mock_playbyplay
from data.nba_live import (
    detect_foul_trouble,
    fetch_live_boxscore,
    fetch_playbyplay,
    get_current_quarter_points,
    summarize_recent_actions,
)
from engine.momentum import analyze_momentum, build_team_run_state
from engine.possessions import estimate_possessions
from engine.live import build_game_state, build_pace_mode
from engine.replay import (
    build_current_team_fouls_from_pbp,
    build_replay_foul_state,
    build_replay_quarter_points,
    build_replay_snapshot,
)


def build_live_context(
    selected_live_game,
    live_source,
    replay_mode=False,
    replay_minute=None,
) -> dict:
    context = _empty_context()
    if not selected_live_game:
        return context

    live_boxscore, actions = _load_live_payload(selected_live_game, live_source)
    snapshot = {}
    replay_foul_state = {"player_fouls": {}, "team_fouls": {}}
    quarter_points_by_quarter = {}

    if replay_mode:
        replay_seconds = int(replay_minute or 0) * 60
        snapshot = build_replay_snapshot(actions, replay_seconds)
        actions = snapshot["actions"]
        quarter = int(snapshot.get("period") or 1)
        clock = _nba_clock_to_mmss(snapshot.get("clock"), fallback="12:00")
        score_home = int(snapshot.get("score_home") or 0)
        score_away = int(snapshot.get("score_away") or 0)
        q_points = build_replay_quarter_points(actions, quarter)
        replay_foul_state = build_replay_foul_state(actions)
        foul_trouble = _replay_foul_trouble_cards(replay_foul_state)
    else:
        q_points = get_current_quarter_points(live_boxscore) if live_boxscore else _empty_q_points()
        quarter = int(
            live_boxscore.get("period")
            or selected_live_game.get("period")
            or q_points.get("period")
            or 1
        )
        clock = _nba_clock_to_mmss(selected_live_game.get("clock"), fallback="12:00")
        score_home = int(selected_live_game.get("home_score") or 0)
        score_away = int(selected_live_game.get("away_score") or 0)
        foul_trouble = detect_foul_trouble(live_boxscore) if live_boxscore else []

    for q in [1, 2, 3, 4]:
        quarter_points_by_quarter[q] = build_replay_quarter_points(actions, q)

    team_fouls = build_current_team_fouls_from_pbp(actions, quarter)
    possession_summary = estimate_possessions(actions)
    momentum_summary = analyze_momentum(actions)
    run_state = build_team_run_state(actions, None)
    game_state = build_game_state(score_home, score_away, quarter, clock)
    pace_mode = build_pace_mode(possession_summary.get("pace_per_48"))
    recent_pbp_summary = summarize_recent_actions(actions, limit=20) if actions else {}
    bonus_home, bonus_away = _bonus_state(
        live_boxscore,
        replay_mode,
        team_fouls,
    )

    context.update(
        {
            "actions": actions,
            "snapshot": snapshot,
            "quarter": quarter,
            "clock": clock,
            "score_home": score_home,
            "score_away": score_away,
            "quarter_points": q_points,
            "team_fouls": team_fouls,
            "replay_foul_state": replay_foul_state,
            "possession_summary": possession_summary,
            "momentum_summary": momentum_summary,
            "game_state": game_state,
            "pace_mode": pace_mode,
            "run_state": run_state,
            "run_state_by_side": {
                "home": build_team_run_state(actions, "home"),
                "away": build_team_run_state(actions, "away"),
            },
            "recent_pbp_summary": recent_pbp_summary,
            "live_boxscore": live_boxscore,
            "q_points": q_points,
            "bonus_home": bonus_home,
            "bonus_away": bonus_away,
            "foul_trouble": foul_trouble,
            "quarter_points_by_quarter": quarter_points_by_quarter,
        }
    )
    return context


def _load_live_payload(selected_live_game: dict, live_source: str) -> tuple[dict, list]:
    if str(live_source).upper() == "LIVE":
        game_id = selected_live_game["game_id"]
        return fetch_live_boxscore(game_id), fetch_playbyplay(game_id)
    return load_mock_boxscore(), load_mock_playbyplay()


def _empty_context() -> dict:
    q_points = _empty_q_points()
    return {
        "actions": [],
        "snapshot": {},
        "quarter": 1,
        "clock": "12:00",
        "score_home": 0,
        "score_away": 0,
        "quarter_points": q_points,
        "team_fouls": {
            "home_team_fouls": 0,
            "away_team_fouls": 0,
            "team_fouls_by_tricode": {},
        },
        "replay_foul_state": {"player_fouls": {}, "team_fouls": {}},
        "possession_summary": {},
        "momentum_summary": {},
        "game_state": "normal",
        "pace_mode": "normal",
        "run_state": {
            "run_for_team": 0,
            "run_against_team": 0,
            "run_label": "NONE",
        },
        "run_state_by_side": {
            "home": {
                "run_for_team": 0,
                "run_against_team": 0,
                "run_label": "NONE",
            },
            "away": {
                "run_for_team": 0,
                "run_against_team": 0,
                "run_label": "NONE",
            },
        },
        "recent_pbp_summary": {},
        "live_boxscore": {},
        "q_points": q_points,
        "bonus_home": False,
        "bonus_away": False,
        "foul_trouble": [],
        "quarter_points_by_quarter": {
            1: _empty_q_points(),
            2: _empty_q_points(),
            3: _empty_q_points(),
            4: _empty_q_points(),
        },
    }


def _empty_q_points() -> dict:
    return {
        "home_q_points": 0,
        "away_q_points": 0,
        "quarter_total": 0,
    }


def _nba_clock_to_mmss(raw_clock, fallback="12:00"):
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


def _bonus_state(live_boxscore: dict, replay_mode: bool, team_fouls: dict) -> tuple[bool, bool]:
    if not replay_mode and live_boxscore:
        home = live_boxscore.get("homeTeam", {})
        away = live_boxscore.get("awayTeam", {})
        if "inBonus" in home or "inBonus" in away:
            return _truthy_bonus(home.get("inBonus")), _truthy_bonus(away.get("inBonus"))

    home_fouls = int(team_fouls.get("home_team_fouls") or 0)
    away_fouls = int(team_fouls.get("away_team_fouls") or 0)
    return away_fouls >= 5, home_fouls >= 5


def _truthy_bonus(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _replay_foul_trouble_cards(replay_foul_state: dict) -> list[dict]:
    results = []

    for player in replay_foul_state.get("player_fouls", {}).values():
        fouls = int(player.get("fouls") or 0)
        severity = None

        if fouls >= 5:
            severity = "CRITICAL"
        elif fouls >= 4:
            severity = "HIGH"

        if severity:
            results.append(
                {
                    "team": player.get("team") or "UNKNOWN",
                    "player": player.get("player") or "Unknown Player",
                    "fouls": fouls,
                    "points": 0,
                    "minutes": "Replay",
                    "starter": False,
                    "oncourt": False,
                    "severity": severity,
                }
            )

    return sorted(results, key=lambda x: x["fouls"], reverse=True)
