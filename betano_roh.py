"""
Rohdaten-Ansicht fuer EINEN Spieler bei Betano (zur Fehlersuche; speichert nichts, aendert nichts).

Start:  venv/bin/python betano_roh.py <Teamname> <Spielername>
        z. B.  venv/bin/python betano_roh.py Hornets "Brandon Miller"

2 Abrufe (Spielliste + Spielseite, 3 s Pause). Zeigt jede Stelle in den Betano-Daten, an der der Name vorkommt: Markt-Nummer, Typ, Name und alle Quoten.
So sieht man, ob Betano die Quoten selbst doppelt/gemischt liefert.
"""
from __future__ import annotations

import sys
import time
import urllib.error

import betano_import as bi
import betano_test as bt
import betano_test_spiel as bts


def main(argv=None, fetch_fn=bt.fetch, write=print, sleep=time.sleep) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        write(__doc__)
        return 2
    team, name = args[0].lower(), " ".join(args[1:]).lower()
    try:
        events = bi.list_events([bts.get(bt.URL, fetch_fn)])
        ev = next((e for e in events if any(team in t.lower() for t in e["teams"])), None)
        if ev is None:
            write(f"Kein Spiel mit „{args[0]}“ in der Betano-Liste.")
            return 1
        sleep(bi.PAUSE_SECONDS)
        data = bts.get(bi.BASE_URL + bts.event_path(ev["url"]), fetch_fn)
    except urllib.error.HTTPError as e:
        write(f"Betano hat NICHT normal geantwortet: HTTP {e.code}.")
        return 1
    except Exception as e:
        write(f"Fehler: {type(e).__name__}: {e}")
        return 1
    write(f"{ev['teams'][0]} – {ev['teams'][1]}: Fundstellen für „{name}“")
    found = 0
    for i, m in enumerate(data["event"].get("markets", [])):
        hits = []
        if name in str(m.get("name", "")).lower() and m.get("selections"):
            hits.append(("Marktname", [(s["name"], s["price"]) for s in m["selections"]]))
        for r in (m.get("tableLayout") or {}).get("rows", []):
            if name in str(r.get("title", "")).lower():
                sels = [s for gs in r.get("groupSelections", []) for s in gs.get("selections", [])]
                hits.append((f"Zeile „{r['title']}“ (rowId {r.get('rowId')})", [(s["name"], s["price"]) for s in sels]))
        for label, sels in hits:
            found += 1
            write(f"\n#{i} Typ {m.get('type')} · {m.get('name')} · Markt-ID {m.get('id')} · {label}")
            write("   " + ", ".join(f"{a} @ {b}" for a, b in sels))
    write(f"\n{found} Fundstelle(n). Es wurde nichts gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
