import json
import logging
import re
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9a-z]+\b", re.IGNORECASE)


def _strip_doi_patterns(text: str) -> str:
    """Remove any DOI-like strings from AI-generated text to prevent unverified DOIs leaking into stored content."""
    if not text:
        return text
    return _DOI_RE.sub("", text).strip()


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def run_ai_summary(paper) -> dict:
    """
    Call Claude at temperature=0 to produce a structured MSL briefing note.
    Returns the parsed dict on success, raises on unrecoverable error.

    Extended thinking is intentionally not used here — temperature=0 is
    required for factual accuracy and is incompatible with thinking mode.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to summarise.")

    system_prompt = _load_prompt("summarise_paper.md")
    client = anthropic.Anthropic()

    user_message = (
        "Summarise the following paper.\n\n"
        "IMPORTANT: Only use information that appears in the text below. "
        "Do not use any external knowledge. "
        "If information is not present in this text, state 'not reported'.\n\n"
        "--- BEGIN PAPER TEXT ---\n"
        + content
        + "\n--- END PAPER TEXT ---"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        timeout=180,
    )

    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("AI summary JSON parse error: %s\nRaw: %s", e, raw[:500])
        raise


def apply_summary_result(paper_summary, findings_data: list, data: dict) -> list:
    """
    Map AI JSON → PaperSummary fields and return FindingsRow dicts.
    Handles both the new schema (executive_summary, safety_profile) and
    the legacy schema (executive_paragraph, safety_summary) for resilience.
    Modifies paper_summary in-place (does not save).
    Returns list of FindingsRow kwargs for bulk creation.
    """
    raw_methodology = data.get("methodology", {})
    if isinstance(raw_methodology, dict):
        paper_summary.methodology = raw_methodology
    elif isinstance(raw_methodology, str) and raw_methodology.strip():
        paper_summary.methodology = {"study_design": raw_methodology.strip()}
    else:
        paper_summary.methodology = {}

    # New schema uses executive_summary; fall back to legacy key
    paper_summary.executive_paragraph = _strip_doi_patterns(
        data.get("executive_summary") or data.get("executive_paragraph", "")
    )

    # New schema uses safety_profile object; fall back to legacy flat fields
    safety_profile = data.get("safety_profile")
    if isinstance(safety_profile, dict):
        paper_summary.safety_summary = _strip_doi_patterns(safety_profile.get("summary", ""))
        paper_summary.adverse_events = safety_profile.get("serious_adverse_events", [])
    else:
        paper_summary.safety_summary = _strip_doi_patterns(data.get("safety_summary", ""))
        paper_summary.adverse_events = data.get("adverse_events", [])

    # Normalise limitations: new schema uses source_reference, legacy uses page_ref
    raw_limitations = data.get("limitations", [])
    normalised = []
    for lim in raw_limitations:
        if isinstance(lim, dict):
            normalised.append({
                "limitation": lim.get("limitation", ""),
                "page_ref": lim.get("source_reference") or lim.get("page_ref", ""),
            })
        else:
            normalised.append({"limitation": str(lim), "page_ref": ""})
    paper_summary.limitations = normalised

    paper_summary.confidence_flags = data.get("confidence_flags", [])
    paper_summary.ai_prefilled = True

    rows = []
    for i, f in enumerate(findings_data):
        rows.append({
            "category": f.get("category", "Other"),
            "finding": f.get("finding", ""),
            "quantitative_result": f.get("quantitative_result", ""),
            # New schema uses source_reference; legacy uses page_ref
            "page_ref": f.get("source_reference") or f.get("page_ref", ""),
            "clinical_significance": f.get("clinical_significance", ""),
            "order": i,
        })
    return rows
