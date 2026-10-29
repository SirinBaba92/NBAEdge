"""
Umverteilung bei Ausfaellen mit den ECHTEN Inaktiven-Listen (rein beschreibend, ohne Netz; keine bestehende Datei wird veraendert). Schreibt analysis/results/redistribution_real.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/redistribution_real.py

Eingabe (nur lesen): NBAEdge_pbp/derived/inactives_<Saison>.csv.gz, forecast_players_<Saison>.csv.gz (roh), Position und Startermerkmal aus NBAEdge_pbp/boxscore/<Saison>/<id>.json.gz, Spielerverlauf aus data/cache.
Ausfall: Status INACTIVE_INJURY und Mittel der letzten 10 Einsaetze (Minuten > 0) vor dem Spiel ueber 20 Minuten, mindestens 5 Einsaetze. Erwartet = dieses Mittel (Minuten, Punkte).
Gruppe A: genau ein Ausfall, kein weiterer INACTIVE_INJURY-Spieler mit Mittel ueber 12 Minuten (egal wie viele Einsaetze). B: genau zwei Ausfaelle, sonst wie A. K: kein INACTIVE_INJURY-Spieler mit Mittel ueber 12 Minuten.
Gegenprobe: INACTIVE_REST / INACTIVE_COACH (Mittel ueber 20, mindestens 5 Einsaetze): genau einer, und kein weiterer Spieler mit Status INJURY/REST/COACH und Mittel ueber 12. Vergleich gegen dieselbe Gruppe K.
Pro Team-Spiel: Summe (tatsaechlich minus erwartet roh) ueber alle Mitspieler mit Prognosezeile. Rueckfluss = (Mittel Summe in A minus Mittel Summe in K) / mittlere erwartete Minuten bzw. Punkte des Ausfalls (B: der Summe beider).
Fehlerbereich: Bootstrap ueber Spiele (beide Teams eines Spiels zusammen gezogen, A und K getrennt), 1000 Ziehungen, 2.5 % bis 97.5 %.
Ausgeschlossen: Spiel 0022400061, Verlaengerungsspiele (Teamsumme der Spielerminuten ueber 245).
"""
import argparse
import gzip
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from analysis import ppm_decomposition as pdc  # noqa: E402
from analysis.redistribution import Rosters, ROLES  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
OUT_MIN, OTHER_MIN, MIN_HISTORY = 20.0, 12.0, 5
SIZES = (("20 bis 28 Min.", 20.0, 28.0), ("ueber 28 Min.", 28.0, 1e9))
NREP, SEED = 1000, 12345
INJ, RESTCOACH = "INACTIVE_INJURY", ("INACTIVE_REST", "INACTIVE_COACH")
OUT = HERE / "results" / "redistribution_real.txt"


# ----------------------------------------------------------------------------- Einlesen
def load_inactives(pbp: Path, season: str) -> dict:
    """{(Team, Spiel-ID): [(Spieler-ID, Status, Tag)]} nur Spieler ohne Einsatz (Minuten leer oder 0)."""
    out = defaultdict(list)
    with gzip.open(pbp / "derived" / f"inactives_{season}.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if float(r["minuten"] or 0) > 0:
                    continue
                out[(r["team"], r["spiel_id"])].append((int(r["spieler_id"]), r["status"], pdc.date_int(r["datum"])))
            except ValueError:
                continue
    return out


def load_box_attrs(pbp: Path, season: str, gids) -> dict:
    """{(Spiel-ID, Spieler-ID): (Position, Starter 0/1)} aus den Rohdateien; fehlende Dateien werden uebersprungen."""
    out = {}
    for gid in gids:
        p = pbp / "boxscore" / season / f"{gid}.json.gz"
        if not p.exists():
            continue
        try:
            d = json.load(gzip.open(p, "rt", encoding="utf-8"))
        except (OSError, ValueError):
            continue
        g = d.get("game", d)
        for side in ("homeTeam", "awayTeam"):
            for pl in (g.get(side) or {}).get("players") or []:
                out[(gid, int(pl["personId"]))] = (str(pl.get("position") or "").strip(), 1 if str(pl.get("starter")) == "1" else 0)
    return out


def pos_class(pos: str) -> str:
    if not pos:
        return "keine Angabe"
    return "gemischt (z. B. G-F)" if "-" in pos else {"G": "Guard", "F": "Forward", "C": "Center"}.get(pos, pos)


# ----------------------------------------------------------------------------- Gruppen
def infos_for(ro: Rosters, inact: list) -> list:
    """[(Status, Einsaetze, Mittel Minuten, Mittel Punkte)] je Inaktivem eines Team-Spiels."""
    out = []
    for pid, status, day in inact:
        n, m, p = ro.recent_mean(pid, day)
        out.append((status, n, m, p))
    return out


def classify(infos: list) -> tuple:
    """-> (Gruppe, Liste der Ausfaelle (Minuten, Punkte)). Gruppe in 'A','B','K','R' (Gegenprobe Rest/Coach) oder None."""
    inj12 = [i for i in infos if i[0] == INJ and i[2] > OTHER_MIN]
    outs = [(i[2], i[3]) for i in inj12 if i[2] > OUT_MIN and i[1] >= MIN_HISTORY]
    if not inj12:
        return "K", []
    if len(outs) == 1 and len(inj12) == 1:
        return "A", outs
    if len(outs) == 2 and len(inj12) == 2:
        return "B", outs
    return None, []


def classify_rest(infos: list) -> tuple:
    big12 = [i for i in infos if i[0] in (INJ,) + RESTCOACH and i[2] > OTHER_MIN]
    outs = [(i[2], i[3]) for i in big12 if i[0] in RESTCOACH and i[2] > OUT_MIN and i[1] >= MIN_HISTORY]
    if len(outs) == 1 and len(big12) == 1:
        return "R", outs
    return None, []


# ----------------------------------------------------------------------------- Rechnung
def cluster_array(recs: list) -> np.ndarray:
    """Eine Zeile je Spiel: [Anzahl Team-Spiele, Summe dMin, Summe dPkt, Summe erw. Min, Summe erw. Pkt]."""
    agg = defaultdict(lambda: np.zeros(5))
    for r in recs:
        agg[r["gid"]] += np.array([1.0, r["dmin"], r["dpts"], r["emin"], r["epts"]])
    return np.array(list(agg.values())) if agg else np.zeros((0, 5))


def flows(sa: np.ndarray, sk: np.ndarray) -> tuple:
    """(Rueckfluss Minuten, Rueckfluss Punkte) aus Summen [n, dmin, dpts, emin, epts] von A und K."""
    return ((sa[1] / sa[0] - sk[1] / sk[0]) / (sa[3] / sa[0]), (sa[2] / sa[0] - sk[2] / sk[0]) / (sa[4] / sa[0]))


def estimate(a: np.ndarray, k: np.ndarray, nrep: int = NREP, seed: int = SEED) -> dict | None:
    """Punktwert und 95-%-Bereich des Rueckflusses; None wenn A oder K leer."""
    if len(a) == 0 or len(k) == 0:
        return None
    pt = flows(a.sum(0), k.sum(0))
    rng = np.random.default_rng(seed)
    ia, ik = rng.integers(0, len(a), (nrep, len(a))), rng.integers(0, len(k), (nrep, len(k)))
    sa, sk = a[ia].sum(1), k[ik].sum(1)
    fm = (sa[:, 1] / sa[:, 0] - sk[:, 1] / sk[:, 0]) / (sa[:, 3] / sa[:, 0])
    fp = (sa[:, 2] / sa[:, 0] - sk[:, 2] / sk[:, 0]) / (sa[:, 4] / sa[:, 0])
    return {"games_a": len(a), "tg_a": int(a[:, 0].sum()), "tg_k": int(k[:, 0].sum()), "min": pt[0], "pts": pt[1],
            "min_ci": tuple(np.percentile(fm, [2.5, 97.5])), "pts_ci": tuple(np.percentile(fp, [2.5, 97.5])),
            "exp_min": float(a[:, 3].sum() / a[:, 0].sum()), "exp_pts": float(a[:, 4].sum() / a[:, 0].sum()),
            "dev_a": (float(a[:, 1].sum() / a[:, 0].sum()), float(a[:, 2].sum() / a[:, 0].sum())),
            "dev_k": (float(k[:, 1].sum() / k[:, 0].sum()), float(k[:, 2].sum() / k[:, 0].sum()))}


def team_game_records(fc: list, groups: dict) -> dict:
    """{Gruppe: [Datensatz je Team-Spiel]}; Datensatz: season, gid, team, dmin, dpts, emin, epts (erwartet des Ausfalls), mates (Zeilen)."""
    tg = defaultdict(list)
    for r in fc:
        tg[(r["season"], r["team"], r["game"])].append(r)
    out = defaultdict(list)
    for key, (grp, outs) in groups.items():
        mates = tg.get(key)
        if grp is None or not mates or mates[0]["ot"]:
            continue
        out[grp].append({"season": key[0], "gid": key[2], "team": key[1], "mates": mates,
                         "dmin": sum(r["mact"] - r["emin"] for r in mates), "dpts": sum(r["act"] - r["epts"] for r in mates),
                         "emin": sum(o[0] for o in outs), "epts": sum(o[1] for o in outs), "outs": outs})
    return out


def split_by(recs: list, keyf, cats: list, attrs=None) -> dict:
    """{Kategorie: (Summe dMin je Team-Spiel, Summe dPkt je Team-Spiel, Anzahl Team-Spiele)} - Summen ueber die Mitspieler der Kategorie."""
    out = {}
    for c in cats:
        dm = dp = 0.0
        for rec in recs:
            for r in rec["mates"]:
                if keyf(r, attrs) == c:
                    dm += r["mact"] - r["emin"]
                    dp += r["act"] - r["epts"]
        out[c] = (dm / max(len(recs), 1), dp / max(len(recs), 1))
    return out


def share_table(a_recs: list, k_recs: list, keyf, cats: list, attrs=None) -> list:
    """[(Kategorie, Mittel A min, Mittel K min, Differenz min, Anteil min, dasselbe Punkte)]; Anteil = Differenz / Summe der Differenzen aller Kategorien."""
    sa, sk = split_by(a_recs, keyf, cats, attrs), split_by(k_recs, keyf, cats, attrs)
    diffs = {c: (sa[c][0] - sk[c][0], sa[c][1] - sk[c][1]) for c in cats}
    tm, tp = sum(d[0] for d in diffs.values()), sum(d[1] for d in diffs.values())
    return [(c, sa[c][0], sk[c][0], diffs[c][0], diffs[c][0] / tm if tm else float("nan"),
             sa[c][1], sk[c][1], diffs[c][1], diffs[c][1] / tp if tp else float("nan")) for c in cats]


def role_of(r, _a=None) -> str:
    return next(name for name, lo, hi in ROLES if (r["emin"] > lo and r["emin"] <= hi))


def pos_of(r, attrs):
    return pos_class((attrs.get((r["game"], r["pid"])) or ("", 0))[0]) if attrs else "keine Angabe"


def starter_of(r, attrs):
    a = attrs.get((r["game"], r["pid"])) if attrs else None
    return "ohne Angabe" if a is None else ("Starter im Spiel" if a[1] else "von der Bank")


# ----------------------------------------------------------------------------- Bericht
def f1(x) -> str:
    return f"{x:+.2f}"


def line(label: str, e: dict | None) -> str:
    if e is None:
        return f"  {label}: keine Daten"
    return (f"  {label}: A {e['games_a']} Spiele / {e['tg_a']} Team-Spiele, K {e['tg_k']}; Ausfall erw. {e['exp_min']:.1f} Min / {e['exp_pts']:.1f} Pkt; Summe Abweichung A {f1(e['dev_a'][0])} Min / {f1(e['dev_a'][1])} Pkt, K {f1(e['dev_k'][0])} / {f1(e['dev_k'][1])}; "
            f"Rueckfluss Minuten {e['min']:.2f} [{e['min_ci'][0]:.2f}; {e['min_ci'][1]:.2f}], Punkte {e['pts']:.2f} [{e['pts_ci'][0]:.2f}; {e['pts_ci'][1]:.2f}]")


def pct(x) -> str:
    return "n/a" if x != x else f"{100 * x:.0f} %"


def table_lines(title: str, rows: list) -> list:
    out = [title, "  Kategorie | Mittel A Min | Mittel K Min | Diff Min | Anteil Min | Mittel A Pkt | Mittel K Pkt | Diff Pkt | Anteil Pkt"]
    for c, am, km, dm, sm, ap, kp, dp, sp in rows:
        out.append(f"  {c} | {f1(am)} | {f1(km)} | {f1(dm)} | {pct(sm)} | {f1(ap)} | {f1(kp)} | {f1(dp)} | {pct(sp)}")
    return out


def build_report(by: dict, attrs: dict, notes: list, seasons=SEASONS) -> str:
    """by: {Gruppe: [Datensaetze]} (A, B, K, R). Reine Zahlen."""
    L = ["Umverteilung bei Ausfaellen mit echten Inaktiven-Listen (nur Zahlen)",
         "Rueckfluss = (Mittel Summe Abweichung Mitspieler in A minus in K) / erwartete Minuten bzw. Punkte des Ausfalls. Klammer: 95-%-Bereich (Bootstrap ueber Spiele, 1000 Ziehungen).", ""]
    for g, name, head in (("A", "A: genau ein Ausfall", "1. Ein Ausfall (Gruppe A)"), ("B", "B: genau zwei Ausfaelle (geteilt durch die Summe beider)", "2. Zwei Ausfaelle (Gruppe B)"),
                          ("R", "Gegenprobe INACTIVE_REST/COACH, genau einer", "6. Gegenprobe Rest/Coach")):
        L.append(head + " - " + name)
        for s in list(seasons) + ["gesamt"]:
            sel = lambda recs: [r for r in recs if s == "gesamt" or r["season"] == s]
            L.append(line(s, estimate(cluster_array(sel(by.get(g, []))), cluster_array(sel(by.get("K", []))))))
        L.append("")
    a, k = by.get("A", []), by.get("K", [])
    L += table_lines("4a. Verteilung auf Mitspieler in A nach Rolle (erwartete Minuten roh; Summen je Team-Spiel)", share_table(a, k, role_of, [n for n, _, _ in ROLES]))
    if attrs:
        L.append("")
        L += table_lines("4b. nach Position im Spiel (Boxscore, Angabe nach dem Spiel)", share_table(a, k, pos_of, sorted({pos_of(r, attrs) for rec in a + k for r in rec["mates"]}), attrs))
        L.append("")
        L += table_lines("4c. nach Startermerkmal im Spiel (Boxscore, Angabe nach dem Spiel)", share_table(a, k, starter_of, ["Starter im Spiel", "von der Bank", "ohne Angabe"], attrs))
    L += ["", "5. Ausfall nach Groesse in A (erwartete Minuten des Ausfalls)"]
    for name, lo, hi in SIZES:
        sub = [r for r in a if lo < r["emin"] <= hi]
        L.append(line(name + " gesamt", estimate(cluster_array(sub), cluster_array(k))))
        for s in seasons:
            L.append(line(f"  {name} {s}", estimate(cluster_array([r for r in sub if r["season"] == s]), cluster_array([r for r in k if r["season"] == s]))))
    L += ["", "7. Variante C des Modells: " + notes[0], "", "Hinweise (was nicht erfasst ist):"] + [" - " + n for n in notes[1:]]
    return "\n".join(L) + "\n"


def run(pbp: Path, cache: Path, seasons=SEASONS) -> str:
    ro = Rosters(pdc.load_local(cache))
    fc, groups_all, rest_groups, counts = [], {}, {}, defaultdict(int)
    for s in seasons:
        fc += pdc.load_forecast_rows(pbp, s)
        for (team, gid), inact in load_inactives(pbp, s).items():
            infos = infos_for(ro, inact)
            groups_all[(s, team, gid)] = classify(infos)
            rest_groups[(s, team, gid)] = classify_rest(infos)
    # Team-Spiele ohne eigene Inaktiven-Zeile fehlen nie (Tabelle enthaelt alle Kaderspieler); trotzdem: Team-Spiele der Prognose ohne Eintrag zaehlen zu K
    for r in fc:
        groups_all.setdefault((r["season"], r["team"], r["game"]), ("K", []))
    by = team_game_records(fc, groups_all)
    by["R"] = team_game_records(fc, {k: v for k, v in rest_groups.items() if v[0] == "R"}).get("R", [])
    gids = {s: {r["gid"] for g in ("A", "K") for r in by.get(g, []) if r["season"] == s} for s in seasons}
    attrs = {}
    for s in seasons:
        attrs.update(load_box_attrs(pbp, s, gids[s]))
    notes = ["nicht aufgerufen. Sie braucht den Schnappschuss des Spielmodells (Spread, Total, Teampunkte) aus data/tracking und die Betano-Eintraege des Spiels (context_for_game, game_player_odds); beides gibt es nur fuer aufgezeichnete Spiele, nicht fuer 2023-24 bis 2025-26.",
             "Mitspieler ohne Prognosezeile (z. B. kein Verlauf, nicht in der Prognosedatei) fehlen in der Summe; Einsatz mit Minuten 0 ist nicht vorhanden (Rueckfluss nur bei Einsatz).",
             "Weitere Inaktive mit kleiner Rolle (Mittel bis 12 Min.) und Inaktive anderer Status (z. B. GLEAGUE_TWOWAY, DND, REST) sind in A, B und K erlaubt und nicht herausgerechnet.",
             "Erwartete Minuten und Punkte des Ausfalls sind Mittel der letzten 10 Einsaetze (Spielerverlauf aus data/cache, ueber Saisongrenzen), nicht die Prognose des Modells; Ausfaelle ohne 5 Einsaetze zaehlen nicht als Ausfall, schliessen A aber aus.",
             "Position und Startermerkmal stammen aus dem Boxscore des Spiels (nach dem Spiel bekannt) und nur fuer Spiele der Gruppen A und K. Der Boxscore nennt die Position nur bei Startern: 'keine Angabe' in 4b sind dieselben Spieler wie 'von der Bank' in 4c.",
             "Die Summe der Abweichungen in K ist nicht 0 (Mitspieler mit Prognose spielen im Mittel weniger als roh erwartet, u. a. weil Spieler ohne Prognosezeile Minuten bekommen); deshalb wird A gegen K verglichen.",
             "Keine Signifikanztests ueber den Bootstrap-Bereich hinaus; Rest/Coach-Gegenprobe wird mit derselben Gruppe K verglichen."]
    return build_report(by, attrs, notes, seasons)


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
