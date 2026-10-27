"""make_proj aus tests/test_snapshots.py als Hilfsmodul (ohne den Testlauf)."""
import datetime as dt
import data.pre_match_store as ps
from engine.projection import compute_projection
K, P = "New York Knicks", "Philadelphia 76ers"
def make_proj(home=K, away=P, start=None, spread=4.5, total=231.5, tt_home=None, tt_away=None, src="Cache", date="2026-10-21"):
    mk = lambda v, bm="Pinnacle": {"line": v, "source": src if v is not None else None, "bookmaker": bm if v is not None else "", "at": 1_790_000_000.0 if v is not None else None, "at_iso": None,
                                  "cache_line": v, "cache_source": src, "cache_at": 1_790_000_000.0, "warn": False}
    pr = compute_projection({"home_team": home, "away_team": away, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38},
                            market_total=total, market_spread=spread, game_date=date)
    pr.update(game_date=date, game_start=start, market_lines={"spread": mk(spread), "total": mk(total), "team_total_away": mk(tt_away), "team_total_home": mk(tt_home)},
              _line_inputs={"game_start": start, "entry_key": ps.game_key(date, start, home, away)})
    return pr

