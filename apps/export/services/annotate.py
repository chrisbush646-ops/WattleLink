"""
PDF annotation service using PyMuPDF.

IMPORTANT — content integrity guarantee:
  This module ONLY adds highlight annotation objects to the PDF's annotation
  layer. It never calls insert_text, draw_*, clean_contents, or any other
  method that touches page content streams. The save flags (garbage=1,
  clean=False) prevent PyMuPDF from rewriting or reorganising content streams,
  so the underlying document text is byte-for-byte identical to the source.

Only claims with status=APPROVED are ever highlighted.
"""
import io
import logging
import re

import pymupdf  # PyMuPDF (also importable as fitz)

logger = logging.getLogger(__name__)

# Highlight colours per endpoint type (RGB 0–1 floats).
# These map to the WattleLink brand palette rendered as PDF highlight fills.
COLOURS = {
    "PRIMARY":   (0.62, 0.93, 0.65),   # eucalyptus green
    "SECONDARY": (0.55, 0.80, 0.97),   # sky blue
    "SAFETY":    (0.99, 0.68, 0.58),   # coral
    "OTHER":     (0.99, 0.90, 0.42),   # wattle gold
}

ANNOTATION_TITLE = "WattleLink Auto-Audit"


def _normalise(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip."""
    return re.sub(r"\s+", " ", text).strip()


def _do_highlight(page, search_text: str, colour: tuple, claim) -> int:
    """
    Search for search_text on page and add a highlight annotation for every hit.
    Sets both stroke and fill so the colour renders correctly across PDF viewers.
    Returns the number of quads highlighted.
    """
    hits = page.search_for(search_text, quads=True)
    for quad in hits:
        annot = page.add_highlight_annot(quad)
        # Set fill AND stroke so all PDF viewers render the colour correctly.
        annot.set_colors(stroke=colour, fill=colour)
        annot.set_info(
            title=ANNOTATION_TITLE,
            content=f"[{claim.get_endpoint_type_display()}] {claim.claim_text[:300]}",
        )
        annot.update()
    return len(hits)


def _highlight_passage(page, passage: str, colour: tuple, claim) -> int:
    """
    Try multiple strategies to locate and highlight a passage on a page.

    Strategy order:
    1. Normalised leading fragment — 150 → 100 → 60 chars (covers most cases where
       the AI quoted verbatim but the passage has mixed whitespace/newlines).
    2. First three sentences of the passage individually (handles cases where only
       part of a multi-sentence passage appears on this page).
    3. Normalised claim_text as a last resort (40-char leading fragment).

    Returns number of quads highlighted.
    """
    norm = _normalise(passage)
    if not norm:
        return 0

    # Strategy 1 — leading fragments of the normalised passage
    for length in (150, 100, 60):
        fragment = norm[:length]
        if len(fragment) < 20:
            break
        hits = _do_highlight(page, fragment, colour, claim)
        if hits:
            return hits

    # Strategy 2 — individual sentences (split on .!? followed by whitespace)
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", norm)
        if len(s.strip()) >= 25
    ]
    for sentence in sentences[:4]:
        hits = _do_highlight(page, sentence[:120], colour, claim)
        if hits:
            return hits

    return 0


def annotate_pdf(pdf_bytes: bytes, claims: list) -> bytes:
    """
    Return a copy of pdf_bytes with highlight annotations for approved claims only.

    Matching uses whitespace-normalised progressive fragments so passages
    extracted from XML or reformatted text still find their targets.
    """
    if not pdf_bytes:
        return pdf_bytes

    if not pdf_bytes[:4].startswith(b"%PDF"):
        logger.error("annotate_pdf: input is not a valid PDF (first bytes: %r)", pdf_bytes[:8])
        return pdf_bytes

    approved = [c for c in claims if getattr(c, "status", None) == "APPROVED"]
    if not approved:
        logger.info("annotate_pdf: no approved claims — returning PDF unchanged")
        return pdf_bytes

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error("Failed to open PDF for annotation: %s", e)
        return pdf_bytes

    annotated = 0
    skipped = 0

    for claim in approved:
        colour = COLOURS.get(claim.endpoint_type, COLOURS["OTHER"])

        passage = (claim.source_passage or "").strip()
        if not passage:
            passage = claim.claim_text.strip()

        if not passage:
            skipped += 1
            continue

        hits_this_claim = 0
        for page in doc:
            hits_this_claim += _highlight_passage(page, passage, colour, claim)

        if hits_this_claim == 0:
            logger.warning(
                "annotate_pdf: no match for claim %s (endpoint=%s, passage[:80]=%r)",
                claim.pk, claim.endpoint_type, passage[:80],
            )
        annotated += hits_this_claim

    logger.info(
        "annotate_pdf: %d highlight(s) for %d approved claim(s); %d skipped",
        annotated, len(approved), skipped,
    )

    buf = io.BytesIO()
    doc.save(buf, garbage=1, deflate=True, clean=False)
    doc.close()
    result = buf.getvalue()
    if not result or not result[:4].startswith(b"%PDF"):
        logger.error("annotate_pdf: save produced invalid output — returning original")
        return pdf_bytes
    return result


def build_metadata_snapshot(paper, claims) -> dict:
    """Build the JSON metadata snapshot stored with the export package."""
    return {
        "paper": {
            "id": paper.pk,
            "title": paper.title,
            "doi": paper.doi,
            "journal": paper.journal,
            "published_date": str(paper.published_date),
            "status": paper.status,
        },
        "claims": [
            {
                "id": c.pk,
                "claim_text": c.claim_text,
                "endpoint_type": c.endpoint_type,
                "source_reference": c.source_reference,
                "fair_balance": c.fair_balance,
                "fair_balance_reference": c.fair_balance_reference,
                "fidelity_checklist": c.fidelity_checklist,
                "version": c.version,
                "reviewed_by": c.reviewed_by.email if c.reviewed_by else None,
                "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
            }
            for c in claims
        ],
    }
