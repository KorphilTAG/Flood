"""Draft an AAR source manifest from the PDFs already sitting in a sources directory.

This is a curator aid, not an ingestion step. It fills in only what can be derived
mechanically from the files themselves -- SHA-256, page count, the title the document
prints on its own first page -- and leaves every provenance and attestation field
blank for a human.

It never sets `status: "verified"`, never writes `verified_by`, and never guesses a
`canonical_url`. Those are the fields the corpus gate exists to protect
(`aar/manifest.py`): a document enters a citation-grounded corpus only because a person
confirmed where it came from and that the checksum matches what they downloaded.

    python -m scripts.draft_aar_manifest --sources data/aar/sources \
        --output ingestion/aar/sources/manifest.draft.json

Then a curator fills the blanks, sets each entry's status to "verified", and runs:

    python -m aar validate --manifest <path>
    python -m aar build --manifest <path> --output data/aar/library
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

# The categories aar/models.py requires. A draft entry is only auto-assigned a category
# when the document's own text makes the match unambiguous; otherwise the curator picks.
CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    (r"hazard\s+mitigation\s+action\s+plan", "kerr_hmp_2024"),
    (r"emergency\s+operations\s+plan", "kerr_eop"),
    (r"service\s+assessment", "nws_service_assessment"),
    (r"(senate|house)\s+(committee|select)|senator\s+[\w.'-]+(?:\s+[\w.'-]+)*,\s*(vice\s+)?chair",
     "tx_house_senate_committee"),
    (r"u\.?s\.?\s*geological\s+survey.*(post-?flood|flood\s+of)", "usgs_post_flood_report"),
    (r"ipaws", "fema_ipaws_records"),
    (r"wimberley", "wimberley_2015_aar"),
    (r"houston", "houston_2016_aar"),
    (r"llano", "llano_2018_aar"),
)

TODO = ""  # left empty on purpose: a blank field fails validation until a human fills it


def _first_page_text(path: Path) -> tuple[str, int, str | None]:
    """Return (first-page text, page count, error). Never raises on a bad PDF."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = " ".join((reader.pages[0].extract_text() or "").split())
        return text, len(reader.pages), None
    except Exception as exc:  # encrypted, corrupt, or image-only
        return "", 0, f"{type(exc).__name__}: {exc}"


def _guess_category(text: str) -> str:
    lowered = text.lower()
    for pattern, category in CATEGORY_HINTS:
        if re.search(pattern, lowered):
            return category
    return TODO


def _guess_title(text: str) -> str:
    """The document's own printed title: the first sentence-ish run of its first page."""
    if not text:
        return TODO
    head = re.split(r"(?<=[a-z])\.\s|\s{2,}|\"", text.strip())[0]
    return head[:120].strip()


def _document_id(path: Path, category: str) -> str:
    stem = category or path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug[:36] or "unnamed-source"


def build_draft(sources_dir: Path) -> dict:
    documents = []
    for pdf in sorted(sources_dir.glob("*.pdf")):
        text, pages, error = _first_page_text(pdf)
        category = _guess_category(text)
        entry = {
            "document_id": _document_id(pdf, category),
            "source_category": category,
            "title": _guess_title(text),
            "publisher": TODO,
            "canonical_url": TODO,
            "local_pdf_path": str(Path("../../../") / pdf.as_posix()),
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "status": "pending",
            "verified_by": TODO,
            "verified_at": TODO,
            "verification_note": TODO,
            "annotations": [],
            "_draft_notes": {
                "file": pdf.name,
                "pages": pages,
                "curator_must_fill": [
                    "publisher", "canonical_url", "verified_by", "verified_at",
                    "verification_note", "status -> verified",
                ] + ([] if category else ["source_category"]),
            },
        }
        if error:
            entry["_draft_notes"]["unreadable"] = error
        documents.append(entry)
    return {"schema_version": "1.0", "documents": documents}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", default="data/aar/sources")
    parser.add_argument("--output", default="ingestion/aar/sources/manifest.draft.json")
    args = parser.parse_args(argv)

    sources = Path(args.sources)
    if not sources.is_dir():
        print(f"Error: sources directory not found: {sources}")
        return 2
    draft = build_draft(sources)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out} with {len(draft['documents'])} entr(y|ies).")
    print("\nEvery entry is status='pending' and will FAIL `python -m aar validate` until a")
    print("curator supplies provenance and sets status='verified'. That gate is deliberate.")
    for doc in draft["documents"]:
        notes = doc["_draft_notes"]
        flag = "  UNREADABLE" if "unreadable" in notes else ""
        print(f"  - {notes['file']}{flag}")
        print(f"      category: {doc['source_category'] or '<curator must choose>'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
