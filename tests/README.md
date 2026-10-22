# NBAEdge Regression Audit

## Offline Audit Mode

Open `config/runtime.py` and set:

```python
OFFLINE_AUDIT_MODE = True
```

When enabled, `app.py` uses `data/mock/` fixtures for scoreboard, boxscore,
play-by-play, projections, value bets and history. Odds API, injury/news API,
NBA live API and BallDontLie requests are skipped.

## Regression Tests

Run the replay regression checks:

```bash
python3 tests/test_replay_regression.py
```

Run the tabular full audit report:

```bash
python3 tests/run_full_audit.py
```

The audit covers replay minutes `5, 10, 15, 20, 30, 40` and validates snapshot,
quarter state, possessions, momentum, master live factor, edge detection and
projection sanity.
