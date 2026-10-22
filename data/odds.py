from config.settings import SHARP_BOOKS

def fetch_odds(refresh: bool = False, caller: str = "fetch_odds") -> list[dict]:
    """Moneyline (h2h), Roh-Antwort. Laeuft ueber data/odds_client.py (Festplatten-Cache, Credit-Schutz, Protokoll).
    Ohne refresh=True wird nur bei komplett fehlendem Cache abgefragt."""
    from data.odds_client import OddsError, get_odds
    res = get_odds("h2h", caller=caller, refresh=refresh)
    if res.data is None:
        raise OddsError(res.error or "Odds API: keine Moneyline-Daten (Cache leer, automatischer Abruf gesperrt).")
    return res.data

def fetch_totals_and_spreads(refresh: bool = False, caller: str = "fetch_totals_and_spreads") -> list[dict]:
    """Totals (O/U) und Spreads, Roh-Antwort. Laeuft ueber data/odds_client.py (siehe fetch_odds)."""
    from data.odds_client import OddsError, get_odds
    res = get_odds("totals_spreads", caller=caller, refresh=refresh)
    if res.data is None:
        raise OddsError(res.error or "Odds API: keine Totals/Spreads (Cache leer, automatischer Abruf gesperrt).")
    return res.data

def parse_odds(raw: list[dict]) -> list[dict]:
    """Parse raw odds into structured per-game bookmaker odds."""
    games = []
    for event in raw:
        home = event["home_team"]
        away = event["away_team"]
        commence = event["commence_time"]
        bookmakers = {}
        for bm in event.get("bookmakers", []):
            key = bm["key"]
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                    if home in outcomes and away in outcomes:
                        bookmakers[key] = {
                            "home_odds": outcomes[home],
                            "away_odds": outcomes[away],
                        }
        if bookmakers:
            games.append({
                "home_team": home,
                "away_team": away,
                "commence_time": commence,
                "bookmakers": bookmakers,
            })
    return games

def parse_totals_spreads(raw: list[dict]) -> dict:
    """
    Parse totals, spreads and team totals per game.
    Returns dict keyed by (home_team_kw, away_team_kw).
    "spread": positiv = Heimteam ist Favorit (umgedreht gegenueber dem Odds-API-Handicap);
    "spread_home_point": Roh-Handicap des Heimteams wie von der Odds API (negativ = Heim-Favorit).
    """
    result = {}
    for event in raw:
        home = event["home_team"]
        away = event["away_team"]
        totals = []
        spreads = []
        total_over_odds = []
        total_under_odds = []
        spread_home_odds = []
        spread_away_odds = []
        team_totals = {}  # {team_name: {"line": float, "over_odds": float, "under_odds": float}}

        for bm in event.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market["key"] == "totals":
                    for o in market["outcomes"]:
                        if o["name"] == "Over":
                            totals.append(o.get("point", 0))
                            total_over_odds.append(o["price"])
                        elif o["name"] == "Under":
                            total_under_odds.append(o["price"])

                elif market["key"] == "spreads":
                    for o in market["outcomes"]:
                        if o["name"] == home:
                            spreads.append(o.get("point", 0))
                            spread_home_odds.append(o["price"])
                        elif o["name"] == away:
                            spread_away_odds.append(o["price"])

                elif market["key"] == "team_totals":
                    for o in market["outcomes"]:
                        team = o.get("description", "")
                        if team not in team_totals:
                            team_totals[team] = {"lines": [], "over_odds": [], "under_odds": []}
                        if o["name"] == "Over":
                            team_totals[team]["lines"].append(o.get("point", 0))
                            team_totals[team]["over_odds"].append(o["price"])
                        elif o["name"] == "Under":
                            team_totals[team]["under_odds"].append(o["price"])

        # Aggregate team totals
        team_totals_agg = {}
        for team, data in team_totals.items():
            if data["lines"]:
                team_totals_agg[team] = {
                    "line": round(sum(data["lines"]) / len(data["lines"]), 1),
                    "over_odds": round(sum(data["over_odds"]) / len(data["over_odds"]), 2) if data["over_odds"] else None,
                    "under_odds": round(sum(data["under_odds"]) / len(data["under_odds"]), 2) if data["under_odds"] else None,
                }

        key = (_normalize(home), _normalize(away))
        result[key] = {
            "total": round(sum(totals) / len(totals), 1) if totals else None,
            # Konvention im ganzen Projekt: positiv = Heimteam ist Favorit.
            # Die Odds API liefert das Handicap des Heimteams (negativ = Heim-Favorit), daher umdrehen.
            # "+ 0.0" verhindert -0.0.
            "spread": (round(-sum(spreads) / len(spreads), 1) + 0.0) if spreads else None,
            "spread_home_point": round(sum(spreads) / len(spreads), 1) if spreads else None,
            "total_over_odds": round(sum(total_over_odds) / len(total_over_odds), 2) if total_over_odds else None,
            "total_under_odds": round(sum(total_under_odds) / len(total_under_odds), 2) if total_under_odds else None,
            "spread_home_odds": round(sum(spread_home_odds) / len(spread_home_odds), 2) if spread_home_odds else None,
            "spread_away_odds": round(sum(spread_away_odds) / len(spread_away_odds), 2) if spread_away_odds else None,
            "home_team": home,
            "away_team": away,
            "team_totals": team_totals_agg,
        }
    return result

def _normalize(name: str) -> str:
    return name.split()[-1].lower()

def get_sharp_fair_odds(bookmakers: dict) -> dict | None:
    """Extract fair (no-vig) odds from sharp books."""
    for book in SHARP_BOOKS:
        if book in bookmakers:
            h_odds = bookmakers[book]["home_odds"]
            a_odds = bookmakers[book]["away_odds"]
            h_implied = 1 / h_odds
            a_implied = 1 / a_odds
            vig = h_implied + a_implied - 1
            fair_h = h_implied / (1 + vig)
            fair_a = a_implied / (1 + vig)
            return {
                "source": book,
                "fair_home_prob": round(fair_h, 4),
                "fair_away_prob": round(fair_a, 4),
                "vig": round(vig, 4),
            }
    return None
