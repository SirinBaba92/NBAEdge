"""Tests fuer eingabe.py (Terminal-Eingabe fuer Pre-Match-Linien und Quoten) mit simulierter Eingabe (stdin-Mock) und die Erhoehung des Spread-Limits im Tab.
Offline (tests/fake_net.py, Temp-Verzeichnisse); Pickle, echte pre_match_entries.json und echte rosters.json werden nur gelesen (SHA vor/nach).
Aufruf aus dem Projektordner: venv/bin/python tests/test_eingabe.py"""
import copy, datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.rosters as ro
import data.market_lines as ml
import engine.line_probabilities as lp
import ui.pre_match_tab as pmt
import eingabe as ei
from roster_fixture import fake_index
from models.elo import MODEL_PATH

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
real = {n: sha(ROOT / "data" / n) for n in ("elo_model.pkl", "rosters.json", "tracking/pre_match_entries.json")}
real_calls = state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
K, P = "New York Knicks", "Philadelphia 76ers"          # Heim, Gast
HN, AN = "Knicks", "76ers"
NOW = time.time()
START = iso(NOW + 6 * H)
G = {"home": K, "away": P, "date": "2026-10-21", "start": START}
KEY = ps.game_key(G["date"], G["start"], K, P)


def setup():
    tmp = fresh_env()
    ro.write(ro.build(fake_index(), "2026-10-21T04:00:00+02:00", "2026-27"))
    return tmp


class Script:
    """Simulierte Eingabe: Liste von (erwarteter Text in der Frage, Antwort); die Reihenfolge der Fragen wird dabei mitgeprueft.
    hooks: {Index: Funktion}, wird VOR der Antwort mit diesem Index ausgefuehrt (z. B. paralleles Speichern im Tab)."""
    def __init__(self, steps, hooks=None):
        self.steps, self.i, self.log, self.hooks = list(steps), 0, [], hooks or {}

    def read(self, prompt):
        self.log.append(prompt)
        if self.i >= len(self.steps):
            raise AssertionError(f"Unerwartete Frage nach dem Ende des Skripts: {prompt!r}")
        want, ans = self.steps[self.i]
        if want not in prompt:
            raise AssertionError(f"Schritt {self.i}: erwartet {want!r}, gestellt {prompt!r}")
        if self.i in self.hooks:
            self.hooks[self.i]()
        self.i += 1
        return ans


def run(steps, hooks=None, games=None, now=None):
    sc, out = Script(steps, hooks), []
    con = ei.Console(read=sc.read, write=out.append)
    rc = ei.main(con, now_fn=lambda: now or NOW, games=games if games is not None else [bdl_game()])
    return sc, out, rc


def bdl_game(home=K, away=P, start=START, date="2026-10-21", status="scheduled"):
    return {"home_team": {"full_name": home}, "visitor_team": {"full_name": away}, "date": date, "datetime": start, "status": status}


def entry():
    return (ps.load().get("entries") or {}).get(KEY)


def lines_of(e, market):
    return {l["id"]: l for l in (e["markets"][market]["lines"])}


# ===== Erstes Spiel: komplette Eingabe, Reihenfolge Heim vor Gast
setup()
steps = [("Nummer wählen", "1"),
         ("Quote Knicks", "1,55"), ("Quote 76ers", "2.50"),
         ("Spread-Linie Knicks", "-4,5"), ("Quote Knicks -4.5", "1,91"), ("Quote 76ers +4.5", "1.89"),
         ("Weitere Spread-Linie Knicks (2 von max. 5)", "-5.5"), ("Quote Knicks -5.5", "2.10"), ("Quote 76ers +5.5", "1.70"),
         ("Weitere Spread-Linie Knicks (3 von max. 5)", ""),
         ("Total-Linie", "238,5"), ("Quote Over 238.5", "1.90"), ("Quote Under 238.5", "1.92"),
         ("Quote Over 235.5", "1.40"), ("Quote Under 235.5", "2.90"),
         ("Quote Over 236.5", "1.50"), ("Quote Under 236.5", "2.50"),
         ("Quote Over 237.5", "1.70"), ("Quote Under 237.5", "2.10"),
         ("Quote Over 239.5", "2.05"), ("Quote Under 239.5", "1.75"),
         ("Quote Over 240.5", "2.30"), ("Quote Under 240.5", "1.60"),
         ("Quote Over 241.5", ""),                                                  # Linie uebersprungen (kein Under)
         ("Team-Total-Linie Knicks", "119,5"), ("Quote Over Knicks 119.5", "1.88"), ("Quote Under Knicks 119.5", "1.92"),
         ("Weitere Team-Total-Linie Knicks vorhanden?", "j"), ("Weitere Team-Total-Linie Knicks", "121.5"), ("Quote Over Knicks 121.5", "2.20"), ("Quote Under Knicks 121.5", "1.62"),
         ("Weitere Team-Total-Linie Knicks vorhanden?", ""),
         ("Team-Total-Linie 76ers", "115,5"), ("Quote Over 76ers 115.5", "1.90"), ("Quote Under 76ers 115.5", "1.90"),
         ("Weitere Team-Total-Linie 76ers vorhanden?", ""),
         ("Anzahl Knicks-Spieler [Enter = 0]", "1"), ("Knicks-Spieler 1 von 1: Name", "brunson"), ("Start-Linie Jalen Brunson", "18"), ("End-Linie Jalen Brunson", "20"),
         ("Quote Jalen Brunson 18+", "1,20"), ("Quote Jalen Brunson 19+", "1.45"), ("Quote Jalen Brunson 20+", ""),
         ("Anzahl 76ers-Spieler [Enter = 0]", "2"), ("76ers-Spieler 1 von 2: Name", "jokic"), ("Start-Linie Nikola Jokić", ""),            # Spieler uebersprungen
         ("76ers-Spieler 2 von 2: Name", "MAXEY"), ("Start-Linie Tyrese Maxey", "22"), ("End-Linie Tyrese Maxey", "22"), ("Quote Tyrese Maxey 22+", "1.8"),
         ("Speichern?", ""),
         ("Nummer wählen", "q")]
sc, out, rc = run(steps)
e = entry()
check("1) Durchlauf endet sauber (q), alle Fragen in der erwarteten Reihenfolge beantwortet", rc == 0 and sc.i == len(steps) and out[-1].startswith("Beendet"))
w = e["markets"]["winner_incl_ot"]
check("Sieger: Heim-Quote zuerst gespeichert (home_odds 1,55 / away_odds 2,5), Buchmacher Betano", (w["home_odds"], w["away_odds"], w["bookmaker"]) == (1.55, 2.5, "Betano") and w["revisions"])
sp = lines_of(e, "spread")
check("Spread: Hauptlinie Heim -4,5 (Gast +4,5) mit Quoten Heim 1,91 / Gast 1,89; weitere Linie x1 -5,5", sp["main"]["line_home"] == -4.5 and sp["main"]["line_away"] == 4.5 and sp["main"]["home_odds"] == 1.91 and sp["main"]["away_odds"] == 1.89
      and sp["x1"]["line_home"] == -5.5 and sp["x1"]["home_odds"] == 2.1 and sp["x1"]["away_odds"] == 1.7 and sp["main"]["role"] == "main")
tt = lines_of(e, "total")
check("Total: Hauptlinie 238,5 plus Leiter 235,5/236,5/237,5 (niedriger) und 239,5/240,5 (hoeher); 241,5 uebersprungen (6 Linien)",
      sorted(l["line"] for l in tt.values()) == [235.5, 236.5, 237.5, 238.5, 239.5, 240.5] and tt["main"]["over_odds"] == 1.9
      and {l["line"]: l["direction"] for l in tt.values() if l["id"] != "main"} == {235.5: "lower", 236.5: "lower", 237.5: "lower", 239.5: "higher", 240.5: "higher"})
check("Total-Leiter: Fragen aufsteigend nach Linie, jeweils erst Over, dann Under", [p for p in sc.log if p.startswith("Quote Over 23") or p.startswith("Quote Under 23")][:2] == ["Quote Over 238.5: ", "Quote Under 238.5: "])
tm = ps.team_total_lines(e, "home"), ps.team_total_lines(e, "away")
check("Team Totals: Heim 119,5 + weitere 121,5 (Schleife), Gast 115,5; keine automatische Leiter", [l["line"] for l in tm[0]] == [119.5, 121.5] and [l["line"] for l in tm[1]] == [115.5]
      and tm[0][0]["over_odds"] == 1.88 and tm[0][1]["direction"] == "higher" and e["markets"]["team_totals"]["home"]["team"] == K and e["markets"]["team_totals"]["away"]["team"] == P)
blocks = {b["name"]: b for b in ps.active_player_blocks(e)}
b = blocks["Jalen Brunson"]
check("Spieler: Brunson 18+ und 19+ (20+ ohne Quote uebersprungen) im Modus Meilensteine, Team = Heim; Jokic uebersprungen; Maxey 22+ (Gast)",
      set(blocks) == {"Jalen Brunson", "Tyrese Maxey"} and b["mode"] == "milestones" and sorted((l["threshold"], l["odds"]) for l in ps.player_lines(b)) == [(18, 1.2), (19, 1.45)]
      and b["team"] == K and blocks["Tyrese Maxey"]["team"] == P and [(l["threshold"], l["odds"]) for l in ps.player_lines(blocks["Tyrese Maxey"])] == [(22, 1.8)])
check("Reihenfolge: Spieler Heim-Team vor Gast-Team; Sieger/Spread/Total/Team Total vor den Spielern",
      sc.log.index("Anzahl Knicks-Spieler [Enter = 0]: ") < sc.log.index("Anzahl 76ers-Spieler [Enter = 0]: ") and sc.log.index("Quote Knicks: ") < sc.log.index("Spread-Linie Knicks: ") < sc.log.index("Total-Linie: ") < sc.log.index("Team-Total-Linie Knicks: ") < sc.log.index("Team-Total-Linie 76ers: "))
check("Eintrag hat Revisionen, updated_at und die Datei ist valides JSON mit Version 5; Tageskopie angelegt",
      e["markets"]["spread"]["updated_at"] and sp["main"]["revisions"][0]["action"] == "saved" and json.loads(ps.store_path().read_text())["version"] == ps.STORE_VERSION and any(ps.history_dir().glob("pre_match_entries*")))

# ===== Gleiche Werte wie bei Tab-Eingabe (Spread-Vorzeichen), und Aufloesung in market_lines / Score Projections
tab_dir = fresh_env()
store_e = ps.save_card(G["date"], START, K, P, winner={"home_odds": "1,55", "away_odds": "2,50", "bookmaker": "Betano"},
                       spread_rows=[{"id": "main", "line": "-4,5", "home_odds": "1,91", "away_odds": "1,89", "bookmaker": "Betano"}], now=NOW)["entry"]
tab_spread = copy.deepcopy(lines_of(store_e, "spread")["main"])
setup()
run([("Nummer wählen", "1"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2.50"), ("Spread-Linie Knicks", "-4,5"), ("Quote Knicks -4.5", "1,91"), ("Quote 76ers +4.5", "1,89"),
     ("Weitere Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""),
     ("Speichern?", ""), ("Nummer wählen", "q")])
my = lines_of(entry(), "spread")["main"]
strip = lambda d: {k: v for k, v in d.items() if k not in ("entered_at", "updated_at", "revisions")}
check("Spread-Hauptlinie ist feldgleich zur Tab-Eingabe (Heim -4,5): line_home, line_away, Quoten, Buchmacher, role, id", strip(my) == strip(tab_spread), f"{strip(my)} vs {strip(tab_spread)}")
res_script = ml.resolve_market_lines(entry(), None, None, None, K, P)
res_tab = ml.resolve_market_lines(store_e, None, None, None, K, P)
check("market_lines loest die Skript-Eingabe wie die Tab-Eingabe auf: eigene Eingabe, Spread = +4,5 (Heim Favorit), Buchmacher Betano",
      res_script["spread"]["line"] == res_tab["spread"]["line"] == 4.5 and res_script["spread"]["source"] == "eigene Eingabe" and res_script["spread"]["bookmaker"] == "Betano")
proj = {"exp_spread": 5.0, "exp_total": 230.0, "home_score": 117.5, "away_score": 112.5, "market_lines": res_script}
proj_t = {**proj, "market_lines": res_tab}
check("Score Projections (build_line_tables): Skript- und Tab-Eingabe ergeben identische Spread-Tabelle (Favorit Heim)",
      lp.build_line_tables(proj, entry())["spread"] == lp.build_line_tables(proj_t, store_e)["spread"] and lp.build_line_tables(proj, entry())["spread"]["favorite"] == "home")

# ===== Gast-Eingabe: 'g +4,5' = Heim -4,5; Gast-Favorit: Heim-Linie +3
setup()
run([("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", "g +4,5"), ("Quote Knicks -4.5", "1.9"), ("Quote 76ers +4.5", "1.9"),
     ("Weitere Spread-Linie Knicks (2 von max. 5)", "76ers -6"), ("Quote Knicks +6", "1.8"), ("Quote 76ers -6", "2.0"), ("Weitere Spread-Linie Knicks (3 von max. 5)", ""),
     ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")])
sp = lines_of(entry(), "spread")
check("Gast-Linie 'g +4,5' wird zu Heim -4,5 umgerechnet; '76ers -6' (Gast Favorit) wird zu Heim +6", sp["main"]["line_home"] == -4.5 and sp["x1"]["line_home"] == 6.0 and sp["x1"]["line_away"] == -6.0 and sp["x1"]["home_odds"] == 1.8)
check("Winner uebersprungen (Enter ohne Vorgabe): kein Sieger-Markt gespeichert", "winner_incl_ot" not in entry()["markets"])

# ===== Spread-Schleife bis 5 Linien
setup()
steps = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", "-1")]
steps += [("Quote Knicks -1", "1.9"), ("Quote 76ers +1", "1.9")]
for n, ln in enumerate(["-2", "-3", "-4", "-5"], start=2):
    steps += [(f"Weitere Spread-Linie Knicks ({n} von max. 5)", ln), (f"Quote Knicks {ln}", "1.9"), (f"Quote 76ers +{ln[1:]}", "1.9")]
steps += [("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(steps)
check("Spread-Schleife: nach 5 Linien (Hauptlinie + 4) keine sechste Frage; alle 5 gespeichert", sc.i == len(steps) and len(ps.active_spread_lines(entry())) == 5 and not any("6 von" in p for p in sc.log))
check("Konstante: Spread-Limit im Store 4 weitere (5 Linien), im Tab ebenfalls (MAX_EXTRA_LINES == 4)", ps.MAX_SPREAD_EXTRA == 4 and pmt.MAX_EXTRA_LINES == 4)

# ===== Tab-Limit: Leiter in Score Projections (5/7/7) hat keine Luecke zum Tab
check("Leiter vs. Tab: Spread 5 = 1 + MAX_SPREAD_EXTRA; Total 7 = 1 + 2 * MAX_TOTAL_PER_DIRECTION; Team Total (je Team) ebenfalls 7",
      1 + ps.MAX_SPREAD_EXTRA == 2 * lp.STAFFEL_SPREAD_HALF + 1 and 1 + 2 * ps.MAX_TOTAL_PER_DIRECTION == 2 * lp.STAFFEL_TOTAL_HALF + 1 and pmt.MAX_TOTAL_DIR == ps.MAX_TOTAL_PER_DIRECTION)
setup()
rows = [{"id": "main", "line": "-1", "home_odds": "1.9", "away_odds": "1.9"}] + [{"id": None, "line": f"-{k}", "home_odds": "1.9", "away_odds": "1.9"} for k in range(2, 6)]
res = ps.save_card(G["date"], START, K, P, spread_rows=rows, now=NOW)
check("Store speichert 5 Spread-Linien (Hauptlinie + 4) in EINEM Vorgang", res["status"] == "saved" and len(ps.active_spread_lines(res["entry"])) == 5)
setup()
rows7 = [{"id": "main", "line": "238,5", "over_odds": "1.9", "under_odds": "1.9"}] + \
        [{"id": None, "direction": "higher", "line": str(238.5 + k), "over_odds": "1.9", "under_odds": "1.9"} for k in (1, 2, 3)] + \
        [{"id": None, "direction": "lower", "line": str(238.5 - k), "over_odds": "1.9", "under_odds": "1.9"} for k in (1, 2, 3)]
res = ps.save_card(G["date"], START, K, P, total_rows=rows7, team_rows={"home": [{**r, "line": str(float(r["line"].replace(",", ".")) - 119.0)} for r in rows7], "away": None}, now=NOW)
check("Store speichert 7 Total-Linien und 7 Team-Total-Linien (Heim) - keine Luecke zur Leiter", len(ps.active_total_lines(res["entry"])) == 7 and len(ps.team_total_lines(res["entry"], "home")) == 7)
# AppTest: der Tab zeigt den Knopf "Weitere Linie hinzufügen" jetzt bis zu 4 weiteren Linien aktiv
src = (ROOT / "ui" / "pre_match_tab.py").read_text()
check("Tab-Quelltext: Limit kommt aus dem Store (kein festes '3' mehr), Hinweis 'maximal N weitere Linien' bleibt dynamisch", "MAX_EXTRA_LINES = store.MAX_SPREAD_EXTRA" in src and 'f"maximal {MAX_EXTRA_LINES} weitere Linien"' in src)

# ===== Vorhandene Werte als Vorgabe: Enter behaelt, nichts wird neu geschrieben
setup()
base_steps = [("Nummer wählen", "1"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2.50"), ("Spread-Linie Knicks", "-4,5"), ("Quote Knicks -4.5", "1.91"), ("Quote 76ers +4.5", "1.89"),
              ("Weitere Spread-Linie Knicks (2 von max. 5)", "-5.5"), ("Quote Knicks -5.5", "2.1"), ("Quote 76ers +5.5", "1.7"), ("Weitere Spread-Linie Knicks (3 von max. 5)", ""),
              ("Total-Linie", "238.5"), ("Quote Over 238.5", "1.9"), ("Quote Under 238.5", "1.9")] + \
             [(f"Quote {w} {x}", "1.9") for x in (235.5, 236.5, 237.5, 239.5, 240.5, 241.5) for w in ("Over", "Under")] + \
             [("Team-Total-Linie Knicks", "119.5"), ("Quote Over Knicks", "1.9"), ("Quote Under Knicks", "1.9"), ("vorhanden?", ""), ("Team-Total-Linie 76ers", ""),
              ("Anzahl Knicks-Spieler", "1"), ("Knicks-Spieler 1 von 1: Name", "brunson"), ("Start-Linie", "18"), ("End-Linie", "19"), ("Quote Jalen Brunson 18+", "1.2"), ("Quote Jalen Brunson 19+", "1.4"),
              ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
run(base_steps)
bytes1 = ps.store_path().read_bytes()
e1 = copy.deepcopy(entry())
# zweiter Lauf: nur Enter (Vorgaben in eckigen Klammern); Spieler wird ueber Anzahl 1 + Name erneut gewaehlt
enter_steps = [("Nummer wählen", "1"), ("Quote Knicks [1.55]", ""), ("Quote 76ers [2.50]", ""), ("Spread-Linie Knicks [-4.5]", ""), ("Quote Knicks -4.5 [1.91]", ""), ("Quote 76ers +4.5 [1.89]", ""),
               ("Weitere Spread-Linie Knicks (2 von max. 5) [-5.5]", ""), ("Quote Knicks -5.5 [2.10]", ""), ("Quote 76ers +5.5 [1.70]", ""), ("Weitere Spread-Linie Knicks (3 von max. 5)", ""),
               ("Total-Linie [238.5]", ""), ("Quote Over 238.5 [1.90]", ""), ("Quote Under 238.5 [1.90]", "")] + \
              [(f"Quote {w} {x} [1.90]", "") for x in (235.5, 236.5, 237.5, 239.5, 240.5, 241.5) for w in ("Over", "Under")] + \
              [("Team-Total-Linie Knicks [119.5]", ""), ("Quote Over Knicks 119.5 [1.90]", ""), ("Quote Under Knicks 119.5 [1.90]", ""), ("vorhanden?", ""), ("Team-Total-Linie 76ers", ""),
               ("Anzahl Knicks-Spieler", "1"), ("Name", "brunson"), ("Start-Linie Jalen Brunson [18]", ""), ("End-Linie Jalen Brunson [19]", ""), ("Quote Jalen Brunson 18+ [1.20]", ""), ("Quote Jalen Brunson 19+ [1.40]", ""),
               ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(enter_steps)
check("Enter behaelt die Vorgaben (in eckigen Klammern angezeigt): 'Nichts geändert', Datei byte-identisch, keine neuen Revisionen", "Nichts geändert." in out and ps.store_path().read_bytes() == bytes1 and entry() == e1)

# ===== Aendern einer Quote erzeugt genau eine neue Revision, der Rest bleibt
setup(); run(base_steps)
s2 = copy.deepcopy(enter_steps); s2[4] = ("Quote Knicks -4.5 [1.91]", "1,95")
run(s2)
e2 = entry(); m = lines_of(e2, "spread")["main"]
check("Aenderung einer Quote: Hauptlinie bekommt Revision 2 (1,95), andere Linien/Maerkte behalten ihre Revisionen",
      m["home_odds"] == 1.95 and len(m["revisions"]) == 2 and len(lines_of(e2, "spread")["x1"]["revisions"]) == 1 and len(e2["markets"]["winner_incl_ot"]["revisions"]) == 1)

# ===== Entfernen mit x
setup(); run(base_steps)
s3 = copy.deepcopy(enter_steps)
s3[6] = ("Weitere Spread-Linie Knicks (2 von max. 5) [-5.5]", "x")           # weitere Spread-Linie entfernen
del s3[7:9]                                                                    # keine Quoten mehr dafuer
s3[7] = ("Weitere Spread-Linie Knicks (2 von max. 5)", "")                       # nach dem Entfernen ist wieder Platz 2 frei
i = next(k for k, (w, _a) in enumerate(s3) if w.startswith("Quote Over 235.5")); s3[i] = (s3[i][0], "x")   # Total-Leiterlinie 235.5 entfernen (Under wird nicht mehr gefragt)
del s3[i + 1]
i = next(k for k, (w, _a) in enumerate(s3) if w.startswith("Start-Linie")); s3[i] = (s3[i][0], "x")        # ganzen Spieler entfernen
del s3[i + 1: i + 4]
sc, out, rc = run(s3)
e3 = entry()
check("x entfernt: weitere Spread-Linie, Total-Leiterlinie und Spieler sind inaktiv (Revision 'removed', nichts geloescht)",
      not lines_of(e3, "spread")["x1"]["active"] and lines_of(e3, "spread")["x1"]["revisions"][-1]["action"] == "removed"
      and 235.5 not in [l["line"] for l in ps.active_total_lines(e3)] and not ps.active_player_blocks(e3) and len(ps.active_total_lines(e3)) == 6, str(sc.log[-4:]))
check("Die uebrigen Linien bleiben aktiv: Hauptlinie Spread/Total, Team Total", ps.active_spread_lines(e3)[0]["id"] == "main" and ps.team_total_lines(e3, "home")[0]["line"] == 119.5)
# Hauptlinie kann nicht mit x entfernt werden
setup()
sc, out, rc = run([("Nummer wählen", "1"), ("Quote Knicks", "1.5"), ("Quote 76ers", "2.5"), ("Spread-Linie Knicks", "x"), ("Spread-Linie Knicks", "q")])
check("x bei der Hauptlinie: Hinweis, dieselbe Frage wird wiederholt (kein Entfernen)", any("nichts zu entfernen" in o for o in out) and sc.log[-2:] == ["Spread-Linie Knicks: ", "Spread-Linie Knicks: "] and entry() is None)

# ===== Zurueck (z)
setup()
steps = [("Nummer wählen", "1"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2,50"), ("Spread-Linie Knicks", "z"),              # zurueck zur Quote 76ers
         ("Quote 76ers", "2,60"), ("Spread-Linie Knicks", "-3"), ("Quote Knicks -3", "1.9"), ("Quote 76ers +3", "z"),            # zurueck zur Quote Knicks -3
         ("Quote 76ers +3", "1.95"), ("Quote 76ers +3", "")]                                                                  # Test fehlerhaft unten
# Skript fuer 'z' praezise: nach z auf der Frage "Quote 76ers +3" wird die vorherige Frage "Quote Knicks -3" erneut gestellt
steps = [("Nummer wählen", "1"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2,50"), ("Spread-Linie Knicks", "z"),
         ("Quote 76ers", "2,60"), ("Spread-Linie Knicks", "-3"), ("Quote Knicks -3", "1.9"), ("Quote 76ers +3", "z"),
         ("Quote Knicks -3", "1.88"), ("Quote 76ers +3", "1.95"), ("Weitere Spread-Linie", ""),
         ("Total-Linie", "z"), ("Weitere Spread-Linie", "z"), ("Quote 76ers +3", "1.97"), ("Weitere Spread-Linie", ""), ("Total-Linie", ""),
         ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""),
         ("Speichern?", "z"), ("Anzahl 76ers-Spieler", ""), ("Speichern?", "")] + [("Nummer wählen", "q")]
sc, out, rc = run(steps)
e = entry()
check("z geht einen Schritt zurueck (auch ueber mehrere Fragen und aus der Zusammenfassung); korrigierte Werte werden gespeichert",
      sc.i == len(steps) and e["markets"]["winner_incl_ot"]["away_odds"] == 2.6 and lines_of(e, "spread")["main"]["home_odds"] == 1.88 and lines_of(e, "spread")["main"]["away_odds"] == 1.97, f"{sc.i}/{len(steps)} {sc.log[-3:]}")
setup()
sc, out, rc = run([("Nummer wählen", "1"), ("Quote Knicks", "z"), ("Quote Knicks", "q")])
check("z bei der ersten Frage: Hinweis, Frage wird wiederholt", any("erste Frage" in o for o in out) and sc.log[-1] == "Quote Knicks: ")

# ===== Ungueltige Eingaben: Erklaerung und dieselbe Frage
setup()
bad = [("Nummer wählen", "x"), ("Nummer wählen", "9"), ("Nummer wählen", "1"),
       ("Quote Knicks", "abc"), ("Quote Knicks", "1,005"), ("Quote Knicks", "1,00"), ("Quote Knicks", "1,0"), ("Quote Knicks", "1,2,3"), ("Quote Knicks", "1.01"),
       ("Quote 76ers", ""), ("Quote 76ers", "2,2"),
       ("Spread-Linie Knicks", "-4,3"), ("Spread-Linie Knicks", "viel"), ("Spread-Linie Knicks", "-4.5"),
       ("Quote Knicks -4.5", "1.9"), ("Quote 76ers +4.5", "1.9"),
       ("Weitere Spread-Linie Knicks (2 von max. 5)", "-4,5"), ("Weitere Spread-Linie Knicks (2 von max. 5)", ""),
       ("Total-Linie", "238,3"), ("Total-Linie", "5"), ("Total-Linie", "238,5"), ("Quote Over 238.5", "0.9"), ("Quote Over 238.5", "1.9"), ("Quote Under 238.5", "1.9")] + \
      [("Quote Over", "") for _ in range(6)] + \
      [("Team-Total-Linie Knicks", "119.5"), ("Quote Over Knicks", "1.9"), ("Quote Under Knicks", "1.9"), ("vorhanden?", "vielleicht"), ("vorhanden?", "j"),
       ("Weitere Team-Total-Linie Knicks", "119.5"), ("Weitere Team-Total-Linie Knicks", "119"), ("Quote Over Knicks 119", "1.5"), ("Quote Under Knicks 119", "2.5"), ("vorhanden?", ""),
       ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", "21"), ("Anzahl Knicks-Spieler", "x1"), ("Anzahl Knicks-Spieler", "1"),
       ("Name", "zzzz"), ("Name", ""), ("Name", "brunson"), ("Start-Linie Jalen Brunson", "0"), ("Start-Linie Jalen Brunson", "18"), ("End-Linie Jalen Brunson", "17"), ("End-Linie Jalen Brunson", "40"),
       ("End-Linie Jalen Brunson", "18"), ("Quote Jalen Brunson 18+", "1"), ("Quote Jalen Brunson 18+", "1.3"), ("Anzahl 76ers-Spieler", ""), ("Speichern?", "ja bitte"), ("Speichern?", "n"), ("Nummer wählen", "q")]
sc, out, rc = run(bad)
msgs = "\n".join(out)
check("Ungueltige Eingaben (Buchstaben, Quote <= 1,00, doppelter Trenner, Viertellinie, unrealistische Linie, doppelte Linie, falsche Nummer ...): Erklaerung + gleiche Frage",
      sc.i == len(bad) and "mindestens 1,01" in msgs and "Bitte eine Zahl" in msgs and "Nur ganze und halbe Linien" in msgs and "schon erfasst" in msgs and "Bitte j (ja)" in msgs and "Kein Spieler" in msgs
      and "End-Linie darf nicht unter" in msgs and "Höchstens 10" in msgs and "Bitte eine Nummer von 1 bis" in msgs, f"{sc.i}/{len(bad)}")
check("Verworfen (n): nichts gespeichert", "Verworfen." in out and entry() is None)

# ===== Spielerabgleich: eindeutig, mehrdeutig, keiner, nur Kader der beiden Teams
setup()
steps = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""),
         ("Anzahl Knicks-Spieler", "2"),
         ("Knicks-Spieler 1 von 2: Name", "Spieler"), ("Nummer", "99"), ("Nummer", "2"), ("Start-Linie", ""),             # mehrdeutig: Auswahl aus Liste
         ("Knicks-Spieler 2 von 2: Name", "Embiid"), ("Knicks-Spieler 2 von 2: Name", "KARL anthony"),                    # Embiid ist 76ers: kein Treffer im Knicks-Kader
         ("Start-Linie Karl-Anthony Towns", ""),
         ("Anzahl 76ers-Spieler", "1"), ("76ers-Spieler 1 von 1: Name", "jokic"), ("Start-Linie Nikola Jokić", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(steps)
txt = "\n".join(out)
check("Spielerabgleich: Teilname/Gross-Klein/Akzent (jokic -> Nikola Jokić) eindeutig; 'Spieler' mehrdeutig -> nummerierte Auswahl; Spieler des anderen Teams: Fehler und Wiederholung",
      sc.i == len(steps) and "Mehrere Treffer" in txt and "1) Spieler0 NYK0" in txt and "Kein Spieler „Embiid“" in txt and "Bitte eine Nummer von 1 bis 12" in txt, f"{sc.i}/{len(steps)} {[k for k in ('Mehrere Treffer','1) Spieler0 NYK0','Kein Spieler „Embiid“','Bitte eine Nummer von 1 bis 12') if k not in txt]}")
check("Es werden keine freien Namen gespeichert (alles uebersprungen -> nichts geschrieben)", entry() is None)

# ===== Spieler-Leiter: Start/End, Zwischenlinien im Schritt 1, ohne Anzahl-Frage
setup()
steps = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""),
         ("Anzahl Knicks-Spieler", "1"), ("Name", "towns"), ("Start-Linie Karl-Anthony Towns", "18"), ("End-Linie Karl-Anthony Towns", "25")] + \
        [(f"Quote Karl-Anthony Towns {t}+", f"{1.1 + (t - 18) * 0.2:.2f}") for t in range(18, 26)] + [("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(steps)
bl = ps.active_player_blocks(entry())[0]
check("Spieler 18 bis 25: 8 Linien (18+ ... 25+) nur mit Quotenfragen, keine Anzahl-Frage; Speicherform wie im Tab (threshold, odds, mode milestones)",
      sc.i == len(steps) and [l["threshold"] for l in ps.player_lines(bl)] == list(range(18, 26)) and all("odds" in l and "threshold" in l for l in ps.player_lines(bl)) and bl["mode"] == "milestones"
      and not any("Anzahl Linien" in p for p in sc.log) and ps.player_lines(bl)[0]["odds"] == 1.1)
tab_player = ps.save_card(G["date"], START, "A", "B", player_blocks=[{"block_id": None, "person_id": 1, "name": "X", "team": "A", "team_abbreviation": "A", "mode": "milestones",
                                                                    "rows": [{"id": None, "value": "18", "odds": "1.1", "bookmaker": "Betano"}]}], now=NOW)["entry"]
tl = ps.player_lines(ps.active_player_blocks(tab_player)[0])[0]
check("Meilenstein-Zeile ist feldgleich zur Tab-Eingabe (gleiche Schluessel)", set(tl) == set(ps.player_lines(bl)[0]))

# ===== Limit 20 Spieler je Spiel: 15 und 20 werden gespeichert, 21 abgelehnt (Anzahl-Frage und Store); Aufteilung auf beide Teams wird beachtet
setup()
rost = ro.load()["teams"]
def roster_players(team, n):
    return [q["name"] for q in rost[team] if q["name"].startswith("Spieler")][:n]
def many_steps(nh, na):
    st = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", str(nh))]
    for i, nm in enumerate(roster_players(K, nh), 1):
        st += [(f"Knicks-Spieler {i} von {nh}: Name", nm), (f"Start-Linie {nm}", "10"), (f"End-Linie {nm}", "10"), (f"Quote {nm} 10+", "1.5")]
    st += [("Anzahl 76ers-Spieler", str(na))]
    for i, nm in enumerate(roster_players(P, na), 1):
        st += [(f"76ers-Spieler {i} von {na}: Name", nm), (f"Start-Linie {nm}", "10"), (f"End-Linie {nm}", "10"), (f"Quote {nm} 10+", "1.5")]
    return st + [("Speichern?", ""), ("Nummer wählen", "q")]
st15 = many_steps(7, 8)
sc, out, rc = run(st15)
check("15 Spieler (7 Heim, 8 Gast) werden gespeichert (frueher: 'höchstens 10 Spieler je Spiel')", sc.i == len(st15) and len(ps.active_player_blocks(entry())) == 15 and "Gespeichert." in out and not any("höchstens" in o for o in out))
setup()
sc, out, rc = run(many_steps(10, 10))
check("20 Spieler (10 Heim, 10 Gast) werden gespeichert, je Spieler eine Linie", len(ps.active_player_blocks(entry())) == 20 and "Gespeichert." in out)
setup()
sc, out, rc = run([("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""),
                   ("Anzahl Knicks-Spieler", "21"), ("Anzahl Knicks-Spieler", "12"), ("Name", "q")])
check("Anzahl 21: abgelehnt mit Hinweis 'höchstens 20 Spieler je Spiel', Frage wird wiederholt", any("von 0 bis 20" in o and "höchstens 20" in o for o in out))
setup()
steps = many_steps(12, 0)[:7 + 12 * 4] + [("Anzahl 76ers-Spieler", "9"), ("Anzahl 76ers-Spieler", "q")]
sc, out, rc = run(steps)
check("Nach 12 Heim-Spielern sind fuer das Gast-Team nur noch 8 Plaetze: Anzahl 9 wird abgelehnt ('von 0 bis 8')", any("von 0 bis 8" in o for o in out))
setup()
blocks21 = [{"block_id": None, "person_id": 5000 + i, "name": f"Test {i}", "team": K, "team_abbreviation": "NYK", "mode": "milestones", "rows": [{"id": None, "value": "10", "odds": "1,5", "bookmaker": "Betano"}]} for i in range(21)]
try:
    ps.save_card(G["date"], START, K, P, player_blocks=blocks21, now=NOW); raised = ""
except ps.CardInputError as e:
    raised = str(e)
check("Store: 21 Spielerbloecke werden abgelehnt ('höchstens 20 Spieler je Spiel'), 20 gehen", "höchstens 20 Spieler je Spiel" in raised and ps.save_card(G["date"], START, K, P, player_blocks=blocks21[:20], now=NOW)["status"] == "saved")

# ===== Parallel: Tab aendert waehrend der Eingabe, nichts geht verloren
setup()
tab_save = lambda: ps.save_card(G["date"], START, K, P, spread_rows=[{"id": "main", "line": "-2", "home_odds": "1.5", "away_odds": "2.6", "bookmaker": "Pinnacle"}],
                                total_rows=[{"id": "main", "line": "230,5", "over_odds": "1.8", "under_odds": "2.0", "bookmaker": "Pinnacle"}], now=NOW)
steps = [("Nummer wählen", "1"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2.50"), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", "119.5"),
         ("Quote Over", "1.9"), ("Quote Under", "1.9"), ("vorhanden?", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(steps, hooks={12: tab_save})            # Tab speichert Spread + Total, BEVOR das Skript speichert
e = entry()
check("Paralleles Speichern im Tab: Skript ueberschreibt nichts (Spread -2 und Total 230,5 aus dem Tab bleiben), seine eigenen Aenderungen (Sieger, Team Total) kommen dazu",
      lines_of(e, "spread")["main"]["line_home"] == -2.0 and lines_of(e, "total")["main"]["line"] == 230.5 and e["markets"]["winner_incl_ot"]["home_odds"] == 1.55
      and ps.team_total_lines(e, "home")[0]["line"] == 119.5 and len(lines_of(e, "spread")["main"]["revisions"]) == 1)
# Tab aendert eine Linie, die das Skript behalten hat (Enter); Skript aendert andere Quote: Hauptlinie bleibt wie im Tab
setup(); run(base_steps)
tab_change = lambda: ps.save_card(G["date"], START, K, P, spread_rows=[{"id": "main", "line": "-3,5", "home_odds": "1.8", "away_odds": "2.0", "bookmaker": "Betano"}], now=NOW)
s4 = copy.deepcopy(enter_steps)
j = next(k for k, (w, _a) in enumerate(s4) if w.startswith("Weitere Spread-Linie Knicks (2 von")); k2 = next(k for k, (w, _a) in enumerate(s4) if w.startswith("Quote Knicks -5.5"))
s4[k2] = (s4[k2][0], "2,15")                                                      # Skript aendert nur die Quote der weiteren Linie
isave = next(k for k, (w, _a) in enumerate(s4) if w.startswith("Speichern?"))
run(s4, hooks={isave: tab_change})
e = entry(); spm = lines_of(e, "spread")
check("Tab aendert die Hauptlinie, das Skript nur die weitere Linie (Hauptlinie war nur 'behalten'): Tab-Wert bleibt, Skript-Aenderung kommt an",
      spm["main"]["line_home"] == -3.5 and spm["main"]["home_odds"] == 1.8 and spm["x1"]["home_odds"] == 2.15, str((spm["main"]["line_home"], spm["x1"]["home_odds"])))

# ===== Spieleauswahl: Berliner Uhrzeit, nur nicht begonnene Spiele, a = alle der Reihe nach
setup()
g_started = bdl_game("Boston Celtics", "Detroit Pistons", iso(NOW - 1 * H))
g_final = bdl_game("Miami Heat", "Chicago Bulls", iso(NOW + 2 * H), status="Final")
g_late = bdl_game("San Antonio Spurs", "Oklahoma City Thunder", iso(NOW + 9 * H))
allg = [g_started, g_final, bdl_game(), g_late]
sc, out, rc = run([("Nummer wählen", "x"), ("Nummer wählen", "q")], games=allg)
listing = "\n".join(o for o in out if o.startswith("  ") and ")" in o)
berlin = lambda s: dt.datetime.fromtimestamp(ps.parse_utc(s), ei.BERLIN).strftime("%H:%M")
check("Auswahl: nur nicht begonnene Spiele, nummeriert, nach Anpfiff sortiert, mit Uhrzeit (Berlin); begonnen/beendet nicht angeboten",
      "1)" in listing and "2)" in listing and "3)" not in listing and "Celtics" not in listing and "Heat" not in listing and "Knicks – 76ers" in listing and "Spurs – Thunder" in listing and berlin(START) in listing)
setup()
sc, out, rc = run([("Nummer wählen", "a"),
                   ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""),
                   ("Quote Spurs", "q")], games=allg)
check("a = alle der Reihe nach (Knicks – 76ers zuerst, dann Spurs – Thunder); q mitten im Spiel beendet sauber", sc.i == 10 and rc == 0 and out[-1].startswith("Beendet") and "=== New York Knicks – Philadelphia 76ers" in "\n".join(out) and "=== San Antonio Spurs – Oklahoma City Thunder" in "\n".join(out))
# q mitten im Spiel: bestaetigte Spiele bleiben gespeichert, das laufende wird nicht geschrieben
setup()
sc, out, rc = run([("Nummer wählen", "a"),
                   ("Quote Knicks", "1,5"), ("Quote 76ers", "2,6"), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""),
                   ("Quote Spurs", "1,4"), ("Quote Thunder", "q")], games=allg)
check("q mitten im zweiten Spiel: erstes Spiel gespeichert, zweites nicht",
      entry() is not None and ps.get_entry(ps.game_key("2026-10-21", iso(NOW + 9 * H), "San Antonio Spurs", "Oklahoma City Thunder")) is None)

# ===== Sperre ab Anpfiff und Speicherfehler
# Spiel beginnt waehrend der Eingabe: execute_plan bekommt eine Zeit nach dem Anpfiff
setup()
calls = iter([NOW, NOW])
late = lambda: next(calls, NOW + 7 * H)
sc2, out2 = Script([("Nummer wählen", "1"), ("Quote Knicks", "1,5"), ("Quote 76ers", "2,6"), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""),
                    ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Speichern?", "n"), ("Nummer wählen", "q")]), []
ei.main(ei.Console(read=sc2.read, write=out2.append), now_fn=late, games=[bdl_game()])
out = out2
check("Spiel beginnt waehrend der Eingabe: Speichern wird abgelehnt (Meldung), nichts geschrieben, danach verwerfen moeglich", any("bereits begonnen" in o for o in out) and entry() is None)

# ===== Linie weicht stark vom Marktwert im Speicher ab: nur warnen (Zusammenfassung), trotzdem speichern; Marktvorschlag aus dem Speicher wird festgehalten
tmp = setup()
(tmp / "pregame_lines.json").write_text(json.dumps({"ev1": {"home_team": K, "away_team": P, "commence": ps.parse_utc(START), "fetched_at": NOW - 600,
                                                          "lines": {"spread": 4.5, "total": 230.0, "team_totals": {}}}}))
steps = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", "-12,5"), ("Quote Knicks -12.5", "1.9"), ("Quote 76ers +12.5", "1.9"), ("Weitere Spread-Linie", ""),
         ("Total-Linie", "250,5"), ("Quote Over 250.5", "1.9"), ("Quote Under 250.5", "1.9")] + [("Quote Over", "") for _ in range(6)] + \
        [("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(steps)
e = entry(); txt = "\n".join(out)
check("Abweichung vom Marktwert (Spread 8 > Grenze 4, Total 20,5 > 8): Hinweis in der Zusammenfassung, aber gespeichert (nicht blockiert)",
      "Hinweis: Spread Knicks -12.5 weicht um 8 " in txt and "Hinweis: Total 250.5 weicht um 20.5" in txt and lines_of(e, "spread")["main"]["line_home"] == -12.5 and lines_of(e, "total")["main"]["line"] == 250.5, txt[-700:])
check("Marktvorschlag aus dem Speicher (Quelle cache_vorab) wird bei der Hauptlinie festgehalten wie im Tab", lines_of(e, "spread")["main"]["market_suggestion"]["line_home"] == -4.5 and lines_of(e, "total")["main"]["market_suggestion"]["line"] == 230.0)

# ===== Hauptlinie des Totals verschoben: alte Zusatzlinien, die nicht mehr zur Leiter passen, koennen entfernt werden
setup(); run(base_steps)
shift = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Quote Knicks", ""), ("Quote 76ers", ""), ("Weitere Spread-Linie", ""), ("Weitere Spread-Linie", ""),
         ("Total-Linie [238.5]", "240.5"), ("Quote Over 240.5 [1.90]", ""), ("Quote Under 240.5 [1.90]", "")] + \
        [(f"Quote {w} {x}", "1.8") for x in (237.5, 238.5, 239.5, 241.5, 242.5, 243.5) for w in ("Over", "Under")]
shift = [("Nummer wählen", "1"), ("Quote Knicks [1.55]", ""), ("Quote 76ers [2.50]", ""), ("Spread-Linie Knicks [-4.5]", ""), ("Quote Knicks -4.5", ""), ("Quote 76ers +4.5", ""),
         ("Weitere Spread-Linie Knicks (2 von max. 5) [-5.5]", ""), ("Quote Knicks -5.5", ""), ("Quote 76ers +5.5", ""), ("Weitere Spread-Linie Knicks (3 von", ""),
         ("Total-Linie [238.5]", "240.5"), ("Quote Over 240.5 [1.90]", ""), ("Quote Under 240.5 [1.90]", "")] + \
        [(f"Quote {w} {x}", "1.8") for x in (237.5, 238.5, 239.5, 241.5, 242.5, 243.5) for w in ("Over", "Under")] + \
        [("Gespeicherte Total-Linien 235.5, 236.5 passen nicht zur neuen Leiter. Entfernen? (Enter = entfernen", ""),
         ("Team-Total-Linie Knicks", ""), ("Quote Over", ""), ("Quote Under", ""), ("vorhanden?", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""),
         ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(shift)
act = {l["line"]: l for l in ps.active_total_lines(entry())}
check("Verschobene Hauptlinie (238,5 -> 240,5): nicht passende alte Linien werden nach Rueckfrage entfernt, neue Leiter 237,5 bis 243,5 gespeichert (inaktive Linien bleiben mit Revision)",
      sorted(act) == [237.5, 238.5, 239.5, 240.5, 241.5, 242.5, 243.5] and act[240.5]["id"] == "main" and act[238.5]["direction"] == "lower" and act[239.5]["direction"] == "lower" and act[241.5]["direction"] == "higher"
      and sum(1 for l in entry()["markets"]["total"]["lines"] if not l["active"]) >= 3, f"{sc.i}/{len(shift)} {sorted(act)} {sc.log[-2:]}")

# ===== Schritt 12: 's' am "Speichern?"-Prompt springt zu einem Bereich; danach direkt zurueck zur Zusammenfassung
def ou(line, o="1.9", u="1.9", rid=None, direction=None):
    return {"id": rid, "direction": direction, "line": str(line), "over_odds": o, "under_odds": u, "bookmaker": "Betano"}


FIRST = [("Quote Knicks", "1.5"), ("Quote 76ers", "2.6"),
         ("Spread-Linie Knicks", "-4.5"), ("Quote Knicks -4.5", "1.9"), ("Quote 76ers +4.5", "1.9"), ("Weitere Spread-Linie Knicks (2 von", ""),
         ("Total-Linie", "238.5"), ("Quote Over 238.5", "1.9"), ("Quote Under 238.5", "1.9")] + [("Quote Over", "") for _ in range(6)] + \
        [("Team-Total-Linie Knicks", "119.5"), ("Quote Over Knicks 119.5", "1.9"), ("Quote Under Knicks 119.5", "1.9"), ("vorhanden?", ""),
         ("Team-Total-Linie 76ers", "115.5"), ("Quote Over 76ers 115.5", "1.9"), ("Quote Under 76ers 115.5", "1.9"), ("vorhanden?", ""),
         ("Anzahl Knicks-Spieler", "1"), ("Knicks-Spieler 1 von 1: Name", "brunson"), ("Start-Linie Jalen Brunson", "18"), ("End-Linie Jalen Brunson", "18"), ("Quote Jalen Brunson 18+", "1.2"),
         ("Anzahl 76ers-Spieler", "0")]
JUMPS = {   # Menuenummer: (Antworten im Bereich, erwartete Werte danach)
    1: ([("Quote Knicks", "1.7"), ("Quote 76ers", "2.3")], {"winner": 1.7}),
    2: ([("Spread-Linie Knicks", "-6.5"), ("Quote Knicks -6.5", "1.8"), ("Quote 76ers +6.5", "2.0"), ("Weitere Spread-Linie Knicks (2 von", "")], {"spread": -6.5}),
    3: ([("Total-Linie", "240"), ("Quote Over 240", "1.8"), ("Quote Under 240", "2.0")] + [("Quote Over", "") for _ in range(6)], {"total": 240.0}),
    4: ([("Team-Total-Linie Knicks", "121.5"), ("Quote Over Knicks 121.5", "1.8"), ("Quote Under Knicks 121.5", "2.0"), ("vorhanden?", "")], {"tt_home": 121.5}),
    5: ([("Team-Total-Linie 76ers", "113.5"), ("Quote Over 76ers 113.5", "1.8"), ("Quote Under 76ers 113.5", "2.0"), ("vorhanden?", "")], {"tt_away": 113.5}),
    6: ([("Anzahl Knicks-Spieler", "1"), ("Knicks-Spieler 1 von 1: Name", "brunson"), ("Start-Linie Jalen Brunson", "20"), ("End-Linie Jalen Brunson", "20"), ("Quote Jalen Brunson 20+", "1.6")], {"brunson": [20]}),
    7: ([("Anzahl 76ers-Spieler", "1"), ("76ers-Spieler 1 von 1: Name", "maxey"), ("Start-Linie Tyrese Maxey", "22"), ("End-Linie Tyrese Maxey", "22"), ("Quote Tyrese Maxey 22+", "1.8")],
        {"maxey": [22]}),
}
MENU_ASK = "Enter = abbrechen"


def snapshot(e):
    pl = {b["name"].split()[-1].lower(): sorted(l["threshold"] for l in ps.player_lines(b)) for b in ps.active_player_blocks(e)}
    return {"winner": e["markets"]["winner_incl_ot"]["home_odds"], "spread": ps.active_spread_lines(e)[0]["line_home"], "total": ps.active_total_lines(e)[0]["line"],
            "tt_home": ps.team_total_lines(e, "home")[0]["line"], "tt_away": ps.team_total_lines(e, "away")[0]["line"], **pl}


base_vals = {"winner": 1.5, "spread": -4.5, "total": 238.5, "tt_home": 119.5, "tt_away": 115.5, "brunson": [18]}
for num, (answers, change) in JUMPS.items():
    setup()
    st = [("Nummer wählen", "1")] + FIRST + [("Speichern?", "s"), (MENU_ASK, str(num))] + answers + [("Speichern?", ""), ("Nummer wählen", "q")]
    sc, out, rc = run(st)
    txt = "\n".join(out)
    exp = {**base_vals, **change}
    got = snapshot(entry()) if entry() else None
    if num == 6:
        exp["brunson"] = [20]
    check(f"s -> {num}) {dict(ei.section_menu(G))[ei.SECTIONS[num - 1]]}: nur dieser Bereich neu gefragt, danach direkt Zusammenfassung (keine weiteren Bereiche), andere Antworten erhalten, gespeichert",
          rc == 0 and sc.i == len(st) and got == exp, f"{sc.i}/{len(st)} {got} != {exp} {sc.log[-3:]}")
check("Menue zeigt alle 7 Bereiche nummeriert (Sieger, Spread, Total, Team Total Heim/Gast, Spieler Heim/Gast)",
      all(x in txt for x in ("  1) Sieger", "  2) Spread", "  3) Total", "  4) Team Total Knicks", "  5) Team Total 76ers", "  6) Spieler Knicks", "  7) Spieler 76ers")) and "s = zu einem Bereich springen" in "\n".join(sc.log), txt[-600:])
# Abbruch: Enter im Menue; z am Anfang des Sprung-Bereichs; q im Menue
setup()
st = [("Nummer wählen", "1")] + FIRST + [("Speichern?", "s"), (MENU_ASK, ""), ("Speichern?", "s"), (MENU_ASK, "3"), ("Total-Linie", "z"), ("Speichern?", "n"), ("Nummer wählen", "q")]
sc, out, rc = run(st)
txt = "\n".join(out)
check("Menue mit Enter abbrechen: zurueck zum Speichern-Prompt; z am Anfang des Sprung-Bereichs bricht den Sprung ab, die alten Antworten bleiben (Total 238.5 in der Zusammenfassung)",
      sc.i == len(st) and "Sprung abgebrochen" in txt and txt.count("238.5: Over 1.90 | Under 1.90  [Hauptlinie]") == 2 and entry() is None, f"{sc.i}/{len(st)} {txt[-500:]}")
setup()
st = [("Nummer wählen", "1")] + FIRST + [("Speichern?", "s"), (MENU_ASK, "9"), (MENU_ASK, "q")]
sc, out, rc = run(st)
check("Ungueltige Menuenummer wird abgelehnt und neu gefragt, q beendet ohne Speichern", sc.i == len(st) and any("Bitte eine Nummer von 1 bis 7" in o for o in out) and entry() is None)
# Zwei Spruenge hintereinander, danach z am Speichern-Prompt (Schritt zurueck) funktioniert weiter
setup()
st = [("Nummer wählen", "1")] + FIRST + [("Speichern?", "s"), (MENU_ASK, "1"), ("Quote Knicks", "1.6"), ("Quote 76ers", "2.5"),
                                          ("Speichern?", "s"), (MENU_ASK, "7")] + JUMPS[7][0] + [("Speichern?", "z"), ("Quote Tyrese Maxey 22+", "1.7"),
                                                                                                    ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(st)
got = snapshot(entry()) if entry() else None
check("Zwei Spruenge nacheinander (Sieger, dann Spieler Gast) und danach z am Speichern-Prompt: alles erhalten, letzte Antwort (Quote) neu",
      sc.i == len(st) and got is not None and got["winner"] == 1.6 and got["maxey"] == [22] and [l["odds"] for b in ps.active_player_blocks(entry()) if b["name"].endswith("Maxey") for l in ps.player_lines(b)] == [1.7] and got["total"] == 238.5 and got["brunson"] == [18], f"{sc.i}/{len(st)} {got}")

# ===== Total-Duplikat: Zusatzlinien auf Leiter-Linien werden ueberschrieben, die auf der neuen Hauptlinie ersetzt; nur wirklich nicht passende loesen die Rueckfrage aus
def dup_state():
    setup()
    ps.save_card(G["date"], START, K, P, total_rows=[ou(243.5, rid="main"), ou(240.5, rid=None, direction="lower"), ou(241.5, rid=None, direction="lower"),
                                                     ou(244.5, rid=None, direction="higher"), ou(245.5, rid=None, direction="higher")], now=NOW)
dup_state()
saved_before = {l["line"]: l["id"] for l in ps.active_total_lines(entry())}
dup_steps = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie [243.5]", "241.5"), ("Quote Over 241.5 [1.90]", ""), ("Quote Under 241.5 [1.90]", ""),
             ("Quote Over 238.5", ""), ("Quote Over 239.5", ""), ("Quote Over 240.5 [1.90]", ""), ("Quote Under 240.5", ""), ("Quote Over 242.5", ""), ("Quote Over 243.5", ""),
             ("Quote Over 244.5 [1.90]", ""), ("Quote Under 244.5", ""),
             ("Gespeicherte Total-Linien 245.5 passen nicht zur neuen Leiter. Entfernen? (Enter = entfernen, n = behalten)", ""),
             ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(dup_steps)
txt = "\n".join(out)
al = ps.active_total_lines(entry())
check("Duplikat-Fall 240.5/241.5: Zusatzlinie 240.5 (Leiter) ueberschrieben, Zusatzlinie 241.5 von der neuen Hauptlinie ersetzt, nur 245.5 loest die Rueckfrage aus (Enter = entfernen) -> gespeichert ohne Duplikat",
      sc.i == len(dup_steps) and "Gespeichert." in txt and sorted(l["line"] for l in al) == [240.5, 241.5, 244.5] and len({l["line"] for l in al}) == len(al)
      and next(l for l in al if l["line"] == 240.5)["id"] == saved_before[240.5] and next(l for l in al if l["line"] == 241.5)["id"] == "main", f"{sc.i}/{len(dup_steps)} {[(l['line'], l['id']) for l in al]} {txt[-400:]}")
inactive = {l["line"] for l in entry()["markets"]["total"]["lines"] if not l["active"]}
check("Entfernte Linien bleiben mit Revision 'removed' erhalten (nichts geloescht): 245.5 und die alte Zusatzlinie 241.5",
      inactive == {245.5, 241.5} and all(l["revisions"][-1]["action"] == "removed" for l in entry()["markets"]["total"]["lines"] if not l["active"]))
check("Zusammenfassung nennt die ersetzte Zeile (ENTFERNEN: Total 241.5 ... ersetzt) und die zu entfernende 245.5", "ENTFERNEN: Total 241.5  (wird durch die neue Zeile ersetzt)" in txt and "ENTFERNEN: Total 245.5" in txt)
# Vorgabe n = behalten
dup_state()
st2 = [(w, "n" if w.startswith("Gespeicherte Total-Linien") else a) for w, a in dup_steps]
sc, out, rc = run(st2)
check("Rueckfrage mit n = behalten: 245.5 bleibt aktiv, gespeichert", sc.i == len(st2) and 245.5 in {l["line"] for l in ps.active_total_lines(entry())})
# Richtung aendert sich mit der Hauptlinie (240.5 war 'higher', ist jetzt 'lower'): neu angelegt, alte ersetzt
setup()
ps.save_card(G["date"], START, K, P, total_rows=[ou(238.5, rid="main"), ou(240.5, rid=None, direction="higher")], now=NOW)
st3 = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie [238.5]", "242.5"), ("Quote Over 242.5 [1.90]", ""), ("Quote Under 242.5 [1.90]", ""),
       ("Quote Over 239.5", ""), ("Quote Over 240.5 [1.90]", ""), ("Quote Under 240.5", ""), ("Quote Over 241.5", ""), ("Quote Over 243.5", ""), ("Quote Over 244.5", ""), ("Quote Over 245.5", ""),
       ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""), ("Anzahl Knicks-Spieler", ""), ("Anzahl 76ers-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(st3)
al = {l["line"]: l for l in ps.active_total_lines(entry())}
check("Gespeicherte Linie auf der Leiter mit neuer Richtung: einmal vorhanden (neu angelegt, jetzt 'lower'), keine Duplikat-Fehlermeldung",
      sc.i == len(st3) and sorted(al) == [240.5, 242.5] and al[240.5]["direction"] == "lower" and not any("mehrfach" in o for o in out), f"{sc.i}/{len(st3)} {sorted(al)} {out[-4:]}")

# ===== Alte Zusatzlinien werden erst beim erfolgreichen Speichern entfernt (Fund aus Schritt 11)
dup_state()
calls = iter([NOW, NOW])
late = lambda: next(calls, NOW + 7 * H)
sc3, out3 = Script(dup_steps[:-1] + [("Speichern?", "n"), ("Nummer wählen", "q")]), []
ei.main(ei.Console(read=sc3.read, write=out3.append), now_fn=late, games=[bdl_game()])
check("Speichern abgelehnt (Anpfiff vorbei): die Rueckfrage mit Enter = entfernen hat noch NICHTS entfernt (245.5 und 241.5-Zusatzlinie weiter aktiv)",
      any("bereits begonnen" in o for o in out3) and sorted(l["line"] for l in ps.active_total_lines(entry())) == [240.5, 241.5, 243.5, 244.5, 245.5]
      and sum(1 for l in entry()["markets"]["total"]["lines"] if not l["active"]) == 0, str(sorted(l["line"] for l in ps.active_total_lines(entry()))))
# Pruefung vor dem Entfernen: ein Plan, den der Store ablehnt, entfernt nichts (Direktaufruf von execute_plan)
dup_state()
e0 = entry()
plan = {"winner": None, "spread": [], "total": [{"id": "main", "line": 241.5, "over_odds": 1.9, "under_odds": 1.9, "direction": None},
                                              {"id": None, "line": 240.5, "over_odds": 1.8, "under_odds": 2.0, "direction": "lower"}],   # 240.5 existiert schon (x1): Duplikat
        "team": {"home": [], "away": []}, "players": [], "remove": [("total", next(l["id"] for l in ps.active_total_lines(e0) if l["line"] == 245.5))], "replaced": set(), "warnings": []}
try:
    ei.execute_plan(G, plan, e0, ro.load(), {}, now=NOW)
    err = None
except ps.CardInputError as ex:
    err = ex
check("execute_plan: Store lehnt das Duplikat 240.5 ab -> geplante Entfernung (245.5) wurde NICHT ausgefuehrt",
      err is not None and "mehrfach" in str(err) and 245.5 in {l["line"] for l in ps.active_total_lines(entry())}, str(err))

# ===== Fehlermeldungen nennen s mit der passenden Menuenummer
plan0 = {"players": [{"name": "Jalen Brunson", "team": K}, {"name": "Tyrese Maxey", "team": P}]}
check("Hinweis fuer Total-Duplikat: 'tippe s und wähle 3 für Total'", ei.section_hint("Total: Die Linie 240,5 kommt mehrfach vor (jede Linie nur einmal pro Spiel und Markt).", G, plan0) == "  → Tippe s und wähle 3 für Total.")
check("Hinweis Spielerpunkte: Limit -> 6 oder 7; Meldung mit Spielername -> Menuenummer seines Teams (Maxey = 7)",
      "wähle 6 oder 7 für Spieler Knicks / Spieler 76ers" in ei.section_hint("Spielerpunkte: höchstens 20 Spieler je Spiel.", G, plan0)
      and ei.section_hint("Spielerpunkte · Tyrese Maxey: Schwelle +22 kommt mehrfach vor", G, plan0) == "  → Tippe s und wähle 7 für Spieler 76ers."
      and "wähle 4 für Team Total Knicks" in ei.section_hint("Team Totals · Knicks: Die Linie 120 kommt mehrfach vor", G, plan0)
      and "wähle 2 für Spread" in ei.section_hint("Spread · Weitere Linie 1: x", G, plan0) and ei.section_hint("Nichts eingetragen.", G, plan0) == "")
setup()
orig = ei.execute_plan
def boom(*a, **k):
    raise ps.CardInputError(["Total: Die Linie 240,5 kommt mehrfach vor (jede Linie nur einmal pro Spiel und Markt)."])
ei.execute_plan = boom
try:
    sc, out, rc = run([("Nummer wählen", "1")] + FIRST + [("Speichern?", ""), ("Speichern?", "n"), ("Nummer wählen", "q")])
finally:
    ei.execute_plan = orig
check("Abgelehntes Speichern im Ablauf: Fehlermeldung enthaelt den Hinweis 'Tippe s und wähle 3 für Total.'", any("kommt mehrfach vor" in o and "Tippe s und wähle 3 für Total." in o for o in out))

# ===== Warnung, wenn Spieler-Quoten mit der Schwelle nicht steigen (nur Hinweis, wird trotzdem gespeichert)
setup()
st = [("Nummer wählen", "1"), ("Quote Knicks", ""), ("Spread-Linie Knicks", ""), ("Total-Linie", ""), ("Team-Total-Linie Knicks", ""), ("Team-Total-Linie 76ers", ""),
      ("Anzahl Knicks-Spieler", "1"), ("Knicks-Spieler 1 von 1: Name", "brunson"), ("Start-Linie Jalen Brunson", "22"), ("End-Linie Jalen Brunson", "25"),
      ("Quote Jalen Brunson 22+", "1.55"), ("Quote Jalen Brunson 23+", "1.44"), ("Quote Jalen Brunson 24+", "1.80"), ("Quote Jalen Brunson 25+", "1.67"),
      ("Anzahl 76ers-Spieler", "1"), ("76ers-Spieler 1 von 1: Name", "maxey"), ("Start-Linie Tyrese Maxey", "20"), ("End-Linie Tyrese Maxey", "22"),
      ("Quote Tyrese Maxey 20+", "1.5"), ("Quote Tyrese Maxey 21+", "1.7"), ("Quote Tyrese Maxey 22+", "2.0"),
      ("Speichern?", ""), ("Nummer wählen", "q")]
sc, out, rc = run(st)
txt = "\n".join(out)
check("Spieler-Quoten, die nicht steigen (Brunson 23+ @ 1.44 nach 22+ @ 1.55, 25+ @ 1.67 nach 24+ @ 1.80): Hinweis mit Spielername und 2 Stellen; Maxey (steigend) ohne Hinweis; trotzdem gespeichert",
      "Hinweis: Jalen Brunson: Quoten steigen nicht mit der Schwelle (23+ @ 1.44 nicht höher als 22+ @ 1.55; 25+ @ 1.67 nicht höher als 24+ @ 1.80; 2 Stelle(n))" in txt and "Hinweis: Tyrese Maxey" not in txt
      and "Gespeichert." in txt and len(ps.active_player_blocks(entry())) == 2, txt[-500:])

# ===== Echter Start als Prozess (stdin-Pipe) in Temp-Ordnern: keine Spiele im Zwischenspeicher
import subprocess
tmp = setup()
env = {**os.environ, "NBAEDGE_TRACKING_DIR": str(tmp / "tracking")}
r = subprocess.run([sys.executable, str(ROOT / "eingabe.py")], input="q\n", capture_output=True, text=True, env=env, timeout=60, cwd=ROOT)
check("Start als Skript (python eingabe.py) ohne Spieleliste: Hinweis statt Absturz, Rueckgabewert 0", r.returncode == 0 and "Keine Spiele" in r.stdout, (r.stdout + r.stderr)[-200:])
upc = json.loads(json.dumps({"fetched_at": NOW, "params": {}, "games": [bdl_game()]}))
(tmp / "upcoming_cache.json").write_text(json.dumps(upc))
r = subprocess.run([sys.executable, str(ROOT / "eingabe.py")], input="1\n1,6\n2,4\n\n\n\n\n\n\n\n\nq\n", capture_output=True, text=True, env=env, timeout=60, cwd=ROOT)
check("Start als Skript mit Spieleliste aus dem Zwischenspeicher und stdin-Pipe: Sieger gespeichert (Temp-Ordner), sauber beendet", r.returncode == 0 and "Gespeichert." in r.stdout and "Beendet" in r.stdout
      and json.loads((tmp / "tracking" / "pre_match_entries.json").read_text())["entries"][KEY]["markets"]["winner_incl_ot"]["home_odds"] == 1.6, (r.stdout + r.stderr)[-300:])

# ===== Keine Abrufe, echte Dateien unveraendert
check("Keine Abrufe: BallDontLie, Odds API, NBA.com unveraendert (0 neue Aufrufe)", (state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]) == real_calls, str(real_calls))
after = {n: sha(ROOT / "data" / n) for n in real}
check("Pickle, echte pre_match_entries.json und echte rosters.json unveraendert (SHA vor/nach), keine echte projection_snapshots-Aenderung", after == real, f"{real} -> {after}")

print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
