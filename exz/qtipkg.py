"""Vollstaendiges QTI-1.2-Paket (questestinterop) aus den Excel-Fragen.

Das ist der OFFIZIELL dokumentierte Importweg von bizExaminer/eduExaminer:
  Autor-Rolle -> Topics Questions -> import -> "QTI and QML import"
  Feld: "QTI XML file for import (Matrix as QML) - ZIP allowed"
  Unterstuetzte Version laut Doku: QTI 1.2

Punkte stehen in <resprocessing>/<setvar> und sind dort per Spezifikation
Dezimalwerte (<decvar vartype="Decimal">) - genau die Luecke, die der
CSV/XLSX-Import nicht abdeckt.
"""
from __future__ import annotations

import io
import os
import zipfile

from .excel import Question
from .qti import LETTERS, as_html, cdata
from .scoring import Points, fmt

DOCTYPE = (
    '<!DOCTYPE questestinterop SYSTEM '
    '"http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.dtd">'
)


def esc(text: str) -> str:
    """Escaping fuer Attributwerte und Elementtext (CDATA hat eigene Regeln)."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _mattext(text: str, indent: str) -> str:
    return (
        f'{indent}<mattext texttype="text/html">{cdata(as_html(text))}</mattext>'
    )


def build_item(
    q: Question,
    pts: Points,
    ident: str,
    shuffle: bool = False,
    cardinality: str = "Multiple",
) -> str:
    """Ein <item>-Block: Praesentation + Bewertung."""
    shuffle_attr = "Yes" if shuffle else "No"
    title = esc(q.text)
    max_score = fmt(pts.correct * pts.n_correct)
    min_score = fmt(pts.wrong * (pts.n_options - pts.n_correct))

    out = [
        f'    <item ident="{ident}" title="{title[:250]}">',
        "      <itemmetadata>",
        "        <qtimetadata>",
        "          <qtimetadatafield>",
        "            <fieldlabel>qmd_itemtype</fieldlabel>",
        f"            <fieldentry>{'Multiple Choice' if q.qtype == 'multiple' else 'Text'}</fieldentry>",
        "          </qtimetadatafield>",
        "          <qtimetadatafield>",
        "            <fieldlabel>qmd_maximumscore</fieldlabel>",
        f"            <fieldentry>{max_score}</fieldentry>",
        "          </qtimetadatafield>",
        "        </qtimetadata>",
        "      </itemmetadata>",
        "      <presentation>",
        "        <material>",
        _mattext(q.text, "          "),
        "        </material>",
    ]

    if q.qtype == "multiple":
        out += [
            f'        <response_lid ident="1" rcardinality="{cardinality}">',
            f'          <render_choice shuffle="{shuffle_attr}">',
        ]
        for i, opt in enumerate(q.options):
            out += [
                f'            <response_label ident="{LETTERS[i]}">',
                "              <material>",
                _mattext(opt.text, "                "),
                "              </material>",
                "            </response_label>",
            ]
        out += ["          </render_choice>", "        </response_lid>"]
    else:
        out += [
            '        <response_str ident="1" rcardinality="Single">',
            '          <render_fib rows="6" columns="80" prompt="Box"/>',
            "        </response_str>",
        ]

    out += [
        "      </presentation>",
        "      <resprocessing>",
        "        <outcomes>",
        f'          <decvar varname="SCORE" vartype="Decimal" defaultval="0"'
        f' minvalue="{min_score}" maxvalue="{max_score}"/>',
        "        </outcomes>",
    ]

    if q.qtype == "multiple":
        for i, opt in enumerate(q.options):
            score = fmt(pts.correct if opt.correct else pts.wrong)
            out += [
                '        <respcondition continue="Yes">',
                "          <conditionvar>",
                f'            <varequal respident="1" case="Yes">{LETTERS[i]}</varequal>',
                "          </conditionvar>",
                f'          <setvar varname="SCORE" action="Add">{score}</setvar>',
                "        </respcondition>",
            ]

    out += ["      </resprocessing>", "    </item>"]
    return "\n".join(out)


def build_bank(
    items: list[tuple[Question, Points, str]],
    bank_title: str = "Fragenpool",
    shuffle: bool = False,
) -> str:
    """items: (Frage, Punkte, Kardinalitaet) je Eintrag."""
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        DOCTYPE,
        "<questestinterop>",
        '  <objectbank ident="BANK_1">',
        "    <qtimetadata>",
        "      <qtimetadatafield>",
        "        <fieldlabel>qmd_title</fieldlabel>",
        f"        <fieldentry>{esc(bank_title)}</fieldentry>",
        "      </qtimetadatafield>",
        "    </qtimetadata>",
    ]
    for q, pts, cardinality in items:
        body.append(build_item(q, pts, f"Q{q.number:03d}", shuffle, cardinality))
    body += ["  </objectbank>", "</questestinterop>"]
    return "\n".join(body)


MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST_1"
          xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
          xmlns:imsmd="http://www.imsglobal.org/xsd/imsmd_v1p2"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <organizations/>
  <resources>
    <resource identifier="RES_1" type="imsqti_xmlv1p2" href="{filename}">
      <file href="{filename}"/>
    </resource>
  </resources>
</manifest>
"""


def write_zip(zip_path: str, xml: str, xml_name: str = "questions.xml",
              manifest: bool = True) -> None:
    os.makedirs(os.path.dirname(zip_path) or ".", exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, xml)
        if manifest:
            zf.writestr("imsmanifest.xml", MANIFEST.format(filename=xml_name))
    with open(zip_path, "wb") as f:
        f.write(buf.getvalue())
