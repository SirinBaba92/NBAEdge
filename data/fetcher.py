import os, requests, time, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BALLDONTLIE_API_KEY")
BASE    = "https://api.balldontlie.io/v1"
CACHE   = Path(__file__).parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

HEADERS = {"Authorization": API_KEY}

def _get(endpoint, params=None, retries=5):
    for attempt in range(retries):
        r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=15)
        if r.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise Exception("Max retries exceeded (429)")

def current_season(today=None) -> int:
    """BallDontLie-Saison (Startjahr): ab Oktober die neue Saison, sonst die laufende/zuletzt beendete."""
    from datetime import date
    today = today or date.today()
    return today.year if today.month >= 10 else today.year - 1

def _is_finished(g: dict) -> bool:
    """Nur beendete Spiele mit Endstand: status == 'Final', nicht verschoben, beide Scores vorhanden."""
    return (
        g.get("status") == "Final"
        and not g.get("postponed")
        and g.get("home_team_score") is not None
        and g.get("visitor_team_score") is not None
    )

def _read_cache(cache_file: Path) -> list[dict]:
    """Liest eine Cache-Datei. Fehlt sie, ist sie leer oder defekt, gilt sie als nicht vorhanden ([])."""
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text())
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [g for g in data if _is_finished(g)]

def fetch_all_games(season: int) -> list[dict]:
    live_season = season >= current_season()
    cache_file = CACHE / f"games_{season}.json"
    # Abgeschlossene Saisons kommen aus dem Cache; leere Dateien zaehlen nicht als Cache.
    # Die laufende Saison wird nie aus dem Cache gelesen (bei jedem Training neu laden).
    if not live_season:
        cached = _read_cache(cache_file)
        if cached:
            return cached

    games, cursor = [], None
    while True:
        params = {"seasons[]": season, "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("games", params)
        games.extend(data["data"])
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1.0)

    # only finished games: no future, in-progress or postponed games
    games = [g for g in games if _is_finished(g)]
    if live_season:
        # Laufende Saison nie als fertig cachen (inkrementelles Laden folgt in Phase B)
        print(f"  Season {season}: {len(games)} finished games loaded (current season, not cached)")
    elif games:
        cache_file.write_text(json.dumps(games))
        print(f"  Season {season}: {len(games)} games cached")
    else:
        print(f"  Season {season}: no finished games found, nothing cached")
    return games

def fetch_seasons(seasons: list[int]) -> list[dict]:
    all_games = []
    for s in seasons:
        print(f"Fetching season {s}...")
        all_games.extend(fetch_all_games(s))
    return all_games

def _upcoming_cache_path() -> Path:
    return Path(os.environ.get("NBAEDGE_UPCOMING_CACHE") or Path(__file__).parent.parent / "data" / "upcoming_cache.json")


def fetch_upcoming_games() -> list[dict]:
    """Fetch today's upcoming games (not yet started).

    Die Roh-Antwort wird UPCOMING_GAMES_TTL_SECONDS (10 Min.) auf der Festplatte zwischengespeichert
    (data/upcoming_cache.json), damit Neuladen und neue Sitzungen das BallDontLie-Rate-Limit nicht ausloesen.
    Schlaegt der Abruf fehl und es gibt einen Cache fuer dieselben Daten, wird dieser (auch abgelaufen) genutzt.
    Gefiltert wird bei jedem Aufruf neu (Zeitfenster relativ zu jetzt)."""
    from datetime import datetime, timezone, timedelta
    from config.settings import UPCOMING_GAMES_TTL_SECONDS
    today = datetime.now(timezone.utc).date()
    params = {
        "start_date": (today - timedelta(days=1)).isoformat(),
        "end_date": today.isoformat(),
        "per_page": 100,
    }
    cache_file = _upcoming_cache_path()
    cached = None
    try:
        cached = json.loads(cache_file.read_text())
        if cached.get("params") != params:
            cached = None
    except Exception:
        cached = None

    now_ts = time.time()
    if cached and now_ts - cached.get("fetched_at", 0) < UPCOMING_GAMES_TTL_SECONDS:
        games = cached["games"]
    else:
        try:
            data = _get("games", params, retries=2)
            games = data.get("data", [])
            tmp = cache_file.with_name(cache_file.name + ".tmp")
            tmp.write_text(json.dumps({"fetched_at": now_ts, "params": params, "games": games}))
            os.replace(tmp, cache_file)
        except Exception as e:
            if not cached:
                raise
            age_min = int((now_ts - cached.get("fetched_at", now_ts)) / 60)
            print(f"  BallDontLie nicht erreichbar ({type(e).__name__}); nutze Zwischenspeicher von vor {age_min} Min.")
            games = cached["games"]
    # Only show games that haven't finished
    now = datetime.now(timezone.utc)
    upcoming = []
    for g in games:
        if g.get("status") == "Final":
            continue
        game_time_str = g.get("date", "")
        try:
            game_time = datetime.fromisoformat(game_time_str.replace("Z", "+00:00"))
            if game_time > now - timedelta(hours=3) and game_time < now + timedelta(hours=12):
                upcoming.append(g)
        except Exception:
            upcoming.append(g)
    return upcoming
