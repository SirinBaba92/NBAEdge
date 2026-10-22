"""
Verbindungstest Teil 2 fuer Betano: EIN Spiel in drei Varianten abrufen (4 Abrufe mit Pausen: Spielliste + 3 Varianten der Spielseite), speichert nichts.

Start:  venv/bin/python betano_test_spiel.py            # erstes Spiel deiner Liste von eingabe.py
        venv/bin/python betano_test_spiel.py 3          # Spiel Nr. 3 deiner Liste

Varianten: A = Daten-Abruf wie bisher (nur Tab "Beliebt"), B = Daten-Abruf mit bt=6 (Tab "Alle"), C = die Spielseite selbst (HTML) mit bt=6.
Zeigt nebeneinander, wie viele Maerkte, Team-Total-Linien und Spieler jede Variante liefert.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error

import betano_import as bi
import betano_test as bt
import eingabe as ei
from data import rosters


def event_path(url: str) -> str:
    """'/quoten/orlando-magic-atlanta-hawks/91836666/' -> '/api/quoten/orlando-magic-atlanta-hawks/91836666/?req=...'"""
    return url.replace("/quoten/", "/api/quoten/", 1) + bi.EVENT_REQ


def get(url: str, fetch_fn) -> dict:
    status, _ctype, body = fetch_fn(url)
    return json.loads(body.decode("utf-8"))["data"]


def summarize(data: dict, g: dict) -> dict:
    p = bi.parse_event(data, g["home"], g["away"])
    split, miss = bi.team_split(p["players"], rosters.load().get("teams", {}), g)
    ev = data["event"]
    return {"p": p, "maerkte": f"{len(ev.get('markets', []))} von {ev.get('totalMarketsAvailable')}", "miss": miss,
            "spieler": f"{len(p['players'])} (im Kader: {len(split['home'])}+{len(split['away'])})"}


def main(argv=None, fetch_fn=bt.fetch, write=print, sleep=time.sleep) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    games = ei.list_games()
    if not games:
        write("Deine Spieleliste von eingabe.py ist leer (keine kommenden Spiele im Zwischenspeicher).")
        return 1
    n = int(args[0]) if args and args[0].isdigit() else 1
    if not 1 <= n <= len(games):
        write(f"Spielnummer 1 bis {len(games)} angeben.")
        return 2
    g = games[n - 1]
    H, A = ei.nick(g["home"]), ei.nick(g["away"])
    write(f"Test mit Spiel {n}: {g['home']} – {g['away']} ({ei.start_label(g['start'])} Uhr)")
    variants = {}
    try:
        lst = get(bt.URL, fetch_fn)
        ev = bi.match_event(g, bi.list_events([lst]))
        if ev is None:
            write("Dieses Spiel steht nicht in der Betano-Liste.")
            return 1
        api = bi.BASE_URL + event_path(ev["url"])
        page = bi.BASE_URL + ev["url"] + "?bt=6"
        for key, label, fn in (("A", "Daten-Abruf (Tab Beliebt)", lambda: get(api, fetch_fn)),
                               ("B", "Daten-Abruf mit bt=6 (Tab Alle)", lambda: get(api + "&bt=6", fetch_fn)),
                               ("C", "Spielseite (HTML) mit bt=6", lambda: bi.parse_initial_state(fetch_fn(page, accept="text/html")[2].decode("utf-8", "replace")))):
            write(f"Variante {key}: {label} ... (nach {bi.PAUSE_SECONDS:g} s Pause)")
            sleep(bi.PAUSE_SECONDS)
            try:
                d = fn()
                variants[key] = summarize(d, g) if d else None
                if d is None:
                    write("   keine verwertbaren Daten in der Antwort.")
            except urllib.error.HTTPError as e:
                write(f"   Betano hat NICHT normal geantwortet: HTTP {e.code} ({e.reason}).")
                variants[key] = None
            except (ValueError, KeyError, TypeError):
                write("   Antwort hat nicht das erwartete Format.")
                variants[key] = None
    except urllib.error.HTTPError as e:
        write(f"Betano hat NICHT normal geantwortet: HTTP {e.code} ({e.reason}). Es wurde nichts gespeichert.")
        return 1
    except Exception as e:
        write(f"Keine Verbindung zu Betano: {type(e).__name__}: {e}")
        return 1
    write("")
    write(f"{'':34}{'A':>18}{'B':>18}{'C':>18}")
    def row(label, fn):
        write(f"{label:34}" + "".join(f"{(fn(variants[k]) if variants.get(k) else '–'):>18}" for k in "ABC"))
    row("Märkte (in Antwort von gesamt)", lambda v: v["maerkte"])
    row("Spread-Linien", lambda v: str(len(v["p"]["spread"]["lines"])))
    row("Total-Linien", lambda v: str(len(v["p"]["total"]["lines"])))
    row(f"Team Total {H}: Linien", lambda v: str(len(v["p"]["team"]["home"]["lines"])))
    row(f"Team Total {A}: Linien", lambda v: str(len(v["p"]["team"]["away"]["lines"])))
    row("Spieler (im Kader)", lambda v: v["spieler"])
    for k in "ABC":
        if variants.get(k):
            p = variants[k]["p"]
            write(f"{k}: Hauptlinien Spread {'–' if p['spread']['main'] is None else ei.sgn(p['spread']['main'])}, Total {'–' if p['total']['main'] is None else ei.fnum(p['total']['main'])}, "
                  f"Team Totals {H} {p['team']['home']['main']} / {A} {p['team']['away']['main']}"
                  + (f"; nicht zuordenbar: {', '.join(variants[k]['miss'])}" if variants[k]["miss"] else ""))
    write("Fertig. Es wurde nichts gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
