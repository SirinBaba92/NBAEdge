"""
Kopfzeilen fuer cdn.nba.com mit automatisch ermittelter Chrome-Version (nur lesend, kein Netz).

Der NBA-Server (Akamai) lehnt Abrufe mit HTTP 403 ab, wenn Origin/Referer fehlen oder der User-Agent kein Chrome mit
aktueller Version ist (gemessen am 22.10.2026: Chrome/147 und /150 gehen, /144 nicht; Safari und Firefox gehen nicht).
Deshalb wird die Hauptversion aus dem installierten Browser gelesen (Chrome, sonst Brave, sonst Chromium) und nie unter
FALLBACK_MAJOR gesetzt; ist kein Browser lesbar, gilt FALLBACK_MAJOR. Genutzt vom Recorder (record_live.py); nba_live.py bleibt vorerst unveraendert.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

FALLBACK_MAJOR = 150
MIN_PLAUSIBLE, MAX_PLAUSIBLE = 100, 400
BROWSER_APPS = (
    Path("/Applications/Google Chrome.app"),
    Path("/Applications/Brave Browser.app"),
    Path("/Applications/Chromium.app"),
)


def _major(text) -> int | None:
    m = re.match(r"\s*(\d+)", str(text or ""))
    if not m:
        return None
    value = int(m.group(1))
    return value if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE else None


def _app_major(app: Path) -> int | None:
    """Hauptversion aus Info.plist (Chrome und Brave tragen dort 150.x.y.z); sonst aus dem Versions-Ordner des Frameworks."""
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        major = _major(info.get("CFBundleShortVersionString"))
        if major:
            return major
    except Exception:
        pass
    try:
        versions = [p.name for p in (app / "Contents" / "Frameworks").glob("*.framework/Versions/*") if p.name != "Current"]
        majors = [m for m in (_major(v) for v in versions) if m]
        return max(majors) if majors else None
    except Exception:
        return None


def detect_chrome_major(apps=BROWSER_APPS, fallback: int = FALLBACK_MAJOR) -> int:
    """Hoechste lesbare Browser-Hauptversion, aber nie kleiner als der Rueckfall (ein veralteter Browser soll keinen 403 ausloesen)."""
    found = [m for m in (_app_major(Path(a)) for a in apps) if m]
    return max([fallback] + found)


def nba_headers(major: int | None = None) -> dict:
    major = major or detect_chrome_major()
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.nba.com",
        "Referer": "https://www.nba.com/",
    }
