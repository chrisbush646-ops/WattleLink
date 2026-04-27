import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def run_ai_summary(paper) -> dict:
    """
    Call Claude to produce a structured summary of the given paper.
    Returns the parsed dict on success, raises on unrecoverable error.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to summarise.")

    system_prompt = _load_prompt("summarise_paper.md")
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
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


def apply_summary_result(paper_summary, findings_data: list, data: dict) -> None:
    """
    Map AI JSON → PaperSummary fields and return FindingsRow dicts.
    Modifies paper_summary in-place (does not save).
    Returns list of FindingsRow kwargs for bulk creation.
    """
    paper_summary.methodology = data.get("methodology", "")
    paper_summary.executive_paragraph = data.get("executive_paragraph", "")
    paper_summary.safety_summary = data.get("safety_summary", "")
    paper_summary.adverse_events = data.get("adverse_events", [])
    paper_summary.limitations = data.get("limitations", [])
    paper_summary.ai_prefilled = True

    rows = []
    for i, f in enumerate(findings_data):
        rows.append({
            "category": f.get("category", "Other"),
            "finding": f.get("finding", ""),
            "quantitative_result": f.get("quantitative_result", ""),
            "page_ref": f.get("page_ref", ""),
            "clinical_significance": f.get("clinical_significance", ""),
            "order": i,
        })
    return rows
