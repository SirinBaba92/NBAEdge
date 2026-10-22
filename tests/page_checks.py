"""Gemeinsame Seitenpruefung fuer AppTest-Tests: JEDER AppTest-Lauf wird auf Streamlit-Exceptions und auf den Streamlit-Satz
'was created with a default value but also had its value set via the Session State API' geprueft (Zusammenfassung am Ende
der Testdatei ueber page_checks.bad). Vor jedem Lauf wird Streamlits 'einmal pro Prozess'-Merker zurueckgesetzt."""
from streamlit.elements.lib import policies
from streamlit.testing.v1 import AppTest

PHRASE = "was created with a default value"
bad: list[str] = []
_installed = False


def problems(at) -> list[str]:
    """Alles, was nach einem Problem aussieht: Exceptions, Warnungen, Fehler, Streamlit-Satz in irgendeinem Element."""
    out = [f"Exception: {e.value}" for e in at.exception] + [f"Warnung: {w.value}" for w in at.warning] + [f"Fehler: {e.value}" for e in at.error]
    for group in (at.markdown, at.caption, at.info, at.text):
        out += [f"Text: {el.value}" for el in group if PHRASE in str(el.value)]
    return out


def install() -> None:
    global _installed
    if _installed:
        return
    orig = AppTest.run

    def run(self, *a, **k):
        policies._shown_default_value_warning = False
        result = orig(self, *a, **k)
        for e in self.exception:
            bad.append(f"Exception: {str(e.value)[:160]}")
        for group in (self.warning, self.markdown, self.caption, self.info, self.text, self.error):
            for el in group:
                if PHRASE in str(el.value):
                    bad.append(f"Streamlit-Satz: {str(el.value)[:160]}")
        return result

    AppTest.run = run
    _installed = True
