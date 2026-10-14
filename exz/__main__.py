"""CLI:  python -m exz {inspect|points|qti|build|repack}"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import sys
import uuid

from .api import (
    SCORE_HINTS,
    question_total,
    BuildError,
    BuildOptions,
    build_exz,
    points_for,
    xml_fields as _xml_fields,
)
from .excel import Question, read_questions
from .exzfile import (
    b64_decode_text,
    b64_encode_text,
    find_questions,
    path_str,
    read_exz,
    walk,
    write_exz,
)
from .qti import build_evaluation, build_presentation
from .qtipkg import build_bank, write_zip
from .scoring import (
    DEFAULT_DECIMALS,
    DEFAULT_ESSAY_POINTS,
    DEFAULT_TOTAL,
    SCHEMES,
    compute,
    compute_essay,
    fmt,
)


def _add_scoring_args(parser):
    parser.add_argument("--total", type=float, default=None,
                        help="feste Maximalpunkte je MC-Frage; ohne Angabe "
                             "ein Punkt je Antwortmoeglichkeit")
    parser.add_argument("--decimals", type=int, default=DEFAULT_DECIMALS)
    parser.add_argument("--scheme", choices=list(SCHEMES), default="balanced",
                        help="balanced: nur Ankreuzen zaehlt. "
                             "symmetric: jede Option ist ein eigenes Urteil")
    parser.add_argument("--plus", type=float,
                        help="symmetric: Punkte je richtigem Urteil "
                             "(Standard total/n)")
    parser.add_argument("--minus", type=float,
                        help="symmetric: Abzug je falschem Urteil "
                             "(Standard plus/2)")
    parser.add_argument("--language", default="DE",
                        help="Sprachkennung der Fragen, z.B. DE oder EN")
    parser.add_argument("--essay-points", type=float,
                        default=DEFAULT_ESSAY_POINTS,
                        help="Punkte je offener Frage (Standard "
                             f"{DEFAULT_ESSAY_POINTS:g})")
    return parser


def _opts(args) -> BuildOptions:
    """CLI-Argumente in die Optionen des gemeinsamen Kerns uebersetzen."""
    return BuildOptions(
        total=getattr(args, "total", None),
        essay_points=getattr(args, "essay_points", DEFAULT_ESSAY_POINTS),
        decimals=getattr(args, "decimals", DEFAULT_DECIMALS),
        scheme=getattr(args, "scheme", "balanced"),
        plus=getattr(args, "plus", None),
        minus=getattr(args, "minus", None),
        negative=bool(getattr(args, "negative", False)),
        shuffle=bool(getattr(args, "shuffle", False)),
        title_format=getattr(args, "title_format", "Frage {nr:02d}"),
        presentation_field=getattr(args, "presentation_field", "presentation"),
        score_field=getattr(args, "score_field", None),
        language=(getattr(args, "language", "DE") or "DE").upper(),
    )


def _out(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path


# ------------------------------------------------------------------ inspect --

def cmd_inspect(args):
    data, container = read_exz(args.exz)
    label = f" (Member '{container.member}')" if container.member else ""
    print(f"Container : {container.kind}{label}")

    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "export.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON      : {os.path.join(outdir, 'export.json')}")

    if isinstance(data, dict):
        print(f"Top-Level : {list(data.keys())}")

    _, questions = find_questions(data)
    if questions is None:
        print("\n!! Keine Fragenliste (dict mit 'revisions') gefunden.")
    else:
        print(f"\nFragen    : {len(questions)}")
        revs = questions[0].get("revisions") or [{}]
        rev0 = revs[0] if isinstance(revs, list) and revs else {}
        print(f"Frage-Felder   : {list(questions[0].keys())}")
        print(f"Revision-Felder: {list(rev0.keys())}")
        fields = _xml_fields(rev0)
        print("\nBase64-XML-Felder in revisions[0]:")
        for key, (tag, xml) in fields.items():
            low = xml.lower()
            hit = any(h in low or h in key.lower() for h in SCORE_HINTS)
            marker = "  <-- BEWERTUNG?" if hit else ""
            print(f"  {key:<24} root=<{tag}>  {len(xml):>6} Zeichen{marker}")
            target = _out(os.path.join(outdir, "xml", f"q0.{key}.xml"))
            with open(target, "w", encoding="utf-8") as f:
                f.write(xml)
        print(f"\nXML-Dumps : {os.path.join(outdir, 'xml')}")

    print("\nAlle Base64-XML-Felder im Export (Pfad -> Anzahl):")
    seen = {}
    for path, value in walk(data):
        text = b64_decode_text(value)
        if not text or not text.lstrip().startswith("<"):
            continue
        generic = re.sub(r"\[\d+\]", "[*]", path_str(path))
        seen[generic] = seen.get(generic, 0) + 1
    for path, count in sorted(seen.items()):
        print(f"  {path}  ({count}x)")
    return 0


# ------------------------------------------------------------------- points --

def cmd_points(args):
    questions, warnings, layout = read_questions(args.xlsx, args.sheet)
    for w in warnings:
        print(f"WARNUNG  {w}", file=sys.stderr)

    print(f"Layout: {layout.describe()}")
    print(f"Schema: {args.scheme}   offene Fragen: {args.essay_points:g} Punkte")
    print(f"{'Nr':>3} {'Typ':<5} {'n':>2} {'k':>2} | {'+kreuz':>7} {'-kreuz':>7} "
          f"{'+leer':>7} {'-leer':>7} | {'max':>6} {'min':>6} {'leer':>6} "
          f"{'raten':>6} | Frage")

    rows = []
    for q in questions:
        p = points_for(q, _opts(args))
        rows.append({
            "nr": q.number,
            "zeile": q.row,
            "typ": q.qtype,
            "optionen": q.n_options,
            "richtige": q.n_correct,
            "richtig_angekreuzt": fmt(p.correct),
            "falsch_angekreuzt": fmt(p.wrong),
            "richtig_nicht_angekreuzt": fmt(p.correct_unticked),
            "falsch_nicht_angekreuzt": fmt(p.wrong_unticked),
            "maximum": fmt(p.max_score),
            "minimum": fmt(p.min_score),
            "leer_abgegeben": fmt(p.blank_score),
            "erwartung_raten": fmt(p.guess_score),
            "frage": q.text,
        })
        label = "MC" if q.qtype == "multiple" else "offen"
        if q.qtype == "multiple":
            detail = (f"{fmt(p.correct):>7} {fmt(p.wrong):>7} "
                      f"{fmt(p.correct_unticked):>7} {fmt(p.wrong_unticked):>7} | "
                      f"{fmt(p.max_score):>6} {fmt(p.min_score):>6} "
                      f"{fmt(p.blank_score):>6} {fmt(p.guess_score):>6}")
            size = f"{q.n_options:>2} {q.n_correct:>2}"
        else:
            detail = (f"{'':>7} {'':>7} {'':>7} {'':>7} | "
                      f"{fmt(p.max_score):>6} {'':>6} {'':>6} {'':>6}")
            size = f"{'-':>2} {'-':>2}"
        print(f"{q.number:>3} {label:<5} {size} | {detail} | {q.text[:34]}")

    if rows:
        counts = {}
        for r in rows:
            counts[r["typ"]] = counts.get(r["typ"], 0) + 1
        print(f"\nueber alle {len(rows)} Fragen: "
              + ", ".join(f"{n}x {t}" for t, n in sorted(counts.items())))
        mc = [r for r in rows if r["typ"] == "multiple"]
        essay = [r for r in rows if r["typ"] != "multiple"]
        uniq = lambda src, key: sorted({r[key] for r in src}, key=float)
        if mc:
            print(f"  Multiple Choice  max {uniq(mc, 'maximum')}  "
                  f"min {uniq(mc, 'minimum')}  "
                  f"leer {uniq(mc, 'leer_abgegeben')}  "
                  f"raten {uniq(mc, 'erwartung_raten')}")
        if essay:
            print(f"  offene Fragen    max {uniq(essay, 'maximum')} "
                  f"(Korrektur per Hand)")

    if args.csv and rows:
        with open(_out(args.csv), "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV: {args.csv}")
    return 0


# -------------------------------------------------------------------- build --

def cmd_build(args):
    verbose = not getattr(args, "quiet", False)

    def say(*a, **kw):
        if verbose:
            print(*a, **kw)

    opts = _opts(args)
    questions, warnings, layout = read_questions(args.xlsx, args.sheet)
    for w in warnings:
        print(f"WARNUNG  {w}", file=sys.stderr)

    counts = {}
    for q in questions:
        counts[q.qtype] = counts.get(q.qtype, 0) + 1
    names = {"multiple": "Multiple Choice", "essay": "offene Fragen"}
    summary = ", ".join(f"{n}x {names.get(t, t)}" for t, n in sorted(counts.items()))
    print(f"{len(questions)} Fragen aus {os.path.basename(args.xlsx)}: {summary}")
    if counts.get("multiple"):
        maxima = sorted({question_total(q, opts) for q in questions
                         if q.qtype == "multiple"})
        wie = ("ein Punkt je Antwortmoeglichkeit" if opts.total is None
               else "fest eingestellt")
        print(f"  Multiple Choice : max "
              f"{' / '.join(f'{m:g}' for m in maxima)} Punkte je Frage "
              f"({wie}, Schema {opts.scheme})")
    if counts.get("essay"):
        print(f"  offene Fragen   : {opts.essay_points:g} Punkte je Frage")

    # XML-Einzeldateien zum Nachsehen
    xml_dir = os.path.join(args.outdir, "xml")
    os.makedirs(xml_dir, exist_ok=True)
    for q in questions:
        pts = points_for(q, opts)
        base = os.path.join(xml_dir, f"q{q.number:03d}")
        with open(base + ".presentation.xml", "w", encoding="utf-8") as f:
            f.write(build_presentation(q, shuffle=opts.shuffle))
        with open(base + ".evaluation.xml", "w", encoding="utf-8") as f:
            f.write(build_evaluation(q, pts, allow_negative=opts.negative))
    say(f"XML geschrieben: {xml_dir}  ({2 * len(questions)} Dateien)")

    if not args.template:
        print()
        print("Kein --template angegeben -> nur XML erzeugt, kein EXZ.")
        print("Fuer die EXZ-Datei ein echtes eduExaminer-Export-File als")
        print("Strukturvorlage mitgeben:  --template input/struktur-vorlage.exz")
        return 0

    try:
        result = build_exz(questions, args.template, opts)
    except BuildError as exc:
        print(file=sys.stderr)
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2

    say("Prototypen in der Vorlage: "
        + ", ".join(f"{k} (Typ-ID {v})"
                    for k, v in sorted(result.prototypes.items())))
    say(f"Bewertungsfeld automatisch erkannt: '{result.score_field}'")

    out = _out(args.output)
    with open(out, "wb") as f:
        f.write(result.exz)
    say()
    say(f"EXZ geschrieben: {out}  "
        f"({len(result.exz):,} Bytes, Container={result.container})")

    check, _ = read_exz(out)
    _, checked = find_questions(check)
    say(f"Rueckleseprobe : {len(checked)} Fragen, "
        f"Felder={list(checked[0]['revisions'][0].keys())}")
    if not verbose:
        print(f"  Kontrolle       : {len(checked)} Fragen in der fertigen Datei")
    return 0


# ---------------------------------------------------------------------- qti --

def cmd_qti(args):
    """QTI-1.2-Paket bauen - der offiziell dokumentierte Importweg."""
    import xml.dom.minidom as minidom

    questions, warnings, layout = read_questions(args.xlsx, args.sheet)
    for w in warnings:
        print(f"WARNUNG  {w}", file=sys.stderr)

    items = []
    for q in questions:
        p = points_for(q, _opts(args))
        card = args.cardinality
        if card == "auto":
            card = "Single" if q.n_correct == 1 else "Multiple"
        items.append((q, p, card))

    xml = build_bank(items, bank_title=args.title, shuffle=args.shuffle)

    out_xml = _out(args.output)
    with open(out_xml, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"QTI 1.2 XML : {out_xml}  ({len(questions)} Fragen, "
          f"{os.path.getsize(out_xml):,} Bytes)")

    if args.zip:
        write_zip(args.zip, xml, os.path.basename(out_xml),
                  manifest=not args.no_manifest)
        print(f"ZIP-Paket   : {args.zip}  ({os.path.getsize(args.zip):,} Bytes)")

    # DOCTYPE fuer den Syntaxcheck entfernen (externe DTD wird nicht geladen)
    body = "\n".join(ln for ln in xml.splitlines() if not ln.startswith("<!DOCTYPE"))
    try:
        minidom.parseString(body)
    except Exception as exc:  # noqa: BLE001
        print(f"XML-Syntax  : FEHLER {exc}", file=sys.stderr)
        return 1
    print("XML-Syntax  : ok")
    return 0


# ------------------------------------------------------------------ rescore --

def cmd_rescore(args):
    """Punkte in einem bestehenden EXZ neu setzen - ohne das XML neu zu bauen."""
    from .rescore import rescore_resprocessing

    data, container = read_exz(args.exz)
    _, qlist = find_questions(data)
    if qlist is None:
        print("FEHLER: keine Fragenliste gefunden.", file=sys.stderr)
        return 2

    field = args.score_field
    print(f"{len(qlist)} Fragen, Feld '{field}', Zielpunkte {args.total:g} "
          f"({args.decimals} Nachkommastellen)\n")
    print(f"{'Nr':>3} {'Titel':<12} {'k':>2} | {'vorher':>14} | {'nachher':>16}")

    touched = skipped = 0
    for i, question in enumerate(qlist, start=1):
        for rev in question.get("revisions", []):
            raw = rev.get(field)
            xml = b64_decode_text(raw) if raw else None
            if not xml:
                skipped += 1
                continue
            res = rescore_resprocessing(xml, args.total, args.decimals,
                                        allow_negative=args.negative)
            if res is None:
                skipped += 1
                print(f"{i:>3} {str(question.get('title', ''))[:12]:<12} "
                      f"?? | nicht deutbar - uebersprungen")
                continue
            rev[field] = b64_encode_text(res.xml)
            touched += 1
            mark = "" if res.changed else "   (unveraendert)"
            print(f"{i:>3} {str(question.get('title', ''))[:12]:<12} "
                  f"{res.n_correct:>2} | "
                  f"{res.old_correct:>6} / {res.old_wrong:>5} | "
                  f"{res.new_correct:>7} / {res.new_wrong:>6}{mark}")

    if skipped:
        print(f"\n{skipped} Revision(en) uebersprungen.")

    out = _out(args.output)
    write_exz(out, data, container)
    print(f"\n{touched} Bewertungen neu gesetzt.")
    print(f"EXZ geschrieben: {out}  "
          f"({os.path.getsize(out):,} Bytes, Container={container.kind})")

    check, _ = read_exz(out)
    _, checked = find_questions(check)
    print(f"Rueckleseprobe : {len(checked)} Fragen ok")
    return 0


# ------------------------------------------------------------------- repack --

def cmd_repack(args):
    """Round-Trip-Test: entpacken und unveraendert neu packen."""
    data, container = read_exz(args.exz)
    write_exz(_out(args.output), data, container)
    again, _ = read_exz(args.output)
    same = again == data
    print("Inhalt identisch:", same)
    return 0 if same else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m exz", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="EXZ auspacken und Struktur zeigen")
    p.add_argument("exz")
    p.add_argument("-o", "--outdir", default="output/inspect")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("points", help="Punkte je Frage vorrechnen")
    p.add_argument("xlsx")
    p.add_argument("--sheet")
    p.add_argument("--csv")
    _add_scoring_args(p)
    p.set_defaults(func=cmd_points)

    p = sub.add_parser("build", help="XLSX -> XML (+ EXZ, wenn --template)")
    p.add_argument("xlsx")
    p.add_argument("--sheet")
    p.add_argument("--template", help="echtes eduExaminer-EXZ als Strukturvorlage")
    p.add_argument("-o", "--output", default="output/import.exz")
    p.add_argument("--outdir", default="output")
    p.add_argument("--shuffle", action="store_true")
    _add_scoring_args(p)
    p.add_argument("--presentation-field", default="presentation")
    p.add_argument("--score-field",
                   help="Feldname der Bewertung (sonst Autoerkennung)")
    p.add_argument("--title-format", default="Frage {nr:02d}",
                   help="Fragentitel; {nr} = Nummer, {text} = Fragetext")
    p.add_argument("--negative", action="store_true",
                   help="allowNegativeOutcome=1: Frage darf unter 0 Punkte fallen")
    p.add_argument("--quiet", action="store_true",
                   help="nur das Wesentliche ausgeben")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("qti", help="QTI-1.2-Paket bauen (offizieller Importweg)")
    p.add_argument("xlsx")
    p.add_argument("--sheet")
    p.add_argument("-o", "--output", default="output/qti/questions.xml")
    p.add_argument("--zip", default="output/qti_import.zip",
                   help="zusaetzlich als ZIP packen (leer = kein ZIP)")
    p.add_argument("--no-manifest", action="store_true",
                   help="ZIP ohne imsmanifest.xml")
    p.add_argument("--title", default="Fragenpool")
    p.add_argument("--shuffle", action="store_true")
    _add_scoring_args(p)
    p.add_argument("--cardinality", default="Multiple",
                   choices=["Multiple", "Single", "auto"],
                   help="auto = Single bei genau einer richtigen Antwort")
    p.set_defaults(func=cmd_qti)

    p = sub.add_parser("rescore",
                       help="Punkte in einem bestehenden EXZ neu setzen")
    p.add_argument("exz")
    p.add_argument("-o", "--output", default="output/rescored.exz")
    p.add_argument("--total", type=float, default=DEFAULT_TOTAL)
    p.add_argument("--decimals", type=int, default=DEFAULT_DECIMALS)
    p.add_argument("--score-field", default="resprocessing")
    p.add_argument("--negative", choices=["keep", "yes", "no"], default="keep",
                   help="allowNegativeOutcome: unveraendert lassen / 1 / 0")
    p.set_defaults(func=cmd_rescore)

    p = sub.add_parser("repack", help="Round-Trip-Test eines EXZ")
    p.add_argument("exz")
    p.add_argument("-o", "--output", default="output/repacked.exz")
    p.set_defaults(func=cmd_repack)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
