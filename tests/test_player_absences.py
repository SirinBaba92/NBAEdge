"""Tests fuer Stufe 4 (Ausfaelle, Baustein P8): data/absences_store.py, Ausfall-Neuberechnung in engine/player_forecast.py, Varianten in engine/player_snapshots.py, Vergleich in ui/player_view.py,
Bereich 'Ausfaelle' in ui/player_absence.py. Nur Temp-Ordner, kein Netz, keine echten Dateien. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_absences.py"""
import hashlib, json, os, subprocess, sys, tempfile, time, warnings
from datetime import date, timedelta
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import absences_store as ab
from data import live_feed as lf
from data import player_history as ph
from data import pre_match_store as ps
from engine import player_forecast as pf
from engine import player_snapshots as psn
from ui import player_absence as pa
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*")) + [ROOT / "data" / "rosters.json"]
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

class _NoNet:
    class R:
        status_code = 200
        def json(self): return {"scoreboard": {"gameDate": "2026-10-22", "games": []}}
    def get(self, url, **kw): return self.R()
lf._feed = lf.LiveFeed(http_get=_NoNet().get)

# ---------------------------------------------------------------- Fixture: Heim-Team mit 12 Spielern, Gast-Team mit 5
NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
FUT = iso(NOW + 5 * 3600)
D = lf.current_us_day(NOW)
KEY = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
NAMES = ["Eins", "Zwei", "Drei", "Vier", "Fuenf", "Sechs", "Sieben", "Acht", "Neun", "Zehn", "Elf", "Zwoelf"]
SPEC = [(39, 24), (34, 22), (33, 20), (31, 18), (30, 16), (26, 12), (24, 10), (22, 9), (20, 8), (18, 6), (14, 4), (12, 3)]
HOME = [(11 + i, n) for i, n in enumerate(NAMES)]
AWAY = [(31 + i, f"G{i}") for i in range(5)]
def grow(pid, name, minutes, points, team):
    d0 = date(2026, 1, 1)
    return [{"game_id": f"g{pid}-{i}", "date": (d0 + timedelta(days=2 * i)).isoformat(), "season": "2025-26", "person_id": pid, "name": name, "team": team, "opponent": "X", "home": True, "minutes": float(minutes), "points": points,
             "fga": 10, "fgm": 4, "fta": 2, "ftm": 1, "fg3a": 3, "fg3m": 1, "fouls": 2, "plus_minus": 0, "win": True, "margin": 4, "source": "league"} for i in range(30)]
rows = []
for (pid, n), (mn, pt) in zip(HOME, SPEC): rows += grow(pid, n, mn, pt, "HEI")
for i, (pid, n) in enumerate(AWAY): rows += grow(pid, n, 34 - 3 * i, 20 - 2 * i, "GAS")
ph.atomic_write_json(ph.season_path("2025-26"), {"version": 1, "format": "nbaedge-player-games", "season": "2025-26", "fetched_at": "x", "source": "t", "rows": sorted(rows, key=lambda r: r["date"])})
ph.atomic_write_json(ph.season_path("2026-27"), {"version": 1, "format": "nbaedge-player-games", "season": "2026-27", "fetched_at": "x", "source": "t", "rows": []})
roster = lambda team, abbr, pl: [{"person_id": i, "name": n, "position": "G", "jersey": "1", "team_id": 1, "team_abbreviation": abbr} for i, n in pl]
(T / "rosters.json").write_text(json.dumps({"version": 1, "format": "nbaedge-rosters", "fetched_at": "2026-10-21T04:56:44+02:00", "source": "t", "season": "2026-27", "abrufe": 1,
                                            "teams": {"Heim Falken": roster("Heim Falken", "HEI", HOME), "Gast Baeren": roster("Gast Baeren", "GAS", AWAY)}}))
def line(th, odds): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00", "entered_at": "2026-10-22T20:00:00+02:00"}
def block(pid, name, team, abbr, lines): return {"id": f"p{pid}", "person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "mode": "milestones", "active": True, "lines": lines}
ENTRIES = {KEY: {"game_date": D, "markets": {"player_points": {"players": [
    block(11, "Eins", "Heim Falken", "HEI", [line(20, 1.9), line(25, 3.2)]), block(12, "Zwei", "Heim Falken", "HEI", [line(18, 1.9), line(24, 4.0)]),
    block(13, "Drei", "Heim Falken", "HEI", [line(16, 1.9)]), block(21 + 0, "Elf", "Heim Falken", "HEI", [line(4, 1.5)]),
    block(31, "G0", "Gast Baeren", "GAS", [line(18, 1.9)]), block(32, "G1", "Gast Baeren", "GAS", [line(14, 1.9)])]}}}}
ENTRIES[KEY]["markets"]["player_points"]["players"][3]["person_id"] = 21                    # 'Elf' hat die Nummer 21
(T / "tracking").mkdir(parents=True, exist_ok=True)
(T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": ENTRIES}))
def write_model(hs=110.0, as_=108.0):
    (T / "tracking" / "projection_snapshots.json").write_text(json.dumps({"version": 1, "format": "x", "updated_at": None, "games": {KEY: {"home": "Heim Falken", "away": "Gast Baeren",
        "versions": [{"projection": {"exp_spread": hs - as_, "exp_total": hs + as_, "home_score": hs, "away_score": as_}}]}}}))
write_model()

# ---------------------------------------------------------------- A) Speicher
check("absences.json ist NICHT in .gitignore (damit in 'nbabackup' / git add -A enthalten)", subprocess.run(["git", "check-ignore", "-q", "data/tracking/absences.json"], cwd=ROOT).returncode == 1)
check("ohne Datei: leere Auswahl", ab.get(KEY) == {"out": {}, "doubtful": {}, "updated_at": None} and ab.load_error() is None)
pd = lambda i, n, t="Heim Falken": {"person_id": i, "name": n, "team": t}
r = ab.set_absences(KEY, [pd(11, "Eins")], [pd(12, "Zwei")], now=NOW)
g = ab.get(KEY)
check("Speichern: fehlt/fraglich je Spiel, mit Zeitstempel; Datei Version 1 Format nbaedge-absences, nach Tag gegliedert", r["status"] == "saved" and set(g["out"]) == {11} and set(g["doubtful"]) == {12} and g["out"][11]["name"] == "Eins"
      and json.loads((T / "tracking" / "absences.json").read_text())["days"][D][KEY]["out"]["11"]["set_at"] and json.loads((T / "tracking" / "absences.json").read_text())["version"] == 1)
check("gleiche Auswahl nochmal: unveraendert (keine neue History)", ab.set_absences(KEY, [pd(11, "Eins")], [pd(12, "Zwei")], now=NOW + 1)["status"] == "unchanged" and len(json.loads((T / "tracking" / "absences.json").read_text())["days"][D][KEY]["history"]) == 1)
ab.set_absences(KEY, [pd(11, "Eins"), pd(13, "Drei")], [], now=NOW + 2)
d = json.loads((T / "tracking" / "absences.json").read_text())["days"][D][KEY]
check("Aenderung ersetzt die Auswahl, History haelt jeden Stand, set_at bleibt fuer unveraenderte Spieler", set(ab.get(KEY)["out"]) == {11, 13} and ab.get(KEY)["doubtful"] == {} and len(d["history"]) == 2 and d["out"]["11"]["set_at"] == d["history"][0]["at"])
try:
    ab.set_absences(KEY, [pd(11, "Eins")], [pd(11, "Eins")]); check("Spieler in beiden Listen: abgelehnt", False)
except ValueError:
    check("Spieler in beiden Listen: abgelehnt, nichts geaendert", set(ab.get(KEY)["out"]) == {11, 13})
check("anderer Tag / anderes Spiel getrennt", ab.get(ps.game_key("2026-10-21", FUT, "A", "B")) == {"out": {}, "doubtful": {}, "updated_at": None})
before = (T / "tracking" / "absences.json").read_text()
(T / "tracking" / "absences.json").write_text("{kaputt")
try:
    ab.set_absences(KEY, [pd(11, "Eins")], []); check("beschaedigte Datei", False)
except ab.AbsencesError as e:
    check("beschaedigte Datei: Fehler mit Sicherungskopie, Datei unveraendert, load liefert error", "beschädigt" in str(e) and (T / "tracking" / "absences.json").read_text() == "{kaputt" and list((T / "tracking").glob("absences.corrupt-*")) and ab.load_error())
(T / "tracking" / "absences.json").write_text(before)
ab.set_absences(KEY, [], [], now=NOW + 3)

# ---------------------------------------------------------------- B) Neuberechnung (Engine)
ctx = pf.context_for_game(KEY)
base = pf.team_match("Heim Falken", True, ctx, D, {11: "Eins", 12: "Zwei", 13: "Drei", 21: "Elf"})
ab_ = pf.team_match("Heim Falken", True, ctx, D, {11: "Eins", 12: "Zwei", 13: "Drei", 21: "Elf"}, absent_ids={11})
bi, ai = base["info"], ab_["info"]
check("ohne Ausfall: Rotation = 10, Eins dabei, Elf (Rang 11) und Zwoelf draussen", bi["members"] == 10 and "Eins" in bi["rotation"] and bi["out_of_rotation"] == ["Elf", "Zwoelf"] and bi["absent"] == [])
check("mit Ausfall Eins: nicht in der Rotation, in info['absent'], freie Minuten = seine erwarteten Minuten", ai["absent"] == ["Eins"] and "Eins" not in ai["rotation"] and 11 not in ab_["adjusted"] and abs(ai["freed_minutes"] - base["raw"][11]["minutes"]["mean"]) < 1e-9, f"{ai['freed_minutes']:.1f}")
check("naechster Spieler rueckt in die Rotation (Elf rein, nur Zwoelf draussen), Rotation weiter 10", ai["members"] == 10 and "Elf" in ai["rotation"] and ai["out_of_rotation"] == ["Zwoelf"] and 21 in ab_["adjusted"] and 21 not in base["adjusted"])
check("Minuten der Rotation weiter 240", abs(ai["minutes_after"] - 240) < 1e-6)
up = [pid for pid in (12, 13, 14, 15) if ab_["adjusted"][pid]["expected_points"] > base["adjusted"][pid]["expected_points"]]
check("Mitspieler bekommen mehr Minuten und Punkte (Zwei, Drei, Vier, Fuenf)", up == [12, 13, 14, 15] and ab_["adjusted"][12]["minutes"]["mean"] >= base["adjusted"][12]["minutes"]["mean"], str(up))
check("Teamabgleich bleibt: Summe der Punkte der Rotation = Teampunkte (110), Faktor steigt (weniger Scorer)", abs(sum(f["expected_points"] for f in ab_["adjusted"].values()) - 110.0) < 0.6 and ai["factor"] > bi["factor"], f"{bi['factor']:.3f} -> {ai['factor']:.3f}")
check("Konstante dokumentiert: Obergrenze 40 Minuten je Spieler", pf.ABSENCE_MINUTES_CAP == 40.0)
two = pf.team_match("Heim Falken", True, ctx, D, {}, absent_ids={11, 12})
check("zwei Ausfaelle: beide ausser Rotation, freie Minuten = Summe, naechste Spieler rutschen nach", two["info"]["absent"] == ["Eins", "Zwei"] and two["info"]["freed_minutes"] > ai["freed_minutes"] and 21 in two["adjusted"])
res = pf.forecast_game_players(KEY, ENTRIES, absent_ids={11})
byn = {x["name"]: x for x in res["players"]}
check("forecast_game_players: Ausgefallener ohne Prognose (Grund 'fehlt (manuell eingetragen)', Qualitaet 'fehlt'), Mitspieler mit Prognose", not byn["Eins"]["forecast"]["ok"] and byn["Eins"]["forecast"]["reason"] == "fehlt (manuell eingetragen)" and byn["Eins"]["forecast"]["quality"] == ["fehlt"]
      and byn["Zwei"]["forecast"]["ok"] and res["teams"]["Heim Falken"]["absent"] == ["Eins"])
res0 = pf.forecast_game_players(KEY, ENTRIES)
check("ohne Ausfall: Eins hat eine Prognose; Zwei hat mit Ausfall hoehere erwartete Punkte und Chancen", res0["players"][0]["forecast"]["ok"] and {x["name"]: x for x in res0["players"]}["Zwei"]["forecast"]["expected_points_adjusted"] < byn["Zwei"]["forecast"]["expected_points_adjusted"]
      and {x["name"]: x for x in res0["players"]}["Zwei"]["forecast"]["p_ge_adjusted"][24] < byn["Zwei"]["forecast"]["p_ge_adjusted"][24])

# ---------------------------------------------------------------- C) Varianten: eigener Eintrag, Original unveraendert
st0, orig = psn.create_for_game(KEY, ENTRIES)
orig_file = T / "snaps" / f"{D}.json"
orig_hash = hashlib.sha1(orig_file.read_bytes()).hexdigest()
s1, v1 = psn.create_variant(KEY, ENTRIES, [pd(11, "Eins")], [pd(12, "Zwei")])
check("Variante geschrieben in <Tag>.absences.json, Original-Snapshot bytegleich", s1 == "geschrieben" and psn.variants_path(D).exists() and hashlib.sha1(orig_file.read_bytes()).hexdigest() == orig_hash and psn.variants_path(D).name == f"{D}.absences.json")
check("Variante: Zeitstempel, Ausfallliste, Verweis auf den Original-Snapshot, Eintrag im Snapshot-Format", v1["created_at"] and [p["person_id"] for p in v1["out"]] == [11] and [p["person_id"] for p in v1["doubtful"]] == [12] and v1["base_created_at"] == orig["created_at"]
      and {"players", "teams", "context"} <= set(v1["entry"]))
vp = {p["person_id"]: p for p in v1["entry"]["players"]}
check("Variante: Ausgefallener ohne Prognose ('fehlt'), Fragliche mit Qualitaet 'fraglich' und Hinweis, Mitspieler hoehere Minuten", not vp[11]["ok"] and "fehlt (manuell eingetragen)" in vp[11]["warnings"] and "fraglich" in vp[12]["quality"] and any("fraglich" in w for w in vp[12]["warnings"])
      and vp[12]["minutes_adjusted"] >= {p["person_id"]: p for p in orig["players"]}[12]["minutes_adjusted"] - 1e-9)
s2, v2 = psn.create_variant(KEY, ENTRIES, [pd(11, "Eins")], [pd(12, "Zwei")])
check("gleiche Auswahl: 'unveraendert', kein Duplikat", s2 == "unveraendert" and len(psn.load_variants(KEY)) == 1)
s3, v3 = psn.create_variant(KEY, ENTRIES, [pd(11, "Eins"), pd(13, "Drei")], [])
check("andere Auswahl: neue Variante angehaengt (Verlauf bleibt), latest_variant passt nur zur genauen Auswahl", s3 == "geschrieben" and len(psn.load_variants(KEY)) == 2 and psn.latest_variant(KEY, {11, 13}, set()) is not None and psn.latest_variant(KEY, {11}, {12}) is None)
check("Original-Snapshot nach allen Varianten weiter bytegleich", hashlib.sha1(orig_file.read_bytes()).hexdigest() == orig_hash)
import analysis.eval_player_forecasts as ev
check("Auswerte-Skript liest nur <Tag>.json, nicht die Varianten-Datei", list(ev.load_snapshots(T / "snaps")) == [D])
write_model(); (T / "tracking" / "projection_snapshots.json").unlink()
try:
    psn.create_variant(KEY, ENTRIES, [pd(11, "Eins")], []); check("ohne Spielmodell keine Neuberechnung", False)
except ValueError as e:
    check("ohne Schnappschuss des Spielmodells: verstaendlicher Fehler, nichts geschrieben", "Schnappschuss des Spielmodells" in str(e) and len(psn.load_variants(KEY)) == 2)
write_model()

# ---------------------------------------------------------------- D) Vergleich (View)
m = pv.build_compare_model(orig, v1["entry"], "team")
P = {p["person_id"]: p for p in m["players"]}
check("Vergleich: Eins 'fehlt' ohne Minuten/Punkte neu, Zwei 'fraglich', Zwei mit Aenderung (neu - alt) in Prozentpunkten", P[11]["flag"] == "fehlt" and P[11]["minutes"] is None and P[11]["minutes_old"] is not None and P[12]["flag"] == "fraglich"
      and all(r["delta"] is not None for r in P[13]["rows"]) and P[13]["rows"][0]["delta"] == P[13]["rows"][0]["model_pct"] - P[13]["rows"][0]["model_old_pct"], "")
html = pv.render_compare_html(m)
check("Vergleich-HTML: Spalten alt/neu, Aenderung, Differenz neu, Markierungen 'fehlt'/'fraglich', ungeprueft", "Modell alt" in html and "Modell neu" in html and "Änderung" in html and "<span class='pl-m'>fehlt</span>" in html and "<span class='pl-m'>fraglich</span>" in html and "ungeprüft" in html and " → " in html)
check("Vergleich ohne Original-Snapshot: nur neue Werte, alte mit Strich", all(p["minutes_old"] is None for p in pv.build_compare_model(None, v1["entry"])["players"]))
check("Farben: kein Gruen/Rot im Vergleich", not any(c in html for c in ("#22c55e", "#ef4444")))

# ---------------------------------------------------------------- E) Bereich im Tab (AppTest)
ab.set_absences(KEY, [], [], now=NOW + 10)
for f in (psn.variants_path(D),): f.unlink()
HARNESS = str(ROOT / "tests" / "_harness_player_tab.py")
def run():
    at = AppTest.from_file(HARNESS, default_timeout=120).run()
    at = at.selectbox(key="pl_day").set_value(D).run()
    return at.selectbox(key=f"pl_game_{D}").set_value(KEY).run()
at = run()
ms = [x for x in at.multiselect]
check("Bereich 'Ausfaelle': Mehrfachauswahl 'Fehlt' und 'Fraglich' aus dem Kader beider Teams (17 Spieler), Knoepfe", [x.label for x in ms] == ["Fehlt", "Fraglich"] and len(ms[0].options) == 17 and [b.label for b in at.button if "Auswahl speichern" in b.label or "neu rechnen" in b.label] == ["Auswahl speichern", "Prognose mit Ausfällen neu rechnen"]
      and not at.exception, " | ".join(problems(at))[:200])
check("Spieler der Auswahl mit Team-Kuerzel beschriftet", any("Eins (HEI)" in o for o in ms[0].options))
out_ms = next(x for x in at.multiselect if x.label == "Fehlt"); out_ms.set_value([11]).run()
next(b for b in at.button if b.label == "Auswahl speichern").click().run()
check("Auswahl speichern: in absences.json gespeichert (pro Tag), Meldung, keine Neuberechnung", set(ab.get(KEY)["out"]) == {11} and any("Auswahl gespeichert" in x.value for x in at.success) and not psn.variants_path(D).exists() and not at.exception)
check("nach dem Speichern: Hinweis 'noch keine Neuberechnung'", any("Noch keine Neuberechnung" in x.value for x in at.info))
next(b for b in at.button if "neu rechnen" in b.label).click().run()
Hc = " ".join(x.value for x in at.markdown)
check("Kartenansicht (Standard) nach der Neuberechnung: Kasten 'Ausfaelle fuer dieses Spiel', Karten mit Werten der Variante, keine Vergleichstabelle", "Ausfälle für dieses Spiel" in Hc and "pl-cards" in Hc and "Modell alt" not in Hc and "Neuberechnung vom" in Hc and not at.exception, " | ".join(problems(at))[:200])
msg_ok = any("Neuberechnet und als eigener Stand gespeichert" in x.value for x in at.success)
at.toggle(key="pl_table_view").set_value(True).run()                 # Tabellenansicht: Vergleichstabelle "alt / neu / Aenderung" wie bisher
H = " ".join(x.value for x in at.markdown)
check("Neuberechnung: eigener Eintrag gespeichert, Original-Snapshot bytegleich, Vergleichstabelle mit 'Modell alt'/'Modell neu' und Zeile 'Neuberechnung vom'", psn.variants_path(D).exists() and hashlib.sha1(orig_file.read_bytes()).hexdigest() == orig_hash
      and "Modell alt" in H and "Modell neu" in H and "Neuberechnung vom" in H and "<span class='pl-m'>fehlt</span>" in H and not at.exception, " | ".join(problems(at))[:200])
check("Meldung nach der Neuberechnung", msg_ok)
H2 = " ".join(x.value for x in at.markdown)
check("Haupttabelle zeigt weiter den ursprünglichen Snapshot (Eins mit Prognose), Tooltip nennt die Ausfall-Auswahl", "Ausfall-Auswahl: fehlt" in H2 and "Eins" in H2)
# Aenderung der Auswahl -> alter Vergleich gehoert nicht mehr dazu
out_ms = next(x for x in at.multiselect if x.label == "Fehlt"); out_ms.set_value([11, 13]).run()
next(b for b in at.button if b.label == "Auswahl speichern").click().run()
check("geaenderte Auswahl ohne Neuberechnung: Hinweis statt Vergleich", any("gehört zu einer anderen Auswahl" in x.value for x in at.info) and "Neuberechnung vom" not in " ".join(x.value for x in at.markdown))
dbt = next(x for x in at.multiselect if x.label == "Fraglich"); dbt.set_value([11]).run()
check("Spieler bei Fehlt und Fraglich: Warnung (Streamlit-Warnung wird ausdruecklich erlaubt)", any("nur eins wählen" in w.value for w in at.warning))
page_checks.bad.clear()

check("echte Dateien (Tracking, Snapshots, Kader) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
