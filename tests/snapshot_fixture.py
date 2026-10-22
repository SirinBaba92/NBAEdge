"""Hilfen fuer Browsertests: ein beendetes Spiel (Schnappschuss + Ergebnis) in die Temp-Tracking-Datei schreiben. Nur Temp-Ordner (NBAEDGE_TRACKING_DIR)."""
import json, time
import data.pre_match_store as ps
import data.projection_snapshots as snap
from engine.projection import compute_projection


def finished_game(home="Miami Heat", away="Chicago Bulls", home_pts=118, away_pts=100, date="2026-10-21"):
    now = time.time()
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 5 * 3600))
    mk = lambda v: {"line": v, "source": "Cache" if v is not None else None, "bookmaker": "Pinnacle" if v is not None else "", "at": now - 9 * 3600 if v is not None else None, "at_iso": None,
                    "cache_line": v, "cache_source": "Cache", "cache_at": now - 9 * 3600, "warn": False}
    pr = compute_projection({"home_team": home, "away_team": away, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38},
                            market_total=224.5, market_spread=3.5, game_date=date)
    pr.update(game_date=date, game_start=start, market_lines={"spread": mk(3.5), "total": mk(224.5), "team_total_away": mk(None), "team_total_home": mk(None)},
              _line_inputs={"game_start": start, "entry_key": ps.game_key(date, start, home, away)})
    model = {"file_mtime": None, "file_size": 0, "sha1": "fixture", "ratings_as_of": "2026-10-20"}
    key = pr["_line_inputs"]["entry_key"]
    content = snap.build_snapshot(pr, None, model)
    data = {"version": snap.SNAP_VERSION, "format": snap.FORMAT, "updated_at": None, "games": {key: {
        "game_date": date, "start_utc": ps.normalize_start(start), "home": home, "away": away, "card": snap._jsonable({k: v for k, v in pr.items() if k != "_line_inputs"}),
        "versions": [{"saved_at": ps.iso_now(now - 9 * 3600), "hash": snap.content_hash(content), **content}],
        "result": {"home_points": home_pts, "away_points": away_pts, "recorded_at": ps.iso_now(now), "source": "update_model"}}}}
    snap._atomic_write(snap.snapshot_path(), data)
    snap._cache.update(sig=None, data=None)
    return key
