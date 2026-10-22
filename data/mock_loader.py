import json
from pathlib import Path

MOCK_DIR = Path("data/mock")


def load_mock_scoreboard():
    path = MOCK_DIR / "mock_scoreboard.json"

    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_mock_boxscore():
    path = MOCK_DIR / "mock_boxscore.json"

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_mock_playbyplay():
    path = MOCK_DIR / "mock_playbyplay.json"

    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
