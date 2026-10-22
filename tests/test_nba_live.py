"""Offline-Tests fuer data/nba_live.py (Header, Fehlermeldungen, Wiederholung, 20-s-Cache).
requests.get und die Uhr sind ersetzt: kein Netzwerkzugriff. Aufruf: venv/bin/python tests/test_nba_live.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
import data.nba_live as nl

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

class Resp:
    def __init__(self, status, payload=None, bad_json=False):
        self.status_code, self._p, self._bad = status, payload, bad_json
    def json(self):
        if self._bad: raise ValueError("kein JSON")
        return self._p

calls, queue, clock = [], [], [1000.0]
def fake_get(url, headers=None, timeout=None):
    calls.append((url, headers, timeout))
    item = queue.pop(0)
    if isinstance(item, Exception): raise item
    return item
nl.requests.get = fake_get
nl.time.sleep = lambda *_: None
nl.time.monotonic = lambda: clock[0]
def reset(): calls.clear(); queue.clear(); nl._cache.clear()

U = "https://cdn.nba.com/x.json"
# Header
check("Header: genau User-Agent, Origin, Referer", set(nl.NBA_HEADERS) == {"User-Agent", "Origin", "Referer"})
check("User-Agent nennt Chrome/%d" % nl.NBA_CHROME_MAJOR, f"Chrome/{nl.NBA_CHROME_MAJOR}." in nl.NBA_HEADERS["User-Agent"])

# 403 -> ein Wiederholungsversuch, deutsche Meldung, Fehler wird gecacht
reset(); queue += [Resp(403), Resp(403)]
try: nl._nba_get_json(U); err = None
except nl.NbaLiveError as e: err = str(e)
check("403: genau 1 Wiederholung (2 Requests)", len(calls) == 2)
check("403: kurze deutsche Meldung ohne Roh-Fehlertext", err and "403" in err and "abgelehnt" in err and "<HTML>" not in err and "Traceback" not in err, err)
check("Header werden bei jedem Request mitgegeben", all(c[1] is nl.NBA_HEADERS for c in calls))
try: nl._nba_get_json(U); err2 = str(None)
except nl.NbaLiveError as e: err2 = str(e)
check("Fehler wird 20 s gecacht (kein neuer Request)", len(calls) == 2 and err2 == err)
clock[0] += 19.9
try: nl._nba_get_json(U)
except nl.NbaLiveError: pass
check("nach 19,9 s noch gecacht", len(calls) == 2)
clock[0] += 0.2; queue += [Resp(200, {"a": 1})]
check("nach 20,1 s neuer Abruf, Erfolg ersetzt den Fehler", nl._nba_get_json(U) == {"a": 1} and len(calls) == 3)

# Erfolg cachen, Kopie zurueckgeben
reset(); queue += [Resp(200, {"game": {"x": [1]}})]
a = nl._nba_get_json(U); a["game"]["x"].append(2); b = nl._nba_get_json(U)
check("Erfolg: ein Request, Cache liefert unveraenderte Kopie", len(calls) == 1 and b == {"game": {"x": [1]}})

# 429, Netzwerkfehler, 404, 500, kaputtes JSON
reset(); queue += [Resp(429), Resp(200, {"ok": 1})]
check("429 dann 200: Wiederholung hat Erfolg", nl._nba_get_json(U) == {"ok": 1} and len(calls) == 2)
reset(); queue += [Resp(429), Resp(429)]
try: nl._nba_get_json(U)
except nl.NbaLiveError as e: m429 = str(e)
check("429 zweimal: Meldung 'zu viele Anfragen'", "zu viele Anfragen" in m429 and len(calls) == 2, m429)
reset(); queue += [requests.exceptions.ConnectionError("Name or service not known: https://cdn..."), requests.exceptions.Timeout("t")]
try: nl._nba_get_json(U)
except nl.NbaLiveError as e: mnet = str(e)
check("Netzwerkfehler: 1 Wiederholung, deutsche Meldung ohne Roh-Text", len(calls) == 2 and "keine Verbindung" in mnet and "Name or service" not in mnet, mnet)
reset(); queue += [Resp(404)]
try: nl._nba_get_json(U)
except nl.NbaLiveError as e: m404 = str(e)
check("404: keine Wiederholung", len(calls) == 1 and "nicht gefunden" in m404, m404)
reset(); queue += [Resp(500), Resp(502)]
try: nl._nba_get_json(U)
except nl.NbaLiveError as e: m5 = str(e)
check("5xx: 1 Wiederholung, Meldung mit Statuscode", len(calls) == 2 and "HTTP 502" in m5, m5)
reset(); queue += [Resp(200, bad_json=True)]
try: nl._nba_get_json(U)
except nl.NbaLiveError as e: mj = str(e)
check("200 ohne JSON: Meldung 'ungueltige Antwort', keine Wiederholung", len(calls) == 1 and "ungueltige" in mj, mj)

# Oeffentliche Funktionen nutzen die zentrale Funktion
reset()
sb = {"scoreboard": {"games": [{"gameId": "0022600001", "gameStatusText": "Q1", "period": 1, "gameClock": "PT11M00.00S",
      "homeTeam": {"teamName": "Pistons", "teamCity": "Detroit", "score": 2}, "awayTeam": {"teamName": "Celtics", "teamCity": "Boston", "score": 0}}]}}
queue += [Resp(200, sb), Resp(200, {"game": {"period": 1}}), Resp(200, {"game": {"actions": [{"actionType": "2pt"}]}})]
games = nl.fetch_live_scoreboard(); box = nl.fetch_live_boxscore("0022600001"); pbp = nl.fetch_playbyplay("0022600001")
check("Scoreboard/Boxscore/Play-by-Play liefern wie vorher", games[0]["game_id"] == "0022600001" and games[0]["home_team"] == "Pistons" and box == {"period": 1} and pbp == [{"actionType": "2pt"}])
check("alle drei Abrufe nutzen cdn.nba.com mit denselben Headern", len(calls) == 3 and all("cdn.nba.com" in c[0] and c[1] is nl.NBA_HEADERS for c in calls))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
