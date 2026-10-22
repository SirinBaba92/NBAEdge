import copy
import threading
import time

import requests

from data.nba_headers import detect_chrome_major, nba_headers

NBA_SCOREBOARD_URL = (
    "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
)

# Einziges Header-Set fuer alle NBA-Abrufe (Scoreboard, Boxscore, Play-by-Play), seit 23.10.2026 aus data/nba_headers.py: Die Chrome-Hauptversion wird automatisch aus dem
# installierten Browser gelesen (Chrome, sonst Brave/Chromium; nie unter dem Rueckfall dort) und veraltet damit nicht mehr.
# Gemessen am 22.10.2026 gegen cdn.nba.com (Akamai): Nur diese drei Header sind noetig.
#  - Origin UND Referer: ohne einen der beiden kommt HTTP 403.
#  - User-Agent mit AKTUELLER Chrome-Version: Chrome/131, /140 und /144 wurden mit 403 abgelehnt, /147 und /150 mit 200; Safari- und Firefox-User-Agent ebenso 403.
#    Kommt wieder 403, zuerst data/nba_headers.py (FALLBACK_MAJOR) pruefen.
# Nicht noetig (getestet bzw. entfernt): Accept, Accept-Language, Sec-Fetch-*, Connection.
NBA_CHROME_MAJOR = detect_chrome_major()
NBA_HEADERS = nba_headers(NBA_CHROME_MAJOR)

NBA_TIMEOUT_SECONDS = 10
NBA_CACHE_SECONDS = 20          # Ergebnisse UND Fehler so lange merken (Streamlit-Reruns)
NBA_RETRY_WAIT_SECONDS = 1.0    # Pause vor dem einen Wiederholungsversuch


class NbaLiveError(Exception):
    """Fehler beim NBA-Live-Abruf; str(e) ist eine kurze deutsche Meldung."""


_cache: dict[str, tuple[float, str, object]] = {}   # url -> (Zeitpunkt, "ok"|"err", Daten|Meldung)
_cache_lock = threading.Lock()


def _error_message(status) -> str:
    if status == 403:
        return ("NBA-Live-Daten: Zugriff vom NBA-Server abgelehnt (HTTP 403). "
                "Eventuell ist der Browser-User-Agent in data/nba_live.py veraltet.")
    if status == 429:
        return "NBA-Live-Daten: zu viele Anfragen (HTTP 429). Bitte kurz warten."
    if status == 404:
        return "NBA-Live-Daten: Spiel nicht gefunden (HTTP 404)."
    if status is None:
        return "NBA-Live-Daten: keine Verbindung zum NBA-Server."
    return f"NBA-Live-Daten: Abruf fehlgeschlagen (HTTP {status})."


def _nba_get_json(url: str):
    """Zentrale Abruffunktion fuer alle NBA-Endpunkte.

    - Header: NBA_HEADERS
    - Bei 403, 429, 5xx oder Netzwerkfehler hoechstens ein Wiederholungsversuch
    - Ergebnis und Fehler werden NBA_CACHE_SECONDS lang gemerkt
    """
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(url)
    if hit and now - hit[0] < NBA_CACHE_SECONDS:
        if hit[1] == "err":
            raise NbaLiveError(hit[2])
        return copy.deepcopy(hit[2])

    status = None
    data = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=NBA_HEADERS, timeout=NBA_TIMEOUT_SECONDS)
            status = r.status_code
            if status == 200:
                data = r.json()
                break
        except requests.exceptions.RequestException:
            status = None
        except ValueError:                      # 200, aber kein JSON
            status = 200
            break
        retryable = status is None or status in (403, 429) or status >= 500
        if not retryable or attempt == 1:
            break
        time.sleep(NBA_RETRY_WAIT_SECONDS)

    with _cache_lock:
        if data is not None:
            _cache[url] = (time.monotonic(), "ok", data)
        else:
            msg = "NBA-Live-Daten: ungueltige Antwort." if status == 200 else _error_message(status)
            _cache[url] = (time.monotonic(), "err", msg)
    if data is None:
        raise NbaLiveError(_cache[url][2])
    return copy.deepcopy(data)


def fetch_live_scoreboard():
    data = _nba_get_json(NBA_SCOREBOARD_URL)
    games = data.get("scoreboard", {}).get("games", [])

    live_games = []

    for g in games:
        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})

        live_games.append(
            {
                "game_id": g.get("gameId"),
                "status": g.get("gameStatusText"),
                "period": g.get("period"),
                "clock": g.get("gameClock"),
                "home_team": home.get("teamName"),
                "home_city": home.get("teamCity"),
                "home_score": home.get("score"),
                "away_team": away.get("teamName"),
                "away_city": away.get("teamCity"),
                "away_score": away.get("score"),
            }
        )

    return live_games


NBA_BOXSCORE_URL = (
    "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
)


def fetch_live_boxscore(game_id: str):
    url = NBA_BOXSCORE_URL.format(game_id=game_id)

    data = _nba_get_json(url)
    return data.get("game", {})


def get_current_quarter_points(game: dict):
    """
    Berechnet die Punkte im aktuellen Viertel aus dem NBA.com Boxscore.
    """
    current_period = int(game.get("period") or 1)

    home = game.get("homeTeam", {})
    away = game.get("awayTeam", {})

    home_periods = home.get("periods", [])
    away_periods = away.get("periods", [])

    home_q_points = 0
    away_q_points = 0

    for p in home_periods:
        if int(p.get("period") or 0) == current_period:
            home_q_points = int(p.get("score") or 0)

    for p in away_periods:
        if int(p.get("period") or 0) == current_period:
            away_q_points = int(p.get("score") or 0)

    return {
        "period": current_period,
        "home_q_points": home_q_points,
        "away_q_points": away_q_points,
        "quarter_total": home_q_points + away_q_points,
    }


def detect_foul_trouble(game: dict):
    """
    Erkennt Spieler mit Foul Trouble aus dem NBA.com Boxscore.
    """
    results = []

    for side in ["homeTeam", "awayTeam"]:
        team = game.get(side, {})
        team_name = f"{team.get('teamCity', '')} {team.get('teamName', '')}".strip()

        for player in team.get("players", []):
            stats = player.get("statistics", {})
            fouls = int(stats.get("foulsPersonal") or 0)
            points = int(stats.get("points") or 0)
            minutes = player.get("statistics", {}).get("minutesCalculated", "PT00M")
            starter = player.get("starter") == "1"
            oncourt = player.get("oncourt") == "1"
            played = player.get("played") == "1"

            if not played:
                continue

            severity = None

            if fouls >= 5:
                severity = "CRITICAL"
            elif fouls >= 4 and starter:
                severity = "HIGH"
            elif fouls >= 4:
                severity = "MEDIUM"

            if severity:
                results.append(
                    {
                        "team": team_name,
                        "player": player.get("name"),
                        "fouls": fouls,
                        "points": points,
                        "minutes": minutes,
                        "starter": starter,
                        "oncourt": oncourt,
                        "severity": severity,
                    }
                )

    return results


NBA_PLAYBYPLAY_URL = (
    "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
)


def fetch_playbyplay(game_id: str):
    url = NBA_PLAYBYPLAY_URL.format(game_id=game_id)

    data = _nba_get_json(url)
    return data.get("game", {}).get("actions", [])


def summarize_recent_actions(actions: list, limit: int = 20):
    """
    Fasst die letzten Aktionen aus dem Play-by-Play zusammen.
    """
    recent = actions[-limit:] if actions else []

    summary = {
        "actions": len(recent),
        "fouls": 0,
        "turnovers": 0,
        "free_throws": 0,
        "made_shots": 0,
        "missed_shots": 0,
        "substitutions": 0,
        "points": 0,
        "last_descriptions": [],
    }

    last_score_home = None
    last_score_away = None
    first_score_home = None
    first_score_away = None

    for a in recent:
        action_type = a.get("actionType")
        desc = a.get("description") or ""

        if action_type == "foul":
            summary["fouls"] += 1
        elif action_type == "turnover":
            summary["turnovers"] += 1
        elif action_type == "freethrow":
            summary["free_throws"] += 1
        elif action_type in ["2pt", "3pt"]:
            if desc.upper().startswith("MISS"):
                summary["missed_shots"] += 1
            else:
                summary["made_shots"] += 1
        elif action_type == "substitution":
            summary["substitutions"] += 1

        try:
            score_home = int(a.get("scoreHome") or 0)
            score_away = int(a.get("scoreAway") or 0)

            if first_score_home is None:
                first_score_home = score_home
                first_score_away = score_away

            last_score_home = score_home
            last_score_away = score_away
        except Exception:
            pass

        if desc:
            summary["last_descriptions"].append(desc)

    if (
        first_score_home is not None
        and first_score_away is not None
        and last_score_home is not None
        and last_score_away is not None
    ):
        summary["points"] = (last_score_home + last_score_away) - (
            first_score_home + first_score_away
        )

    if summary["free_throws"] >= 4 or summary["fouls"] >= 4:
        summary["pace_signal"] = "FREE_THROW_HEAVY"
    elif summary["turnovers"] >= 3 or summary["missed_shots"] >= 5:
        summary["pace_signal"] = "OFFENSE_STUCK"
    elif summary["points"] >= 10:
        summary["pace_signal"] = "SCORING_BURST"
    else:
        summary["pace_signal"] = "NORMAL"

    return summary
