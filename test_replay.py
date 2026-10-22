import json
from pathlib import Path

from engine.replay import build_replay_snapshot

pbp_path = Path("data/mock/mock_playbyplay.json")

with pbp_path.open("r", encoding="utf-8") as f:
    actions = json.load(f)

# Beispiel: Replay bis Mitte Q2
snapshot = build_replay_snapshot(actions, max_game_seconds=18 * 60)

print("SNAPSHOT:")
print("Period:", snapshot["period"])
print("Clock:", snapshot["clock"])
print("Score Away/Home:", snapshot["score_away"], "-", snapshot["score_home"])
print("Actions:", len(snapshot["actions"]))
