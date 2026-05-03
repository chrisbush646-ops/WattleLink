import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def run_ai_assessment(paper) -> dict:
    """
    Call Claude to pre-fill GRADE + RoB 2 for the given paper.
    Returns the parsed dict on success, raises on unrecoverable error.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to assess.")

    system_prompt = _load_prompt("grade_assessment.md")
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        timeout=120,
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if the model wrapped output anyway
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines
            if not line.startswith("```")
        )

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("AI assessment JSON parse error: %s\nRaw output: %s", e, raw[:500])
        raise


def _t(value, max_len: int) -> str:
    """Truncate a string to max_len, guarding against None."""
    s = value or ""
    return s[:max_len] if len(s) > max_len else s


def apply_grade_result(grade_assessment, grade_data: dict) -> None:
    """Map AI JSON → GradeAssessment fields (in-place, does not save)."""
    grade_assessment.overall_rating = _t(grade_data.get("overall_rating", ""), 20)

    for field_prefix, key in [
        ("rob", "rob"),
        ("inconsistency", "inconsistency"),
        ("indirectness", "indirectness"),
        ("imprecision", "imprecision"),
        ("publication_bias", "publication_bias"),
    ]:
        domain = grade_data.get(key, {})
        setattr(grade_assessment, f"{field_prefix}_rating", _t(domain.get("rating", ""), 20))
        setattr(grade_assessment, f"{field_prefix}_rationale", domain.get("rationale", ""))
        setattr(grade_assessment, f"{field_prefix}_page_ref", _t(domain.get("page_ref", ""), 100))

    grade_assessment.ai_prefilled = True


def apply_rob_result(rob_assessment, rob_data: dict) -> None:
    """Map AI JSON → RobAssessment fields (in-place, does not save)."""
    rob_assessment.overall_judgment = _t(rob_data.get("overall_judgment", ""), 20)

    for prefix in ("d1", "d2", "d3", "d4", "d5"):
        domain = rob_data.get(prefix, {})
        setattr(rob_assessment, f"{prefix}_judgment", _t(domain.get("judgment", ""), 20))
        setattr(rob_assessment, f"{prefix}_rationale", domain.get("rationale", ""))
        setattr(rob_assessment, f"{prefix}_page_ref", _t(domain.get("page_ref", ""), 100))

    rob_assessment.ai_prefilled = True
