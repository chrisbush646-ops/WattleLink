import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "extract_metadata.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def extract_metadata_from_text(text: str) -> dict:
    """
    Use Claude to extract bibliographic metadata from the first part of a PDF's text.
    Returns a dict with keys matching the Paper model fields.
    Falls back to empty/null values on any error.
    """
    import anthropic
    from django.conf import settings

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping metadata extraction")
        return {}

    # First 3 000 chars of the PDF text is almost always enough to find the header/front matter
    snippet = text[:3000].strip()
    if not snippet:
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            system=_load_prompt(),
            messages=[{"role": "user", "content": snippet}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.error("Metadata extraction failed: %s", exc)
        return {}

    # Coerce published_date string → date object
    pub_date = None
    raw_date = (data.get("published_date") or "").strip()
    if raw_date:
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                from datetime import datetime
                pub_date = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue

    authors = data.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(";") if a.strip()]

    return {
        "title":        (data.get("title") or "").strip() or None,
        "authors":      authors,
        "journal":      (data.get("journal") or "").strip(),
        "journal_short":(data.get("journal_short") or "").strip(),
        "published_date": pub_date,
        "volume":       (data.get("volume") or "").strip(),
        "issue":        (data.get("issue") or "").strip(),
        "pages":        (data.get("pages") or "").strip(),
        "pmcid":        (data.get("pmcid") or "").strip(),
        "pubmed_id":    (data.get("pubmed_id") or "").strip(),
        "study_type":   (data.get("study_type") or "Other").strip(),
    }
