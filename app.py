"""Streamlit-Oberflaeche "Import eduExaminer": Excel rein, EXZ raus.

    streamlit run app.py

Die Punktelogik liegt in exz/api.py - die App ist nur die Bedienoberflaeche.
"""
from __future__ import annotations

import io
from pathlib import Path

import streamlit as st

from exz.api import BuildError, BuildOptions, convert, points_for
from exz.excel import AnswerFlagError, LayoutError, read_questions
from exz.scoring import (
    DEFAULT_DECIMALS,
    DEFAULT_ESSAY_POINTS,
    DEFAULT_TOTAL,
    fmt,
)

HERE = Path(__file__).parent
TEMPLATE = HERE / "vorlage" / "struktur-vorlage.exz"

st.set_page_config(page_title="Import eduExaminer", page_icon="📝",
                   layout="centered")


@st.cache_data(show_spinner=False)
def load_template() -> bytes:
    return TEMPLATE.read_bytes()


def de(value) -> str:
    """Deutsche Schreibweise: 1,333 statt 1.333."""
    return fmt(value).replace(".", ",")


# ----------------------------------------------------------------- Oberflaeche

st.title("Import eduExaminer")

if not TEMPLATE.exists():
    st.error(
        f"Die Strukturvorlage fehlt: `{TEMPLATE}`. Sie liefert den Bauplan für "
        "beide Fragearten und muss neben der App liegen."
    )
    st.stop()

with st.sidebar:
    st.header("Bepunktung")

    essay_points = st.number_input(
        "Punkte je offener Frage",
        min_value=0.0, max_value=100.0,
        value=float(DEFAULT_ESSAY_POINTS), step=0.5, format="%.3g",
    )

    st.markdown("**Multiple Choice** – fest eingestellt:")
    st.markdown(
        """
| richtige Antworten | richtig | falsch |
|---|---|---|
| 1 von 4 | +4 | −1,333 |
| 2 von 4 | +2 | −2 |
| 3 von 4 | +1,333 | −4 |
"""
    )

opts = BuildOptions(
    total=DEFAULT_TOTAL,
    essay_points=float(essay_points),
    decimals=DEFAULT_DECIMALS,
    negative=False,
)

upload = st.file_uploader(
    "Excel-Datei mit den Fragen",
    type=["xlsx", "xlsm"],
)

if upload is None:
    st.info("Laden Sie eine Excel-Datei hoch.")
    st.stop()

raw = upload.getvalue()

# --- einlesen und prüfen ----------------------------------------------------
try:
    questions, warnings, layout = read_questions(io.BytesIO(raw))
except LayoutError as exc:
    st.error(f"**Aufbau nicht erkannt.** {exc}")
    st.stop()
except AnswerFlagError as exc:
    st.error(f"**Unklarer Wert in einer true/false-Spalte.** {exc}")
    st.stop()
except Exception as exc:  # noqa: BLE001
    st.error(f"**Die Datei konnte nicht gelesen werden.** {type(exc).__name__}: {exc}")
    st.stop()

if not questions:
    st.error("In der Datei wurden keine Fragen gefunden.")
    st.stop()

counts = {}
for q in questions:
    counts[q.qtype] = counts.get(q.qtype, 0) + 1

n_images = sum(len(q.images) for q in questions)

spalten = st.columns(4 if n_images else 3)
spalten[0].metric("Fragen gesamt", len(questions))
spalten[1].metric("Multiple Choice", counts.get("multiple", 0))
spalten[2].metric("Offene Fragen", counts.get("essay", 0))
if n_images:
    spalten[3].metric("Bilder", n_images)

st.caption(f"Erkannter Aufbau: {layout.describe()}")

for warning in warnings:
    st.warning(warning)

# --- Vorschau ---------------------------------------------------------------
rows = []
for q in questions:
    pts = points_for(q, opts)
    rows.append({
        "Nr": q.number,
        "Zeile": q.row,
        "Art": "Multiple Choice" if q.qtype == "multiple" else "offen",
        "Antw.": q.n_options or "–",
        "davon richtig": q.n_correct if q.qtype == "multiple" else "–",
        "je richtig": de(pts.correct) if q.qtype == "multiple" else "–",
        "je falsch": de(pts.wrong) if q.qtype == "multiple" else "–",
        "max": de(pts.max_score),
        "Bild": "ja" if q.images else "",
        "Frage": q.text or ("(nur Bild)" if q.images else ""),
    })

with st.expander(f"Vorschau der {len(rows)} Fragen", expanded=False):
    st.dataframe(rows, hide_index=True, use_container_width=True)

if n_images:
    with st.expander(f"{n_images} Bild(er) aus der Datei", expanded=False):
        for q in questions:
            for bild in q.images:
                st.caption(
                    f"Frage {q.number} (Zeile {q.row}) – "
                    f"{bild.width}×{bild.height} px")
                st.image(bild.data, width=min(bild.width or 400, 400))

# --- bauen ------------------------------------------------------------------
try:
    result = convert(io.BytesIO(raw), load_template(), opts)
except BuildError as exc:
    st.error(f"**Umwandlung nicht möglich.** {exc}")
    st.stop()
except Exception as exc:  # noqa: BLE001
    st.error(f"**Unerwarteter Fehler.** {type(exc).__name__}: {exc}")
    st.stop()

out_name = Path(upload.name).with_suffix(".exz").name

st.success(
    f"{len(result.questions)} Fragen umgewandelt – {result.summary()}."
)
st.download_button(
    f"⬇  {out_name} herunterladen",
    data=result.exz,
    file_name=out_name,
    mime="application/octet-stream",
    type="primary",
    use_container_width=True,
)

st.markdown(
    """
**In eduExaminer hochladen:** Rolle *Autor* → *Topics Questions* → *import*
→ Reiter **bizExaminer file** → Datei wählen → *Upload*.

Bitte zuerst mit einer einzelnen Frage testen und nach dem Import prüfen,
ob die Punktzahlen stimmen.
"""
)
