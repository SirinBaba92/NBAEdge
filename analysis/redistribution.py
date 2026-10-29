"""
Wohin fliessen Minuten und Punkte eines ausgefallenen Spielers? (rein beschreibend, ohne Netz; keine bestehende Datei wird veraendert). Schreibt analysis/results/redistribution.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/redistribution.py

WICHTIG - was im Projekt fehlt: Listen der Inaktiven (INACTIVE_INJURY, INACTIVE_GLEAGUE_TWOWAY) fuer 2023-24 bis 2025-26 liegen NICHT vor (die lokalen Spielerdaten sind der LeagueGameLog ohne Inaktive; die Boxscores des Recorders
enthalten nur 2026-27 und keine Inaktiven). Auch die Prognose-Variante C (Neuberechnung mit Ausfaellen) steht nicht in den Dateien (nur A roh und B Teamabgleich ohne Ausfaelle), und eine Position gibt es lokal nicht.
Deshalb gilt hier eine NAeHERUNG fuer 'Ausfall': ein Stammspieler, der laut seinem eigenen Verlauf erwartet worden waere, aber im Spiel nicht eingesetzt wurde:
  - Er hat im letzten Spiel seines Teams (gleiche Saison) gespielt (Minuten > 0) und im aktuellen Spiel nicht (keine Zeile oder 0 Minuten),
  - er spielt fuer dasselbe Team in mindestens einem der naechsten 5 Teamspiele wieder (schliesst Wechsel und lange Ausfaelle aus),
  - Mittel seiner letzten 10 Spiele vor dem Spieltag (mindestens 5 Spiele): Minuten > 20. Diese Mittelwerte (Minuten und Punkte) ersetzen 'erwartete Minuten/Punkte roh' des Ausfalls, weil fuer Nichtgespielte keine Prognosezeile existiert.
  Die Naeherung enthaelt auch Ruhetage, Entscheidungen des Trainers und nicht gemeldete Verletzungen; sie trennt nicht zwischen Verletzung und anderen Gruenden.
Nur Team-Spiele mit genau EINEM solchen Ausfall; ohne Verlaengerungsspiele (Teamsumme der Spielerminuten > 245) und ohne Spiel 0022400061.
Mitspieler = Spieler des Teams in forecast_players_<Saison>.csv.gz (nur Spieler mit Prognose UND Minuten > 0). Abweichung = tatsaechlich minus erwartet roh. Rueckfluss = Summe der Abweichungen aller Mitspieler / Minuten bzw. Punkte des Ausfalls.
Vergleichswert: Team-Spiele ohne jeden Ausfall-Kandidaten (Summe der Abweichungen dort, absolut), damit sichtbar ist, was auch ohne Ausfall in der Summe steckt.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from analysis import ppm_decomposition as pdc  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
LOOKBACK = 10
MIN_HISTORY = 5
RETURN_WITHIN = 5
OUT_MIN = 20.0
ROLES = (("Starter (>28)", 28.0, 1e9), ("mittlere (12-28)", 12.0, 28.0), ("Bank (<12)", -1.0, 12.0))
SIZES = (("20 bis 28 Min.", 20.0, 28.0), ("ueber 28 Min.", 28.0, 1e9))
OUT = HERE / "results" / "redistribution.txt"


# ----------------------------------------------------------------------------- Ausfaelle
class Rosters:
    """Teamspiele je (Saison, Team) in Datumsfolge mit Kader (Spieler mit Minuten > 0) und Verlauf je Spieler."""

    def __init__(self, rows: list[dict]):
        games = defaultdict(dict)
        self.hist = defaultdict(list)
        for r in rows:
            if r["minutes"] <= 0:
                continue
            games[(r["season"], r["team"])].setdefault((pdc.date_int(r["date"]), str(r["game_id"])), set()).add(int(r["person_id"]))
            self.hist[int(r["person_id"])].append((pdc.date_int(r["date"]), float(r["minutes"]), float(r["points"])))
        self.games = {k: sorted(v.items()) for k, v in games.items()}
        for lst in self.hist.values():
            lst.sort()
        self.hdates = {p: np.array([d for d, _, _ in lst]) for p, lst in self.hist.items()}

    def recent_mean(self, pid: int, day: int):
        """(Anzahl, Mittel Minuten, Mittel Punkte) der letzten LOOKBACK Spiele vor day."""
        lst, ds = self.hist.get(pid, []), self.hdates.get(pid)
        if ds is None:
            return 0, 0.0, 0.0
        k = int(np.searchsorted(ds, day, side="left"))
        part = lst[max(0, k - LOOKBACK):k]
        if not part:
            return 0, 0.0, 0.0
        return len(part), float(np.mean([m for _, m, _ in part])), float(np.mean([p for _, _, p in part]))


def find_candidates(ro: Rosters) -> dict:
    """{(Saison, Team, Spiel-ID): [(Spieler-ID, erw. Minuten, erw. Punkte)]} fuer alle Teamspiele mit mindestens einem Kandidaten."""
    out = {}
    for (season, team), lst in ro.games.items():
        for i in range(1, len(lst)):
            (day, gid), roster = lst[i]
            cands = []
            for pid in lst[i - 1][1]:
                if pid in roster:
                    continue
                if not any(pid in lst[j][1] for j in range(i + 1, min(len(lst), i + 1 + RETURN_WITHIN))):
                    continue
                n, m, p = ro.recent_mean(pid, day)
                if n >= MIN_HISTORY and m > OUT_MIN:
                    cands.append((pid, m, p))
            if cands:
                out[(season, team, gid)] = cands
    return out


def team_game_rows(fc: list[dict]) -> dict:
    out = defaultdict(list)
    for r in fc:
        out[(r["season"], r["team"], r["game"])].append(r)
    return out


def group_flow(mates: list[dict], lo: float, hi: float) -> tuple:
    """(Summe Abweichung Minuten, Summe Abweichung Punkte) der Mitspieler mit lo < erwartete Minuten <= hi (Bank: lo = -1)."""
    sel = [r for r in mates if lo < r["emin"] <= hi] if hi < 1e8 or lo > 0 else [r for r in mates if r["emin"] > lo]
    return sum(r["mact"] - r["emin"] for r in sel), sum(r["act"] - r["epts"] for r in sel)


def events_and_baseline(fc: list[dict], cands: dict) -> tuple:
    """(events, baseline). event: {'season','exp_min','exp_pts','dev_min','dev_pts','roles': {Rolle: (dmin, dpts)}}; baseline: Liste (dev_min, dev_pts, roles) fuer Teamspiele ohne Kandidat. OT-Teamspiele fehlen."""
    tg = team_game_rows(fc)
    events, base, multi, no_mates = [], [], 0, 0
    for key, mates in tg.items():
        if mates[0]["ot"]:
            continue
        roles = {name: group_flow(mates, lo, hi) for name, lo, hi in ROLES}
        dmin, dpts = sum(r["mact"] - r["emin"] for r in mates), sum(r["act"] - r["epts"] for r in mates)
        c = cands.get(key)
        if c is None:
            base.append({"season": key[0], "dev_min": dmin, "dev_pts": dpts, "roles": roles})
        elif len(c) == 1:
            events.append({"season": key[0], "exp_min": c[0][1], "exp_pts": c[0][2], "dev_min": dmin, "dev_pts": dpts, "roles": roles})
        else:
            multi += 1
    return events, base, multi


# ----------------------------------------------------------------------------- Statistik und Bericht
def ms(v) -> tuple:
    a = np.asarray(v, float)
    return (len(a), float(a.mean()) if len(a) else float("nan"), float(a.std(ddof=1)) if len(a) > 1 else float("nan"))


def fmt(t) -> str:
    return f"{t[1]:+.3f} / {t[2]:.3f} (n={t[0]})" if t[0] else "-"


def build_report(events: list, base: list, multi: dict, notes: list) -> str:
    names = list(SEASONS) + ["gesamt"]
    sel = lambda lst, n: [e for e in lst if n == "gesamt" or e["season"] == n]
    out = ["Rueckfluss der Minuten und Punkte eines ausgefallenen Spielers (beschreibend, keine Bewertung)"] + [l for l in __doc__.split("WICHTIG")[1].split("Nur Team-Spiele")[0].strip().split("\n")]
    out[1] = "WICHTIG " + out[1]
    out += ["Nur Team-Spiele mit genau einem Ausfall; ohne Verlaengerung und ohne Spiel 0022400061. Abweichung = tatsaechlich minus erwartet roh, Summe ueber die Mitspieler mit Prognose.", ""]
    out.append("1. ANZAHL")
    out.append("  " + "".ljust(34) + "".join(n.rjust(10) for n in names))
    out.append("  " + "Team-Spiele mit genau 1 Ausfall".ljust(34) + "".join(str(len(sel(events, n))).rjust(10) for n in names))
    out.append("  " + "Team-Spiele mit 2 oder mehr Kandidaten".ljust(34) + "".join(str(multi.get(n, 0)).rjust(10) for n in names))
    out.append("  " + "Team-Spiele ohne Kandidat (Vergleich)".ljust(34) + "".join(str(len(sel(base, n))).rjust(10) for n in names))
    out += ["", "2. RUECKFLUSS INSGESAMT (Mittel / Streuung)", "  Rueckfluss = Summe der Mitspieler-Abweichungen / erwartete Minuten bzw. Punkte des Ausfalls; Vergleich: Summe der Abweichungen in Spielen ohne Kandidat (absolut)"]
    out.append("  " + "".ljust(44) + "".join(n.rjust(26) for n in names))
    rows = [("Ausfall erwartete Minuten (Mittel)", lambda n: f"{np.mean([e['exp_min'] for e in sel(events, n)]):.2f}" if sel(events, n) else "-"),
            ("Ausfall erwartete Punkte (Mittel)", lambda n: f"{np.mean([e['exp_pts'] for e in sel(events, n)]):.2f}" if sel(events, n) else "-"),
            ("Summe Abweichung Minuten (Ausfall)", lambda n: fmt(ms([e["dev_min"] for e in sel(events, n)]))),
            ("Summe Abweichung Minuten (ohne Ausfall)", lambda n: fmt(ms([b["dev_min"] for b in sel(base, n)]))),
            ("Summe Abweichung Punkte (Ausfall)", lambda n: fmt(ms([e["dev_pts"] for e in sel(events, n)]))),
            ("Summe Abweichung Punkte (ohne Ausfall)", lambda n: fmt(ms([b["dev_pts"] for b in sel(base, n)]))),
            ("Rueckfluss Minuten (Anteil)", lambda n: fmt(ms([e["dev_min"] / e["exp_min"] for e in sel(events, n)]))),
            ("Rueckfluss Punkte (Anteil)", lambda n: fmt(ms([e["dev_pts"] / e["exp_pts"] for e in sel(events, n) if e["exp_pts"] > 0]))),
            ("Rueckfluss Minuten abzgl. Vergleich", lambda n: f"{np.mean([e['dev_min'] for e in sel(events, n)]) / np.mean([e['exp_min'] for e in sel(events, n)]) - np.mean([b['dev_min'] for b in sel(base, n)]) / np.mean([e['exp_min'] for e in sel(events, n)]):+.3f}" if sel(events, n) and sel(base, n) else "-"),
            ("Rueckfluss Punkte abzgl. Vergleich", lambda n: f"{(np.mean([e['dev_pts'] for e in sel(events, n)]) - np.mean([b['dev_pts'] for b in sel(base, n)])) / np.mean([e['exp_pts'] for e in sel(events, n)]):+.3f}" if sel(events, n) and sel(base, n) else "-")]
    for lab, fn in rows:
        out.append("  " + lab.ljust(44) + "".join(fn(n).rjust(26) for n in names))
    out.append("  Prognose-Variante C (Neuberechnung mit Ausfaellen): nicht in den Dateien, kein Vergleich moeglich. Position der Mitspieler: lokal nicht vorhanden.")

    out += ["", "3. VERTEILUNG AUF DIE MITSPIELER NACH ROLLE (alle Saisons; Mittel der Abweichungssumme der Gruppe je Spiel: mit Ausfall / ohne Ausfall / Differenz; Anteil = Differenz / erwartete Ausfall-Minuten bzw. -Punkte)"]
    out.append("  " + "Rolle (erw. Min. roh)".ljust(24) + "Minuten: mit / ohne / Diff / Anteil".ljust(42) + "Punkte: mit / ohne / Diff / Anteil")
    em, ep = np.mean([e["exp_min"] for e in events]), np.mean([e["exp_pts"] for e in events])
    tot = [0.0, 0.0]
    for name, _, _ in ROLES:
        a = np.mean([e["roles"][name][0] for e in events]); b = np.mean([x["roles"][name][0] for x in base])
        c = np.mean([e["roles"][name][1] for e in events]); d = np.mean([x["roles"][name][1] for x in base])
        tot[0] += (a - b) / em; tot[1] += (c - d) / ep
        out.append("  " + name.ljust(24) + f"{a:+.2f} / {b:+.2f} / {a - b:+.2f} / {(a - b) / em:+.3f}".ljust(42) + f"{c:+.2f} / {d:+.2f} / {c - d:+.2f} / {(c - d) / ep:+.3f}")
    out.append("  " + "Summe der drei Rollen".ljust(24) + f"Anteil {tot[0]:+.3f}".ljust(42) + f"Anteil {tot[1]:+.3f}")

    out += ["", "4. NACH GROESSE DES AUSFALLS (erwartete Minuten des Ausfalls; alle Saisons)"]
    out.append("  " + "Groesse".ljust(18) + "Spiele".rjust(8) + "  Rueckfluss Minuten (Mittel/Streuung)".ljust(42) + "Rueckfluss Punkte (Mittel/Streuung)".ljust(40) + "abzgl. Vergleich Min. / Pkt.")
    for name, lo, hi in SIZES:
        ev = [e for e in events if lo < e["exp_min"] <= hi]
        if not ev:
            out.append("  " + name.ljust(18) + "0")
            continue
        sub = ms([e["dev_min"] / e["exp_min"] for e in ev]); sp = ms([e["dev_pts"] / e["exp_pts"] for e in ev if e["exp_pts"] > 0])
        dm = (np.mean([e["dev_min"] for e in ev]) - np.mean([b["dev_min"] for b in base])) / np.mean([e["exp_min"] for e in ev])
        dp = (np.mean([e["dev_pts"] for e in ev]) - np.mean([b["dev_pts"] for b in base])) / np.mean([e["exp_pts"] for e in ev])
        out.append("  " + name.ljust(18) + str(len(ev)).rjust(8) + ("  " + f"{sub[1]:+.3f} / {sub[2]:.3f}").ljust(42) + f"{sp[1]:+.3f} / {sp[2]:.3f}".ljust(40) + f"{dm:+.3f} / {dp:+.3f}")
        for rname, _, _ in ROLES:
            a = np.mean([e["roles"][rname][0] for e in ev]); c = np.mean([e["roles"][rname][1] for e in ev])
            b = np.mean([x["roles"][rname][0] for x in base]); d = np.mean([x["roles"][rname][1] for x in base])
            out.append("      " + rname.ljust(18) + f"Minuten-Anteil {(a - b) / np.mean([e['exp_min'] for e in ev]):+.3f}".ljust(36) + f"Punkte-Anteil {(c - d) / np.mean([e['exp_pts'] for e in ev]):+.3f}")
    out += ["", "5. NICHT GEPRUEFT"] + ["  " + n for n in notes]
    return "\n".join(out) + "\n"


def run(pbp: Path, cache: Path, seasons=SEASONS) -> str:
    local = pdc.load_local(cache)
    ro = Rosters(local)
    cands = find_candidates(ro)
    fc = [r for s in seasons for r in pdc.load_forecast_rows(pbp, s)]
    events, base, multi = events_and_baseline(fc, cands)
    multi_by = defaultdict(int)
    tg = team_game_rows(fc)
    for key, c in cands.items():
        if len(c) > 1 and key in tg and not tg[key][0]["ot"]:
            multi_by[key[0]] += 1
    multi_by["gesamt"] = sum(multi_by.values())
    notes = ["Echte Inaktiven-Listen (INACTIVE_INJURY / INACTIVE_GLEAGUE_TWOWAY) fuer 2023-24 bis 2025-26: nicht im Projekt, daher die Naeherung oben (Verletzung nicht von Ruhetag oder Trainerentscheidung getrennt).",
             "Spieler ohne Einsatz fehlen in den Prognosedateien (nur Minuten > 0): Mitspieler, die ebenfalls fehlten, und ein zweiter Ausfall im selben Spiel sind nicht erfasst; Spiele mit zwei oder mehr Kandidaten sind ausgeschlossen (Zahl oben).",
             "Spieler ohne Prognose, die trotzdem spielten, fehlen in der Summe der Mitspieler. Erwartete Minuten/Punkte des Ausfalls sind Mittel der letzten 10 Spiele, nicht die Prognose des Modells.",
             "Prognose-Variante C und Position: nicht vorhanden. Keine Signifikanztests; erstes Teamspiel einer Saison hat keinen Vorgaenger und wird nicht betrachtet; lineups_<Saison>.csv.gz wurde nicht gebraucht."]
    return build_report(events, base, multi_by, notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = run(Path(a.pbp_dir), Path(a.cache_dir))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
