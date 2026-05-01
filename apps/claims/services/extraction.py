import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"

_THINKING_BUDGET = 6000
_MAX_TOKENS = 12000


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def extract_claims(paper) -> list[dict]:
    """
    Call Claude with extended thinking to extract commercially-oriented,
    MA Code-compliant core claims from the paper's full text.
    Returns list of claim dicts on success, raises on error.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to extract claims from.")

    system_prompt = _load_prompt("extract_claims.md")
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS,
        thinking={"type": "enabled", "budget_tokens": _THINKING_BUDGET},
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                "Extract core claims from the following clinical paper. "
                "Each claim must cover a DISTINCT endpoint or outcome — do not rephrase the same result twice. "
                "If the paper only has one strong primary result, return just one claim. "
                "Only add secondary or safety claims if they report genuinely different data:\n\n"
                + content
            ),
        }],
        timeout=180,
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("Claims extraction returned no text block.")

    raw = text_block.text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Claims extraction JSON parse error: %s\nRaw: %s", e, raw[:500])
        raise

    return data.get("claims", [])
