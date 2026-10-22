"""
Druckt die Spieler-Punkte-Prognose (engine/player_forecast.py) gegen die Betano-Meilensteine (engine/player_odds.py). UNGEPRUEFT. Nur lesend, kein Netz.

Aufruf:  venv/bin/python analysis/print_player_forecast.py [Spieltag JJJJ-MM-TT | game_key]       (ohne Angabe: der neueste Spieltag mit Spielerquoten)
Je Spiel und Spieler: erwartete Minuten (Spanne), erwartete Punkte, dann je Meilenstein Quote, Buchmacher-Chance (inkl. Marge), Modell-Chance und Differenz in Prozentpunkten.
Zeilen, in denen das Modell mindestens 5 Prozentpunkte ueber dem Buchmacher liegt, sind mit "◀" markiert. Sortiert nach Team und erwarteten Punkten.
Die Ausgabe wird zusaetzlich nach analysis/results/player_forecast_<Tag>.txt geschrieben (nicht im Repository).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import player_history as ph                  # noqa: E402
from data import pre_match_store as store              # noqa: E402
from engine import player_forecast as pf               # noqa: E402
from engine import player_odds as po                   # noqa: E402

MARK_PP = 5.0


def pick_keys(entries: dict, arg: str | None) -> list[str]:
    with_players = [k for k, e in entries.items() if po.game_player_odds(entries, k)]
    if arg and arg in entries:
        return [arg]
    day = arg or (max(k.split("|", 1)[0] for k in with_players) if with_players else None)
    return sorted((k for k in with_players if k.split("|", 1)[0] == day), key=lambda k: k.split("|")[1]) if day else []


def data_stand() -> str:
    st = ph.player_history_status()
    parts = [f"{s}: {v['games']} Spiele, {v['players']} Spieler, Stand {(v['fetched_at'] or 'fehlt')[:16].replace('T', ' ')} UTC" for s, v in st["seasons"].items()]
    return "Spielverlauf: " + " | ".join(parts) + (f" | letzter Fehler: {st['last_error']}" if st.get("last_error") else "")


def render_game(key: str, entries: dict) -> list[str]:
    res = pf.forecast_game_players(key, entries)
    ctx = res["context"]
    L = [f"=== {key.split('|')[3]} @ {key.split('|')[2]}  ({key.split('|')[1][:16].replace('T', ' ')} UTC) ==="]
    L.append(f"Spielmodell: Spread {ctx['exp_spread']:+.1f} (positiv = Heim stärker), Total {ctx['exp_total']:.1f}" if ctx["found"] else
             "Spielmodell: KEIN Schnappschuss, Spread 0 angenommen")
    players = res["players"]
    players.sort(key=lambda p: (p["team"] or "", -(p["forecast"].get("expected_points") or -1), p["name"]))
    team = None
    for p in players:
        fc = p["forecast"]
        if p["team"] != team:
            team = p["team"]
            L.append(f"\n{team}")
        if not fc["ok"]:
            L.append(f"  {p['name']}: keine Prognose – {fc['reason']}")
            continue
        m = fc["minutes"]
        tags = f"  [{', '.join(fc['quality'])}]" if fc["quality"] else ""
        used = "/".join(f"{n}" for n in fc["games_used"].values())
        L.append(f"  {p['name']}: Minuten {m['mean']:.1f} ({m['low']:.0f}–{m['high']:.0f}), Punkte {fc['expected_points']:.1f}, Spiele {used}{tags}")
        for r in p["rows"]:
            model = fc["p_ge"].get(r["milestone"])
            if model is None:
                continue
            diff = model * 100 - r["percent"]
            L.append(f"      {r['milestone']:>2}+  Quote {r['odds']:5.2f} ({r['bookmaker'] or '-'})  Buchmacher {r['percent']:>3}%  Modell {model*100:>5.1f}%  {diff:+5.1f} PP" + ("  ◀" if diff >= MARK_PP else ""))
        for w in fc["warnings"] + p["warnings"]:
            L.append(f"      ! {w}")
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Spieler-Punkte-Prognose gegen Betano-Meilensteine (UNGEPRÜFT)")
    ap.add_argument("ziel", nargs="?", help="Spieltag JJJJ-MM-TT oder game_key (Standard: neuester Spieltag mit Spielerquoten)")
    args = ap.parse_args(argv)
    entries = store.load()["entries"]
    keys = pick_keys(entries, args.ziel)
    if not keys:
        print(f"Keine Spiele mit Spielerquoten gefunden für {args.ziel or 'irgendeinen Spieltag'}.")
        return 2
    day = keys[0].split("|", 1)[0]
    L = ["UNGEPRÜFT – " + pf.UNVERIFIED_TEXT, data_stand(), f"{MARGIN_NOTE}", f"Erstellt {datetime.now():%Y-%m-%d %H:%M}"]
    for k in keys:
        L += [""] + render_game(k, entries)
    text = "\n".join(L)
    print(text)
    out = ROOT / "analysis" / "results" / f"player_forecast_{day}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\n(gespeichert: {out.relative_to(ROOT)})")
    return 0


MARGIN_NOTE = f"Buchmacher = {po.MARGIN_LABEL}; Modell = P(Punkte ≥ Meilenstein) ohne Ausfälle, Gegner und Tempo. ◀ = Modell mindestens {MARK_PP:g} Prozentpunkte über dem Buchmacher."

if __name__ == "__main__":
    sys.exit(main())
