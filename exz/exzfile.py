"""Lesen/Schreiben des EXZ-Containers + Base64-Feld-Helfer.

Die Mail spricht von einem ZIP-Archiv, das Notebook von rohem zlib.
Wir erkennen das Format automatisch und schreiben in demselben Format
zurueck, damit eduExaminer die Datei wieder frisst.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import io
import json
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Container:
    """Merkt sich, WIE die Datei verpackt war, damit write() das spiegelt."""
    kind: str                      # "zlib" | "gzip" | "zip" | "raw"
    member: str | None = None      # Dateiname im ZIP
    extras: dict[str, bytes] = field(default_factory=dict)  # weitere ZIP-Member
    wbits: int = zlib.MAX_WBITS
    level: int = 6


def _looks_like_json(raw: bytes) -> bool:
    return raw.lstrip()[:1] in (b"{", b"[")


def read_exz(path: str) -> tuple[Any, Container]:
    """Gibt (geparstes JSON, Container-Info) zurueck."""
    with open(path, "rb") as f:
        return loads_exz(f.read())


def loads_exz(blob: bytes) -> tuple[Any, Container]:
    """Wie read_exz, aber aus dem Speicher - fuer Uploads ohne Datei."""
    # 1) ZIP?
    if blob[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(blob))
        names = zf.namelist()
        main = next((n for n in names if n.lower().endswith(".json")), None) or names[0]
        extras = {n: zf.read(n) for n in names if n != main}
        return json.loads(zf.read(main).decode("utf-8")), Container("zip", main, extras)

    # 2) gzip?
    if blob[:2] == b"\x1f\x8b":
        return json.loads(gzip.decompress(blob).decode("utf-8")), Container("gzip")

    # 3) rohes zlib (so macht es das Notebook) - mit und ohne Header
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            raw = zlib.decompress(blob, wbits)
        except zlib.error:
            continue
        return json.loads(raw.decode("utf-8")), Container("zlib", wbits=wbits)

    # 4) unkomprimiertes JSON
    if _looks_like_json(blob):
        return json.loads(blob.decode("utf-8")), Container("raw")

    raise ValueError(
        f"Unbekanntes EXZ-Format (erste Bytes: {blob[:8]!r}) - "
        f"weder zip/gzip/zlib/json"
    )


def write_exz(path: str, obj: Any, container: Container) -> None:
    with open(path, "wb") as f:
        f.write(dumps_exz(obj, container))


def dumps_exz(obj: Any, container: Container) -> bytes:
    """Wie write_exz, aber als Bytes - fuer Downloads ohne Datei."""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if container.kind == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(container.member or "export.json", payload)
            for name, data in container.extras.items():
                zf.writestr(name, data)
        blob = buf.getvalue()
    elif container.kind == "gzip":
        blob = gzip.compress(payload, container.level)
    elif container.kind == "raw":
        blob = payload
    else:
        co = zlib.compressobj(container.level, zlib.DEFLATED, container.wbits)
        blob = co.compress(payload) + co.flush()

    return blob


# ---------------------------------------------------------------- base64 ----

def b64_decode_text(value: Any) -> str | None:
    """Dekodiert einen Base64-String zu UTF-8-Text, sonst None."""
    if not isinstance(value, str) or len(value) < 16:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def b64_encode_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def walk(node: Any, path: tuple = ()) -> Iterator[tuple[tuple, Any]]:
    """Laeuft rekursiv durch dicts/lists und liefert (pfad, blattwert)."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (i,))
    else:
        yield path, node


def path_str(path: tuple) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out.lstrip(".")


def find_questions(root: Any) -> tuple[Any, list] | tuple[None, None]:
    """Sucht die Fragenliste (Liste von dicts mit 'revisions').

    Das Notebook nutzt root['topics']['questions'] - wir suchen generisch,
    falls der Export anders verschachtelt ist.
    """
    best: tuple[Any, list] | None = None

    def visit(node: Any, parent: Any) -> None:
        nonlocal best
        if isinstance(node, dict):
            for k, v in node.items():
                if (
                    k == "questions"
                    and isinstance(v, list)
                    and v
                    and isinstance(v[0], dict)
                    and "revisions" in v[0]
                    and best is None
                ):
                    best = (node, v)
                visit(v, node)
        elif isinstance(node, list):
            for v in node:
                visit(v, node)

    visit(root, None)
    return best if best else (None, None)
