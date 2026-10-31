"""Tests (vor der Aktivierung der Betano-Automatik): UMGEKEHRTER Fall – fuer ein Spiel gibt es schon "auto"-Revisionen (save_auto), danach speichert eine
Handeingabe ueber den normalen Weg (eingabe.execute_plan via betano_import --datei, und save_card ohne source wie in der App). Muss normal gehen,
ohne doppelte/verwaiste Linien; danach gilt der Teil als "hand", eine spaetere Automatik-Speicherung wird fuer ihn uebersprungen. Dazu: Tab Pre-Match
zeigt auto-Quoten als vorbelegte Werte ohne Fehler, "unveraendert"-Hinweis der Handeingabe stimmt.
Offline (tests/fake_net.py), Temp-Ordner; echte Dateien nur per Hash geprueft.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_auto_then_hand.py"""
import hashlib, json, os, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install()
import betano_auto as ba
import betano_import as bi
import eingabe as ei
import data.pre_match_store as ps
import data.rosters as ro

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
REAL = [ROOT / "data/tracking/pre_match_entries.json", ROOT / "data/automation.log", ROOT / "data/betano_auto_state.json", ROOT / "data/upcoming_cache.json", ROOT / "data/rosters.json"]
real_before = {str(p): sha(p) for p in REAL}

FIX = ROOT / "tests/fixtures/betano_magic_hawks.har.json"
har = json.loads(FIX.read_text())["log"]["entries"]
dtl = json.loads(har[0]["response"]["content"]["text"])
M, HK = "Orlando Magic", "Atlanta Hawks"
START_MS = 1792623600000
START = "2026-10-21T23:00:00Z"
NOW = START_MS / 1000 - 6 * 3600
G = {"home": M, "away": HK, "date": "2026-10-21", "start": START}
KEY = ps.game_key(G["date"], START, M, HK)
GBDL = {"home_team": {"full_name": M}, "visitor_team": {"full_name": HK}, "date": G["date"], "datetime": START, "status": "scheduled"}

def setup():
    tmp = fresh_env()
    ro.rosters_path().write_text((ROOT / "data" / "rosters.json").read_text())
    (tmp / "upcoming_cache.json").write_text(json.dumps({"fetched_at": NOW, "params": {}, "games": [GBDL]}))
    return tmp
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def revs(n):
    out = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                (out.extend(v) if k == "revisions" else walk(v))
        elif isinstance(x, list):
            [walk(i) for i in x]
    walk(n); return out
def integrity(e):
    """Fehlerliste: doppelte Linienwerte/IDs unter den aktiven Linien, Linien ohne Revision (verwaist), doppelte Spieler/Zeilen-IDs."""
    errs, mk = [], e.get("markets", {})
    def chk(name, lines, key):
        ids = [l["id"] for l in lines]
        if len(ids) != len(set(ids)): errs.append(f"{name}: doppelte IDs")
        act = [l for l in lines if l.get("active", True)]
        vals = [l.get(key) for l in act]
        if len(vals) != len(set(vals)): errs.append(f"{name}: doppelte aktive Linie {sorted(v for v in vals if vals.count(v) > 1)}")
        for l in lines:
            if not l.get("revisions"): errs.append(f"{name}: {l['id']} ohne Revision (verwaist)")
    chk("spread", (mk.get("spread") or {}).get("lines", []), "line_home")
    chk("total", (mk.get("total") or {}).get("lines", []), "line")
    for side in ("home", "away"):
        chk(f"team_{side}", ((mk.get("team_totals") or {}).get(side) or {}).get("lines", []), "line")
    pids = [b["person_id"] for b in (mk.get("player_points") or {}).get("players", []) if b.get("active", True)]
    if len(pids) != len(set(pids)): errs.append("Spieler doppelt")
    for b in (mk.get("player_points") or {}).get("players", []):
        chk(f"spieler {b['name']}", b.get("lines", []), "threshold")
    w = mk.get("winner_incl_ot")
    if w and not w.get("revisions"): errs.append("winner ohne Revision")
    return errs
def auto_save(data):
    return ba.process_game(G, None, data, NOW)
def hand_import():
    out = []
    rc = bi.main(["--datei", str(FIX)], real=lambda p: "", write=out.append, now_fn=lambda: NOW)       # Enter bei "Speichern?" = normaler Handweg (execute_plan -> save_card)
    return rc, out
def alt(price_add):
    d = json.loads(json.dumps(dtl))
    for col in d["data"]["event"]["sixPackLayout"]["columns"]:
        for s in col.get("selections", []): s["price"] = str(round(float(s["price"]) + price_add, 2))
    for m in d["data"]["event"].get("markets", []):
        for r in (m.get("tableLayout") or {}).get("rows", []):
            for g_ in r.get("groupSelections", []):
                for s in g_.get("selections", []): s["price"] = str(round(float(s["price"]) + price_add, 2))
    return d["data"]

# ===== A) volle Karte per Automatik, danach Handimport (eingabe.execute_plan, Spieler-Linien ersetzen)
setup()
r = auto_save(dtl["data"])
e0 = entry(); n_auto = len(revs(e0))
check("A1 Automatik hat alle Maerkte gespeichert (nur source=auto)", r == "saved" and n_auto > 20 and all(x.get("source") == "auto" for x in revs(e0)), f"{r} {n_auto}")
check("A1 Integritaet nach auto in Ordnung", not integrity(e0), str(integrity(e0)))
rc, out = hand_import()
check("A2 Handimport mit gleichen Quoten: kein Fehler, 'Nichts geändert.' (Vorbelegung = auto-Werte, unveraendert erkannt)", rc == 0 and any("Nichts geändert" in x for x in out) and not any("ABBRUCH" in x for x in out), "\\n".join(out[-6:]))
check("A2 'schon gespeichert, unverändert'-Hinweis steht in der Zusammenfassung", any("schon gespeichert, unverändert" in x for x in out))
check("A2 Eintrag byte-gleich (Hand ohne Aenderung schreibt nichts, auto bleibt auto)", json.dumps(entry(), sort_keys=True) == json.dumps(e0, sort_keys=True))
# Hand mit geaenderten Quoten (normaler Weg)
import betano_import
orig_load = betano_import.load_payloads
alt_data = alt(0.25)
betano_import.load_payloads = lambda path: [alt_data] + [d for d in orig_load(path) if "blocks" in d]
try:
    rc, out = hand_import()
finally:
    betano_import.load_payloads = orig_load
e1 = entry()
check("A3 Handimport mit geaenderten Quoten: Gespeichert, kein Fehler/ABBRUCH", rc == 0 and any("Gespeichert" in x for x in out) and not any("ABBRUCH" in x or "Fehler" in x for x in out), "\\n".join(out[-5:]))
check("A3 keine doppelten oder verwaisten Linien, Spieler nur einmal", not integrity(e1), str(integrity(e1)))
w = e1["markets"]["winner_incl_ot"]
check("A3 Sieger: Revisionen auto…, dann hand (ohne source); aktueller Wert = Handwert", [x.get("source", "hand") for x in w["revisions"]] == ["auto", "hand"] and w["home_odds"] != e0["markets"]["winner_incl_ot"]["home_odds"], str(w["revisions"]))
check("A3 Sieger gilt jetzt als hand", ps.has_hand_revision(w) and not ps.has_hand_revision(e0["markets"]["winner_incl_ot"]))
sp = e1["markets"]["spread"]["lines"][0]
check("A3 Spread-Hauptlinie: hand-Revision angehaengt, gleiche Linie (keine zweite Hauptlinie)", ps.has_hand_revision(sp) and len([l for l in e1["markets"]["spread"]["lines"] if l["id"] == "main"]) == 1)
# Automatik danach: Teile mit Hand werden uebersprungen
rc_before = json.dumps(entry(), sort_keys=True)
r2 = auto_save(alt(0.5))
check("A4 spaetere Automatik: alle Teile mit Hand uebersprungen (Spielstatus skipped), Eintrag byte-gleich", r2 in ("skipped",) and json.dumps(entry(), sort_keys=True) == rc_before, f"{r2}")

# ===== B) App-Weg: save_card ohne source, nur ein Teil (Sieger) -> Rest bleibt auto-aktualisierbar
setup()
auto_save(dtl["data"])
e0 = entry()
ps.save_card(G["date"], START, M, HK, winner={"home_odds": "1,40", "away_odds": "3,10", "bookmaker": "Pinnacle"}, now=NOW)
e1 = entry()
check("B1 App-Speichern des Siegers (save_card ohne source): normal gespeichert, Integritaet ok", e1["markets"]["winner_incl_ot"]["home_odds"] == 1.4 and not integrity(e1) and e1["markets"]["winner_incl_ot"]["revisions"][-1].get("source") is None)
check("B1 andere Maerkte unveraendert (noch auto, Revisionszahl gleich)", json.dumps(e1["markets"]["spread"], sort_keys=True) == json.dumps(e0["markets"]["spread"], sort_keys=True))
r3 = auto_save(alt(0.5))
e2 = entry()
check("B2 spaetere Automatik: Sieger bleibt Hand (1,40), Spread/Total werden weiter als auto aktualisiert", e2["markets"]["winner_incl_ot"]["home_odds"] == 1.4 and r3 == "saved" and e2["markets"]["spread"]["lines"][0]["revisions"][-1].get("source") == "auto" and not integrity(e2), f"{r3}")
# App-Weg auf einer auto-Linie (Hauptlinie des Spreads, mit der gespeicherten ID, wie die Oberflaeche sie sendet)
sp0 = e2["markets"]["spread"]["lines"][0]
ps.save_card(G["date"], START, M, HK, spread_rows=[{"id": "main", "line": str(sp0["line_home"]).replace(".", ","), "home_odds": "1,80", "away_odds": "2,00", "bookmaker": "Betano"}], now=NOW)
e3 = entry()
check("B3 App-Speichern auf einer auto-Spread-Linie: ok, gleiche Linie, keine Dublette, danach hand", ps.has_hand_revision(e3["markets"]["spread"]["lines"][0]) and not integrity(e3) and len(e3["markets"]["spread"]["lines"]) == len(e2["markets"]["spread"]["lines"]))
before = json.dumps(entry(), sort_keys=True)
r4 = auto_save(alt(0.75))
e4 = entry()
check("B4 Automatik fasst die Hand-Spread-Leiter nie mehr an (Spread-Linien byte-gleich)", json.dumps(e4["markets"]["spread"], sort_keys=True) == json.dumps(e3["markets"]["spread"], sort_keys=True), f"{r4}")
check("B4 Automatik darf Total (noch auto) weiter aktualisieren", ps.has_hand_revision(e4["markets"]["total"]) is False and not integrity(e4))

# ===== C) Anzeige: Tab Pre-Match mit auto-Quoten vorbelegt
from streamlit.testing.v1 import AppTest
fresh_env(remaining=400)
state["commence_offsets"] = {"New York Knicks": 3 * 3600}
from data import fetcher
g = [x for x in fetcher.fetch_upcoming_games() if x["home_team"]["full_name"] == "New York Knicks"][0]
st_ = ps.normalize_start(g["datetime"])
ps.save_auto(g["date"], st_, "New York Knicks", "Philadelphia 76ers", winner={"home_odds": "1,70", "away_odds": "2,20", "bookmaker": "Betano"},
             spread_rows=[{"id": "main", "line": "-4,5", "home_odds": "1,91", "away_odds": "1,95", "bookmaker": "Betano"}],
             total_rows=[{"id": "main", "direction": None, "line": "231,5", "over_odds": "1,91", "under_odds": "1,89", "bookmaker": "Betano"}])
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
vals = {t.key: t.value for t in at.text_input if t.key}
check("C1 Tab Pre-Match: keine Exception, keine Warnung/Fehlermeldung mit auto-Eintrag", not at.exception and not at.warning and not at.error, str([e.value for e in at.exception])[:200])
check("C1 auto-Quoten sind als Werte vorbelegt (Sieger, Spread, Total)", "2,20" in vals.values() and "1,70" in vals.values() and "-4,5" in vals.values() and "231,5" in vals.values() and "1,89" in vals.values())
e_ui = (ps.load()["entries"] or {})
check("C1 die Anzeige hat nichts geschrieben (Revisionszahl unveraendert: 3 = Sieger, Spread, Total)", sum(len(revs(v)) for v in e_ui.values()) == 3, str(sum(len(revs(v)) for v in e_ui.values())))

real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unveraendert", real_before == real_after, str({k: v for k, v in real_after.items() if real_before[k] != v}))
print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
