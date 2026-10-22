"""
Druckt die Spieler-Punkte-Prognose (engine/player_forecast.py) gegen die Betano-Meilensteine (engine/player_odds.py). UNGEPRUEFT. Nur lesend, kein Netz.

Aufruf:  venv/bin/python analysis/print_player_forecast.py [Spieltag JJJJ-MM-TT | game_key]       (ohne Angabe: der neueste Spieltag mit Spielerquoten)
Je Spiel und Spieler: erwartete Minuten (Spanne), erwartete Punkte, dann je Meilenstein Quote, Buchmacher-Chance (inkl. Marge), Modell-Chance und Differenz in Prozentpunkten.
Mit Teamabgleich (P6b): Summe der Spieler an den Teampunkten des Spielmodells ausgerichtet; Differenz bezieht sich auf "Modell Team"; ◀ ab 5 PP ueber, ▼ ab 5 PP unter dem Buchmacher. Sortiert nach Team und erwarteten Punkten.
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
    L.append(f"Spielmodell: Spread {ctx['exp_spread']:+.1f} (positiv = Heim stärker), Total {ctx['exp_total']:.1f}, Teampunkte Heim {ctx['home_score']:.1f} / Gast {ctx['away_score']:.1f}" if ctx["found"] else
             "Spielmodell: KEIN Schnappschuss, Spread 0 angenommen, kein Teamabgleich")
    for team, t in res["teams"].items():
        if t.get("matched"):
            mins = f", Minuten {t['minutes_before']:.0f} → {t['minutes_after']:.0f}" if abs(t["minutes_before"] - t["minutes_after"]) > 0.5 else f", Minuten {t['minutes_before']:.0f}"
            nh = f", ohne Verlauf (10 Min., Liga-Schnitt): {', '.join(t['no_history'])}" if t["no_history"] else ""
            L.append(f"Team {team}: Spieler-Summe {t['player_sum']:.1f} → Teampunkte {t['team_points']:.1f}, Faktor {t['factor']:.2f} (Rotation {t['members']} Spieler{mins}){nh}")
            for n in (t.get("note"), t.get("minutes_note")):
                if n:
                    L.append(f"  ! {n}")
        else:
            L.append(f"Team {team}: {t.get('note') or 'kein Teamabgleich'}")
    players = res["players"]
    players.sort(key=lambda p: (p["team"] or "", -(p["forecast"].get("expected_points_adjusted") or p["forecast"].get("expected_points") or -1), p["name"]))
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
        L.append(f"  {p['name']}: Minuten {m['mean']:.1f} → {fc['minutes_adjusted']:.1f} ({m['low']:.0f}–{m['high']:.0f}), Punkte roh {fc['expected_points_raw']:.1f} → Team {fc['expected_points_adjusted']:.1f}, Spiele {used}{tags}")
        for r in p["rows"]:
            raw, adj = fc["p_ge_raw"].get(r["milestone"]), fc["p_ge_adjusted"].get(r["milestone"])
            if raw is None or adj is None:
                continue
            diff = adj * 100 - r["percent"]
            mark = "  ◀" if diff >= MARK_PP else "  ▼" if diff <= -MARK_PP else ""
            L.append(f"      {r['milestone']:>2}+  Quote {r['odds']:5.2f} ({r['bookmaker'] or '-'})  Buchmacher {r['percent']:>3}%  Modell roh {raw*100:>5.1f}%  Modell Team {adj*100:>5.1f}%  {diff:+5.1f} PP{mark}")
        for w in fc["warnings"] + p["warnings"] + ([fc["team_note"]] if fc.get("team_note") else []):
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


MARGIN_NOTE = f"Buchmacher = {po.MARGIN_LABEL}; Modell = P(Punkte ≥ Meilenstein) ohne Ausfälle, Gegner und Tempo. Differenz = Modell Team minus Buchmacher; ◀ = Modell mindestens {MARK_PP:g} Prozentpunkte über dem Buchmacher, ▼ = mindestens {MARK_PP:g} darunter."

if __name__ == "__main__":
    sys.exit(main())
