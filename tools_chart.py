"""Punkteverlauf je Frage zeichnen - Basis 4 Punkte, Schema "balanced".

    python tools_chart.py [ausgabe.png] [--total 4]
                          [--mit-negativ] [--ohne-vergleich]

Standard: keine Negativpunkte, Punktzahl je Frage bei 0 gekappt
(entspricht allowNegativeOutcome = 0 in eduExaminer).

Wichtig: beim Schema "balanced" haengt die Punktzahl nicht nur davon ab, WIE
VIELE Optionen falsch beurteilt wurden, sondern auch WELCHE ART Fehler es war.
Eine richtige Antwort nicht anzukreuzen kostet etwas anderes, als eine falsche
anzukreuzen. Darum ein Band statt einer Linie - ausser bei 2 richtigen, wo
beide Fehlerarten gleich viel kosten.

Nur k = 1, 2, 3 - Fragen mit 0 oder 4 richtigen Antworten kommen nicht vor.
"""
from __future__ import annotations

import sys
from itertools import product

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from exz.scoring import compute

N_OPTIONS = 4
BLUE, RED, GREY = "#1f77b4", "#d62728", "#6f6f6f"


def de(value: float, decimals: int = 3) -> str:
    """Deutsche Schreibweise: 1,333 statt 1.333, ohne Nullen am Ende."""
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") or "0"


def band(k: int, total: float, decimals: int = 3):
    """Min/Max erreichbare Punkte je Anzahl falsch beurteilter Optionen."""
    p = compute(N_OPTIONS, k, total=total, decimals=decimals)
    truth = [True] * k + [False] * (N_OPTIONS - k)
    out: dict[int, tuple[float, float]] = {}
    for ticks in product([False, True], repeat=N_OPTIONS):
        score = float(sum(
            (p.correct if t else p.correct_unticked) if truth[i]
            else (p.wrong if t else p.wrong_unticked)
            for i, t in enumerate(ticks)
        ))
        errors = sum(1 for i, t in enumerate(ticks) if t != truth[i])
        lo, hi = out.get(errors, (score, score))
        out[errors] = (min(lo, score), max(hi, score))
    xs = sorted(out)
    return xs, [out[e][0] for e in xs], [out[e][1] for e in xs]


def tcexam(total: float):
    """Altes System: +1 je richtigem Urteil, -0,5 je falschem."""
    plus = total / N_OPTIONS
    minus = plus / 2
    xs = list(range(N_OPTIONS + 1))
    return xs, [total - e * (plus + minus) for e in xs]


def draw(ax, total: float, cap: bool, vergleich: bool) -> None:
    """cap=True: Punktzahl je Frage bei 0 gekappt, keine Negativpunkte."""
    clip = (lambda v: max(0.0, v)) if cap else (lambda v: v)

    xs, lo1, hi1 = band(1, total)
    _, lo3, hi3 = band(3, total)
    lo = [clip(min(a, b)) for a, b in zip(lo1, lo3)]
    hi = [clip(max(a, b)) for a, b in zip(hi1, hi3)]
    _, lo2, _ = band(2, total)
    line2 = [clip(v) for v in lo2]

    ax.fill_between(xs, lo, hi, color=BLUE, alpha=0.15, lw=0,
                    label="1 oder 3 richtige: möglicher Bereich")
    ax.plot(xs, hi, color=BLUE, lw=2.2, marker="^", ms=7,
            label=f"1 oder 3 richtige, günstigster Fehler "
                  f"(−{de(total / 3)} je Fehler)")
    ax.plot(xs, lo, color=BLUE, lw=2.2, marker="v", ms=7, ls=":",
            label=f"1 oder 3 richtige, teuerster Fehler "
                  f"(−{de(total)} je Fehler)")
    ax.plot(xs, line2, color=RED, lw=2.4, marker="o", ms=7,
            label=f"2 richtige: −{de(total / 2)} je Fehler (eindeutig)")

    floor = 0.0
    if vergleich:
        xt, yt = tcexam(total)
        ax.plot(xt, yt, color=GREY, lw=2, ls="--", marker="s", ms=6.5,
                label=f"altes System: +{de(total / N_OPTIONS)} / "
                      f"−{de(total / N_OPTIONS / 2)} je Option, mit Negativ")
        floor = min(floor, min(yt))
    floor = min(floor, min(lo))

    ax.axhline(0, color="black", lw=1)
    ax.set_xlabel("falsch beurteilte Antwortoptionen")
    ax.set_ylabel("Punkte")
    ax.set_xticks(range(N_OPTIONS + 1))
    ax.set_yticks([y * total / 4 for y in range(-4, 5)])
    ax.set_ylim(floor - total * 0.14, total * 1.12)
    ax.grid(alpha=0.3)


def main(argv):
    out_path = "output/punkteverlauf_4punkte.png"
    total = 4.0
    cap = "--mit-negativ" not in argv
    vergleich = "--ohne-vergleich" not in argv

    positional = [a for a in argv if not a.startswith("--")]
    if "--total" in argv:
        idx = argv.index("--total") + 1
        total = float(argv[idx])
        positional = [a for a in positional if a != argv[idx]]
    if positional:
        out_path = positional[0]

    fig, ax = plt.subplots(figsize=(11.2, 6.4))
    draw(ax, total, cap=cap, vergleich=vergleich)

    modus = ("ohne Negativpunkte, Frage bei 0 gekappt" if cap
             else "mit Negativpunkten")
    ax.set_title(
        f"Punkteverlauf je Frage · Basis {de(total)} Punkte · {modus}\n"
        f"1 richtige: +{de(total)} / −{de(total / 3)}      "
        f"2 richtige: +{de(total / 2)} / −{de(total / 2)}      "
        f"3 richtige: +{de(total / 3)} / −{de(total)}",
        fontsize=12)
    ax.legend(loc="upper right", fontsize=9.5)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"geschrieben: {out_path}")

    xs, lo1, hi1 = band(1, total)
    _, lo3, hi3 = band(3, total)
    _, lo2, _ = band(2, total)
    _, yt = tcexam(total)
    clip = (lambda v: max(0.0, v)) if cap else (lambda v: v)
    head = (f"{'Fehler':>6} | {'1 oder 3 richtige':>19} | {'2 richtige':>10}"
            + (f" | {'altes System':>12}" if vergleich else ""))
    print()
    print(head)
    for i, e in enumerate(xs):
        low, high = clip(min(lo1[i], lo3[i])), clip(max(hi1[i], hi3[i]))
        rng = de(low) if abs(high - low) < 1e-9 else f"{de(low)} .. {de(high)}"
        row = f"{e:>6} | {rng:>19} | {de(clip(lo2[i])):>10}"
        if vergleich:
            row += f" | {de(yt[i]):>12}"
        print(row)


if __name__ == "__main__":
    main(sys.argv[1:])
