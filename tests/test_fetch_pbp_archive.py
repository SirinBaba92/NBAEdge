"""Test fuer analysis/fetch_pbp_archive.py ohne Netz: Auswertung der Antwort, Ueberspringen vorhandener Dateien, Sperre (403), Fehlschlag.
Aufruf aus dem Projektordner: venv/bin/python tests/test_fetch_pbp_archive.py"""
import gzip, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import fetch_pbp_archive as fp

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
cache = T / "cache"; cache.mkdir()
rows = [{"game_id": g} for g in ("0022500001", "0022500002", "0022500003", "0042500101")]
(cache / "player_games_2025-26.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")


def body(gid, n=3):
    return json.dumps({"game": {"gameId": gid, "actions": [{"actionNumber": i} for i in range(n)]}}).encode()


# Auswertung
assert fp.game_ids("2025-26", cache) == ["0022500001", "0022500002", "0022500003"]       # Playoff-ID (004...) entfaellt
assert fp.parse_response(body("0022500001"), "0022500001") == 3
for bad, gid in ((b"nope", "0022500001"), (body("0022500009"), "0022500001"), (body("0022500001", 0), "0022500001"), (b'{"x": 1}', "0022500001")):
    try:
        fp.parse_response(bad, gid); raise SystemExit("haette ValueError werfen muessen")
    except ValueError:
        pass

# Lauf: 1 vorhanden (uebersprungen), 1 gut, 1 mit falscher ID (Fehlschlag)
out = T / "out"
fp.save_gz(fp.target_path(out, "2025-26", "0022500001"), body("0022500001"))
calls, sleeps = [], []
def fake(gid):
    calls.append(gid)
    return 200, body(gid) if gid == "0022500002" else body("0022500999")
arc = fp.Archive(out, fetch=fake, sleep=sleeps.append, write=lambda *_: None)
res = arc.run(["2025-26"], cache)
r = res["report"]["2025-26"]
assert calls == ["0022500002", "0022500003"], calls                                       # vorhandene Datei: kein Abruf
assert (r["expected"], r["saved"], r["fresh"], len(r["failed"])) == (3, 2, 1, 1), r
assert json.loads(gzip.decompress(fp.target_path(out, "2025-26", "0022500002").read_bytes()))["game"]["gameId"] == "0022500002"
assert not fp.target_path(out, "2025-26", "0022500003").exists()
assert "0022500003" in (out / "fehlschlaege.txt").read_text()

# Zweiter Lauf: nur der Fehlschlag wird erneut versucht
calls.clear()
fp.Archive(out, fetch=fake, sleep=lambda s: None, write=lambda *_: None).run(["2025-26"], cache)
assert calls == ["0022500003"], calls

# Sperre: 403 -> sofort Stopp, kein Wiederholen
out2 = T / "out2"; calls2 = []
def blocked(gid):
    calls2.append(gid); return 403, b""
res = fp.Archive(out2, fetch=blocked, sleep=lambda s: None, write=lambda *_: None).run(["2025-26"], cache)
assert res["stopped"] == "gesperrt" and calls2 == ["0022500001"], (res["stopped"], calls2)
assert "GESPERRT" in (out2 / "protokoll.txt").read_text()

# 5xx: 2 Wiederholungen (3 Abrufe), dann Fehlschlag und weiter
out3 = T / "out3"; calls3 = []
def err(gid):
    calls3.append(gid); return 503, b""
res = fp.Archive(out3, fetch=err, sleep=lambda s: None, write=lambda *_: None).run(["2025-26"], cache)
assert len(calls3) == 9 and len(res["report"]["2025-26"]["failed"]) == 3, len(calls3)
print("OK test_fetch_pbp_archive")
