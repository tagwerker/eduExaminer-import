"""Punktevergabe.

Pro Antwortoption gibt es VIER Faelle, weil das EXZ je Antwort zwei
respconditions kennt (angekreuzt / nicht angekreuzt):

                    angekreuzt        nicht angekreuzt
    richtige Antw.  correct           correct_unticked
    falsche Antw.   wrong             wrong_unticked

Zwei Schemata:

"balanced" (Standard) - nur das Ankreuzen wird bewertet:

    correct          = + TOTAL / k
    wrong            = - TOTAL / (n - k)
    correct_unticked = 0
    wrong_unticked   = 0

    Maximum TOTAL, Erwartungswert beim Raten 0.
    n=4, k=1 -> +4 / -1,333    k=2 -> +2 / -2    k=3 -> +1,333 / -4

"symmetric" - jede der n Optionen ist ein eigenes Ja/Nein-Urteil:

    correct = wrong_unticked = + PLUS      (Urteil richtig)
    wrong   = correct_unticked = - MINUS   (Urteil falsch)

    Maximum  n * PLUS,  Minimum  -n * MINUS - beides unabhaengig von k.
    n=4, PLUS=1, MINUS=0,5 -> Maximum +4, Minimum -2.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

DEFAULT_TOTAL = 4.0
DEFAULT_DECIMALS = 3
DEFAULT_ESSAY_POINTS = 4.0
SCHEMES = ("balanced", "symmetric")


@dataclass
class Points:
    kind: str                  # "choice" | "essay"
    correct: Decimal           # richtige Antwort angekreuzt
    wrong: Decimal             # falsche Antwort angekreuzt
    correct_unticked: Decimal  # richtige Antwort NICHT angekreuzt
    wrong_unticked: Decimal    # falsche Antwort NICHT angekreuzt
    total: Decimal
    n_options: int
    n_correct: int

    @property
    def n_wrong(self) -> int:
        return self.n_options - self.n_correct

    @property
    def max_score(self) -> Decimal:
        """Beste Antwort. Bei Essay-Fragen die volle Punktzahl."""
        if self.kind == "essay":
            return self.total
        return self.correct * self.n_correct + self.wrong_unticked * self.n_wrong

    @property
    def min_score(self) -> Decimal:
        """Schlechteste Antwort. Bei Essay-Fragen 0."""
        if self.kind == "essay":
            return Decimal(0)
        return self.correct_unticked * self.n_correct + self.wrong * self.n_wrong

    @property
    def blank_score(self) -> Decimal:
        """Nichts angekreuzt bzw. nichts geschrieben."""
        if self.kind == "essay":
            return Decimal(0)
        return (self.correct_unticked * self.n_correct
                + self.wrong_unticked * self.n_wrong)

    @property
    def guess_score(self) -> Decimal:
        """Erwartungswert, wenn jede Option mit 50 % angekreuzt wird."""
        if self.kind == "essay":
            return Decimal(0)
        half = Decimal("0.5")
        per_correct = half * (self.correct + self.correct_unticked)
        per_wrong = half * (self.wrong + self.wrong_unticked)
        return per_correct * self.n_correct + per_wrong * self.n_wrong


def _round(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def compute(
    n_options: int,
    n_correct: int,
    total: float = DEFAULT_TOTAL,
    decimals: int = DEFAULT_DECIMALS,
    scheme: str = "balanced",
    plus: float | None = None,
    minus: float | None = None,
) -> Points:
    """Punkte fuer eine Frage mit n_options Optionen, davon n_correct richtig.

    scheme "symmetric": plus/minus je Einzelurteil. Ohne Angabe gilt
    plus = total / n_options und minus = plus / 2 - bei total=4 und n=4
    also +1 / -0,5 und damit Maximum +4, Minimum -2.
    """
    if scheme not in SCHEMES:
        raise ValueError(f"unbekanntes Schema '{scheme}', erlaubt: {SCHEMES}")

    tot = Decimal(str(total))
    n_wrong = n_options - n_correct
    zero = Decimal(0)

    if scheme == "symmetric":
        p = Decimal(str(plus)) if plus is not None else tot / Decimal(n_options)
        q = (Decimal(str(minus)) if minus is not None
             else p / Decimal(2))
        return Points(
            kind="choice",
            correct=_round(p, decimals),
            wrong=_round(-q, decimals),
            correct_unticked=_round(-q, decimals),
            wrong_unticked=_round(p, decimals),
            total=tot,
            n_options=n_options,
            n_correct=n_correct,
        )

    # balanced
    if n_correct <= 0:
        pos = zero
        neg = -tot / Decimal(n_options) if n_options else zero
    elif n_wrong <= 0:
        pos = tot / Decimal(n_correct)
        neg = zero
    else:
        pos = tot / Decimal(n_correct)
        neg = -tot / Decimal(n_wrong)

    return Points(
        kind="choice",
        correct=_round(pos, decimals),
        wrong=_round(neg, decimals),
        correct_unticked=zero,
        wrong_unticked=zero,
        total=tot,
        n_options=n_options,
        n_correct=n_correct,
    )


def compute_essay(
    points: float = DEFAULT_ESSAY_POINTS,
    decimals: int = DEFAULT_DECIMALS,
) -> Points:
    """Offene Frage: feste Punktzahl, die Korrektur erfolgt per Hand."""
    total = Decimal(str(points))
    zero = Decimal(0)
    return Points(
        kind="essay",
        correct=_round(total, decimals),
        wrong=zero,
        correct_unticked=zero,
        wrong_unticked=zero,
        total=total,
        n_options=0,
        n_correct=0,
    )


def fmt(value: Decimal) -> str:
    """'4' statt '4.000', aber '1.333' bleibt '1.333'."""
    text = format(Decimal(value).normalize(), "f")
    return "0" if text in ("-0", "-0.0") else text
