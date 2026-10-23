"""Simulierte Netzwerkantworten fuer Offline-Tests (Odds API, BallDontLie, cdn.nba.com).
install() ersetzt requests.get; jede nicht vorgesehene URL loest einen Fehler aus.
fresh_env() legt fuer Odds-Cache, Odds-Log und BallDontLie-Cache ein leeres Temp-Verzeichnis an
(das Projekt-data/ bleibt unberuehrt) und setzt alle Zaehler zurueck."""
import os as _os
_os.environ.setdefault("NBAEDGE_ALL_TABS", "1")      # bestehende Tests sehen alle Tabs gleichzeitig (st.tabs); die lazy Navigation prueft tests/test_lazy_tabs.py
import datetime as dt
import os
import tempfile
from pathlib import Path

import requests

SPIELE = [("New York Knicks", "Philadelphia 76ers", -4.5, 232.0),
          ("San Antonio Spurs", "Oklahoma City Thunder", 0.2, 230.7),
          ("Detroit Pistons", "Boston Celtics", 1.5, 219.8)]
odds_markets_requested = []        # Markt-Parameter jedes Odds-API-Requests (aeltere Tests)
state = {"commence_offsets": {}, "remaining": 452, "odds_status": 200, "odds_status_seq": [], "odds_calls": [], "bdl_calls": 0, "bdl_status": 200,
         "nba_calls": 0, "scoreboard": [], "nba_status": 200, "board_date": None, "boxes": {}, "espn": {"events": []}, "espn_status": 200, "espn_calls": 0, "nba_urls": []}
SECRET = "GEHEIMER-TESTKEY-123"


def scoreboard_game(game_id, away, home, period, status, clock="PT05M00.00S", away_score=0, home_score=0):
    a_city, a_name = away.rsplit(" ", 1) if " " in away else ("", away)
    h_city, h_name = home.rsplit(" ", 1) if " " in home else ("", home)
    return {"gameId": game_id, "gameStatusText": status, "period": period, "gameClock": clock,
            "homeTeam": {"teamName": h_name, "teamCity": h_city, "score": home_score},
            "awayTeam": {"teamName": a_name, "teamCity": a_city, "score": away_score}}


def commence_for(home, now=None):
    """Anpfiff (UTC-ISO): Standard jetzt + 3 Std.; mit state['commence_offsets'][home] (Sekunden relativ zu jetzt) ueberschreibbar."""
    now = now or dt.datetime.now(dt.timezone.utc)
    off = state["commence_offsets"].get(home, 3 * 3600)
    return (now + dt.timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%SZ")


def events(markets, spiele=SPIELE):
    out = []
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for h, a, pt, tot in spiele:
        bms = []
        for bk in ("pinnacle", "draftkings", "fanduel"):
            ms = []
            if "h2h" in markets:
                ms.append({"key": "h2h", "outcomes": [{"name": h, "price": 1.5}, {"name": a, "price": 2.8}]})
            if "totals" in markets:
                ms.append({"key": "totals", "outcomes": [{"name": "Over", "point": tot, "price": 1.91}, {"name": "Under", "point": tot, "price": 1.91}]})
            if "spreads" in markets:
                ms.append({"key": "spreads", "outcomes": [{"name": h, "point": pt, "price": 1.91}, {"name": a, "point": -pt, "price": 1.91}]})
            for m in ms:
                m["last_update"] = now_iso
            bms.append({"key": bk, "last_update": now_iso, "markets": ms})
        out.append({"id": f"ev-{h.split()[-1].lower()}", "home_team": h, "away_team": a, "commence_time": commence_for(h), "bookmakers": bms})
    return out


class Resp:
    def __init__(self, payload, status=200, headers=None):
        self._p, self.status_code, self.content = payload, status, b"x"
        self.headers = headers if headers is not None else {"x-requests-remaining": "999"}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def fresh_env(remaining=452, odds_status=200):
    """Neues leeres Temp-Verzeichnis fuer alle Caches/Logs, Zaehler zurueck, Credits setzen."""
    tmp = Path(tempfile.mkdtemp(prefix="nbaedge_test_"))
    os.environ["NBAEDGE_ODDS_CACHE"] = str(tmp / "odds_cache.json")
    os.environ["NBAEDGE_ODDS_LOG"] = str(tmp / "odds_calls.log")
    os.environ["NBAEDGE_UPCOMING_CACHE"] = str(tmp / "upcoming_cache.json")
    os.environ["NBAEDGE_PREGAME_LINES"] = str(tmp / "pregame_lines.json")
    os.environ["NBAEDGE_TRACKING_DIR"] = str(tmp / "tracking")
    os.environ["NBAEDGE_ROSTERS"] = str(tmp / "rosters.json")          # nie die echte Kaderdatei
    os.environ["ODDS_API_KEY"] = SECRET
    os.environ["NBAEDGE_AUTOMATION_LOG"] = str(tmp / "automation.log")
    state["commence_offsets"] = {}
    state.update(remaining=remaining, odds_status=odds_status, odds_status_seq=[], odds_calls=[], bdl_calls=0, bdl_status=200, nba_calls=0, scoreboard=[],
                 nba_status=200, board_date=None, boxes={}, espn={"events": []}, espn_status=200, espn_calls=0, nba_urls=[])
    odds_markets_requested.clear()
    import data.odds_client as oc, data.live_market as lm, data.nba_live as nl
    oc._mem.update(path=None, mtime=None, obj=None)
    lm._CACHE.update(fetched_at=0.0, lines={})
    nl._cache.clear()
    return tmp


def _no_real_playerindex(*a, **k):
    raise AssertionError("Tests duerfen nicht an stats.nba.com abrufen (PlayerIndex)")


def install(spiele=SPIELE):
    try:
        import nba_api.stats.endpoints as _ep
        _ep.PlayerIndex = _no_real_playerindex                          # kein echtes Netz fuer den Kader-Abruf
    except Exception:
        pass
    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        if "the-odds-api.com" in url:
            odds_markets_requested.append(params["markets"])
            n_markets = len(params["markets"].split(","))
            cost = n_markets * len(params["regions"].split(","))
            state["odds_calls"].append({"markets": params["markets"], "regions": params["regions"]})
            status = state["odds_status_seq"].pop(0) if state["odds_status_seq"] else state["odds_status"]
            if status != 200:
                return Resp({"message": "fehler"}, status, {"x-requests-remaining": str(state["remaining"])})
            state["remaining"] -= cost
            return Resp(events(params["markets"], spiele), 200,
                        {"x-requests-remaining": str(state["remaining"]), "x-requests-last": str(cost)})
        if "balldontlie.io" in url:
            if params and "start_date" in params:
                state["bdl_calls"] += 1
                if state["bdl_status"] != 200:
                    return Resp({}, state["bdl_status"])
                return Resp({"data": [{"id": 900 + i, "date": dt.date.today().isoformat(), "datetime": commence_for(h).replace("Z", ".000Z"), "status": "7:00 PM ET", "postponed": False,
                                       "home_team": {"full_name": h}, "visitor_team": {"full_name": a}} for i, (h, a, _, _) in enumerate(spiele)], "meta": {}})
            return Resp({"data": [], "meta": {}})
        if "cdn.nba.com" in url:
            state["nba_calls"] += 1
            state["nba_urls"].append(url)
            if state["nba_status"] != 200:                                  # z. B. 403/429 fuer alle cdn.nba.com-Abrufe
                return Resp({}, state["nba_status"])
            if "scoreboard" in url:
                board = {"games": state["scoreboard"]}
                if state["board_date"]:
                    board["gameDate"] = state["board_date"]
                return Resp({"scoreboard": board})
            for gid, box in state["boxes"].items():                         # eigene Boxscores je game_id (Live-Feed-Tests)
                if gid in url:
                    return Resp({"game": box})
            return Resp({"game": {"homeTeam": {}, "awayTeam": {}, "actions": []}})
        if "espn.com" in url:
            state["espn_calls"] += 1
            if state["espn_status"] != 200:
                return Resp({}, state["espn_status"])
            return Resp(state["espn"])
        raise AssertionError(f"unerlaubter Abruf: {url}")
    requests.get = fake_get
