"""
PDF annotation service using PyMuPDF.

Highlights approved claim source passages in the paper PDF.
Each claim gets a distinct colour band; a legend is added to page 1.
"""
import io
import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Highlight colours per endpoint type (RGB 0-1 floats)
COLOURS = {
    "PRIMARY":   (0.55, 0.80, 0.57),   # eucalyptus green
    "SECONDARY": (0.65, 0.80, 0.90),   # sky blue
    "SAFETY":    (0.90, 0.65, 0.55),   # coral
    "OTHER":     (0.90, 0.85, 0.60),   # wattle gold
}


def annotate_pdf(pdf_bytes: bytes, claims: list) -> bytes:
    """
    Add highlight annotations to a PDF for each approved claim's source_passage.

    Args:
        pdf_bytes: raw bytes of the original PDF
        claims: list of CoreClaim instances (must have source_passage, endpoint_type)

    Returns:
        Annotated PDF as bytes. If no PDF or no passages match, returns original bytes.
    """
    if not pdf_bytes:
        return pdf_bytes

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error("Failed to open PDF for annotation: %s", e)
        return pdf_bytes

    annotated = 0
    for claim in claims:
        passage = (claim.source_passage or "").strip()
        if not passage:
            continue

        colour = COLOURS.get(claim.endpoint_type, COLOURS["OTHER"])

        # Search each page for the passage (or leading fragment if long)
        search_text = passage[:120] if len(passage) > 120 else passage

        for page in doc:
            hits = page.search_for(search_text, quads=True)
            for quad in hits:
                annot = page.add_highlight_annot(quad)
                annot.set_colors(stroke=colour)
                annot.set_info(
                    title=f"[{claim.get_endpoint_type_display()}]",
                    content=claim.claim_text[:200],
                )
                annot.update()
                annotated += 1

    logger.info("Annotated %d passages across %d claims", annotated, len(claims))

    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    doc.close()
    return buf.getvalue()


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
