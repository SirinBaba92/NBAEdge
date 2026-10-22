import json
from pathlib import Path

from data.nba_live import fetch_live_boxscore, fetch_playbyplay

MOCK_DIR = Path("data/mock")
MOCK_DIR.mkdir(parents=True, exist_ok=True)

# Fallback bekannte fertige Spiele
CANDIDATE_GAME_IDS = [
    "0042500206",  # Pistons @ Cavaliers Game 6
    "0042500236",  # Spurs @ Timberwolves Game 6
]

saved = False

for game_id in CANDIDATE_GAME_IDS:
    print("Versuche Game ID:", game_id)

    try:
        box = fetch_live_boxscore(game_id)
        pbp = fetch_playbyplay(game_id)

        home = box.get("homeTeam", {})
        away = box.get("awayTeam", {})

        mock_game = {
            "game_id": game_id,
            "status": box.get("gameStatusText", "Final"),
            "period": box.get("period", 4),
            "clock": box.get("gameClock", "PT00M00.00S"),
            "home_team": home.get("teamName"),
            "home_city": home.get("teamCity"),
            "home_score": home.get("score"),
            "away_team": away.get("teamName"),
            "away_city": away.get("teamCity"),
            "away_score": away.get("score"),
        }

        with open(MOCK_DIR / "mock_scoreboard.json", "w", encoding="utf-8") as f:
            json.dump([mock_game], f, indent=2)

        with open(MOCK_DIR / "mock_boxscore.json", "w", encoding="utf-8") as f:
            json.dump(box, f, indent=2)

        with open(MOCK_DIR / "mock_playbyplay.json", "w", encoding="utf-8") as f:
            json.dump(pbp, f, indent=2)

        print(
            "Mock-Daten gespeichert:",
            mock_game["away_city"],
            mock_game["away_team"],
            "@",
            mock_game["home_city"],
            mock_game["home_team"],
        )

        saved = True
        break

    except Exception as e:
        print("Übersprungen:", e)

if not saved:
    print("Kein Mock-Spiel konnte gespeichert werden.")
