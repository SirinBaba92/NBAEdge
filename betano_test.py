"""
Kleiner Verbindungstest fuer Betano (EIN Abruf, speichert nichts, aendert keine Daten).

Start:  venv/bin/python betano_test.py

Holt nur die NBA-Spielliste von betano.de und zeigt:
- ob Betano antwortet (Statuscode) oder blockiert,
- wie viele Spiele zurueckkommen,
- welche davon zu deiner Spieleliste von eingabe.py passen (nur Lesen aus dem lokalen Zwischenspeicher).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

import eingabe as ei

URL = "https://www.betano.de/api/sport/basketball/usa/nba/441g/?req=la,s,stnf,c,mb"


def fetch(url: str = URL, timeout: int = 30, accept: str = "application/json") -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "NBAEdge/1.0 (persoenliche Nutzung)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def main(fetch_fn=fetch, write=print) -> int:
    write("Betano-Verbindungstest: 1 Abruf der NBA-Spielliste ...")
    t0 = time.time()
    try:
        status, ctype, body = fetch_fn()
    except urllib.error.HTTPError as e:
        write(f"Betano hat NICHT normal geantwortet: HTTP {e.code} ({e.reason}).")
        write("Das heißt meist: Zugriff ohne Browser wird blockiert (Bot-Schutz) oder die Adresse hat sich geändert. Es wurde nichts gespeichert.")
        return 1
    except Exception as e:                                          # Netz, DNS, Zeitueberschreitung
        write(f"Keine Verbindung zu Betano: {type(e).__name__}: {e}")
        return 1
    write(f"Antwort nach {time.time() - t0:.1f} s: HTTP {status}, Typ {ctype or '?'}, {len(body) / 1024:.0f} KB.")
    try:
        data = json.loads(body.decode("utf-8"))["data"]
        events = [e for b in data.get("blocks", []) for e in b.get("events", [])]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        write("Die Antwort ist kein Spielplan im erwarteten Format (vermutlich eine Sperrseite statt Daten). Der Anfang der Antwort:")
        write(body[:300].decode("utf-8", "replace"))
        return 1
    write(f"Spiele in der Betano-Liste: {len(events)}")
    from betano_import import canon
    names = {tuple(canon(p["name"]) for p in e.get("participants", [])[:2]) for e in events}
    mine = ei.list_games()
    if not mine:
        write("Deine Spieleliste von eingabe.py ist leer (keine kommenden Spiele im Zwischenspeicher), Abgleich nicht möglich.")
        return 0
    for g in mine:
        hit = (g["home"], g["away"]) in names or (g["away"], g["home"]) in names
        write(f"  {'gefunden ' if hit else 'FEHLT    '} {ei.start_label(g['start'])}  {g['home']} – {g['away']}")
    write("Fertig. Es wurde nichts gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
