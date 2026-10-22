def get_live_bet_status(live_boxscore, bets):
    """
    Track live points-over bets against a live boxscore.

    The function expects the NBAEdge live boxscore shape:
    - live_boxscore["homeTeam"]["players"]
    - live_boxscore["awayTeam"]["players"]

    A future game_finished flag is supported when present on live_boxscore:
    {"game_finished": True, "homeTeam": {...}, "awayTeam": {...}}
    """
    game_finished = False
    players = []

    if isinstance(live_boxscore, dict):
        game_finished = bool(live_boxscore.get("game_finished", False))
        for side in ["homeTeam", "awayTeam"]:
            team = live_boxscore.get(side, {})
            players.extend(team.get("players", []))

    results = []

    for bet in bets or []:
        player_name = bet.get("player")
        line = float(bet.get("line", 0))
        player = _find_player(players, player_name)
        current_points = _get_current_points(player)
        remaining = max(0, line - current_points)

        if current_points > line:
            status = "WON"
        elif game_finished:
            status = "LOST"
        else:
            status = "IN_PROGRESS"

        results.append(
            {
                "player": player_name,
                "line": line,
                "current_points": current_points,
                "remaining": remaining,
                "status": status,
            }
        )

    return results


def _find_player(players, player_name):
    """Return the matching player dictionary, or an empty dict if not found."""
    if not player_name:
        return {}

    for player in players or []:
        if not isinstance(player, dict):
            continue

        name = player.get("name")
        if name == player_name:
            return player

    return {}


def _get_current_points(player):
    """Read points from NBA.com statistics and fall back to 0."""
    if not isinstance(player, dict):
        return 0

    statistics = player.get("statistics", {})
    if not isinstance(statistics, dict):
        return 0

    points = statistics.get("points", 0)

    try:
        return int(points)
    except (TypeError, ValueError):
        return 0
