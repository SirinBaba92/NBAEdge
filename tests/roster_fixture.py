"""Gefaelschte PlayerIndex-Antwort fuer Tests und Browsertest (kein echtes Netz): 30 Teams mit je 16 Spielern; einzelne Teams haben Namen mit Akzenten/Suffix."""
from nba_api.stats.static import teams as _teams

NAMED = {
    "New York Knicks": [("Jalen", "Brunson", "G", "11"), ("Karl-Anthony", "Towns", "C", "32"), ("Josh", "Hart", "G-F", "3"), ("Mikal", "Bridges", "F", "25")],
    "Philadelphia 76ers": [("Tyrese", "Maxey", "G", "0"), ("Joel", "Embiid", "C", "21"), ("Nikola", "Jokić", "C", "15"), ("Jaren", "Jackson Jr.", "F", "13")],
    "San Antonio Spurs": [("Victor", "Wembanyama", "C", "1"), ("Dylan", "Harper", "G", "2")],
    "Oklahoma City Thunder": [("Shai", "Gilgeous-Alexander", "G", "2"), ("Jalen", "Williams", "F", "8")],
}
HEADERS = ["PERSON_ID", "PLAYER_LAST_NAME", "PLAYER_FIRST_NAME", "PLAYER_SLUG", "TEAM_ID", "TEAM_SLUG", "IS_DEFUNCT", "TEAM_CITY", "TEAM_NAME", "TEAM_ABBREVIATION",
           "JERSEY_NUMBER", "POSITION", "HEIGHT", "WEIGHT", "COLLEGE", "COUNTRY", "DRAFT_YEAR", "DRAFT_ROUND", "DRAFT_NUMBER", "ROSTER_STATUS", "FROM_YEAR", "TO_YEAR",
           "PTS", "REB", "AST", "STATS_TIMEFRAME", "SUPPLEMENTAL_STATUS"]


def fake_index(season="2026-27", drop_teams=(), extra=None, per_team=16) -> dict:
    """extra: {Teamvollname: [(Vorname, Nachname, Position, Trikot)]} zusaetzlich (z. B. Neuzugang)."""
    rows, pid = [], 900000
    for t in _teams.get_teams():
        city = "LA" if t["nickname"] == "Clippers" else t["city"]          # wie in der echten Antwort ("LA Clippers")
        full = f'{city} {t["nickname"]}'
        if full in drop_teams:
            continue
        named = list(NAMED.get(full, [])) + list((extra or {}).get(full, []))
        fillers = [(f"Spieler{i}", f"{t['abbreviation']}{i}", "F", str(20 + i)) for i in range(per_team - len(NAMED.get(full, [])))]
        for first, last, pos, jersey in named + fillers:
            pid += 1
            rows.append([pid, last, first, f"{first}-{last}".lower(), t["id"], t["nickname"].lower(), 0, city, t["nickname"], t["abbreviation"],
                         jersey, pos, "6-6", "210", "X", "USA", 2020, 1, 5, 1.0, "2020", "2026", None, None, None, "Season", 0])
    return {"resource": "playerindex", "parameters": {"Season": season}, "resultSets": [{"name": "PlayerIndex", "headers": HEADERS, "rowSet": rows}]}
