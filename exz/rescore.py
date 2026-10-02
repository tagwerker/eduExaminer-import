"""Punkte in einem bestehenden EXZ neu setzen - minimalinvasiv.

Nur die Zahlen in <setvar action="Set">...</setvar> werden ersetzt. Struktur,
Reihenfolge, Whitespace, Feedback-Verweise, IDs und alle uebrigen Felder
bleiben unberuehrt. Das ist deutlich risikoaermer als das XML neu zu bauen.

Welche Antwort richtig ist, wird aus der Datei selbst gelesen: eine Antwort
gilt als richtig, wenn ihr aktueller Punktwert positiv ist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .scoring import compute, fmt

# Ein <respcondition>-Block bis zum schliessenden Tag.
BLOCK_RE = re.compile(r"<respcondition\b.*?</respcondition>", re.S)
NOT_RE = re.compile(r"<conditionvar>\s*<not>")
LETTER_RE = re.compile(r'<varequal\s+respident="[^"]*">\s*([^<\s]+)\s*</varequal>')
SETVAR_RE = re.compile(r'(<setvar\b[^>]*>)(-?[\d.,]+)(</setvar>)')


@dataclass
class Rescored:
    xml: str
    n_options: int
    n_correct: int
    old_correct: str
    old_wrong: str
    new_correct: str
    new_wrong: str
    changed: bool


def _value(block: str) -> float | None:
    m = SETVAR_RE.search(block)
    if not m:
        return None
    try:
        return float(m.group(2).replace(",", "."))
    except ValueError:
        return None


NEG_RE = re.compile(r"(<allowNegativeOutcome>)([01])(</allowNegativeOutcome>)")


def set_allow_negative(xml: str, mode: str) -> str:
    """mode: 'keep' | 'yes' | 'no' - schaltet allowNegativeOutcome um."""
    if mode == "keep":
        return xml
    value = "1" if mode == "yes" else "0"
    return NEG_RE.sub(lambda m: m.group(1) + value + m.group(3), xml)


def rescore_resprocessing(
    xml: str, total: float, decimals: int, allow_negative: str = "keep"
) -> Rescored | None:
    """Setzt die Punkte eines <resprocessing>-XML neu. None, wenn nicht deutbar."""
    blocks = list(BLOCK_RE.finditer(xml))
    if not blocks:
        return None

    # Nur die "angekreuzt"-Bedingungen tragen Punkte.
    ticked = []
    for m in blocks:
        block = m.group(0)
        if NOT_RE.search(block):
            continue
        letter_m = LETTER_RE.search(block)
        value = _value(block)
        if letter_m is None or value is None:
            continue
        ticked.append((m, letter_m.group(1), value))

    if not ticked:
        return None

    n_options = len({letter for _m, letter, _v in ticked})
    n_correct = sum(1 for _m, _l, v in ticked if v > 0)
    pts = compute(n_options, n_correct, total, decimals)
    new_correct, new_wrong = fmt(pts.correct), fmt(pts.wrong)

    old_correct = next((f"{v:g}" for _m, _l, v in ticked if v > 0), "-")
    old_wrong = next((f"{v:g}" for _m, _l, v in ticked if v < 0), "-")

    # Von hinten ersetzen, damit die Offsets gueltig bleiben.
    out = xml
    for m, _letter, value in reversed(ticked):
        block = m.group(0)
        replacement = new_correct if value > 0 else new_wrong
        new_block = SETVAR_RE.sub(
            lambda sm: sm.group(1) + replacement + sm.group(3), block, count=1
        )
        out = out[: m.start()] + new_block + out[m.end():]

    out = set_allow_negative(out, allow_negative)

    return Rescored(
        xml=out,
        n_options=n_options,
        n_correct=n_correct,
        old_correct=old_correct,
        old_wrong=old_wrong,
        new_correct=new_correct,
        new_wrong=new_wrong,
        changed=out != xml,
    )
