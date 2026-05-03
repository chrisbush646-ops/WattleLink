import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"

_MAX_TOKENS = 4096


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def extract_claims(paper) -> list[dict]:
    """
    Call Claude at temperature=0 to extract commercially-oriented,
    MA Code-compliant core claims from the paper's full text.
    Returns list of claim dicts on success, raises on error.

    Extended thinking is intentionally not used — temperature=0 is required
    for factual accuracy and is incompatible with thinking mode.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to extract claims from.")

    system_prompt = _load_prompt("extract_claims.md")
    client = anthropic.Anthropic()

    user_message = (
        "Extract core claims from the following clinical paper.\n\n"
        "IMPORTANT: Only use information that appears in the text below. "
        "Do not use any external knowledge. "
        "If information is not present in this text, state 'not reported'.\n\n"
        "Each claim must cover a DISTINCT endpoint or outcome — do not rephrase the same result twice. "
        "If the paper only has one strong primary result, return just one claim. "
        "Only add secondary or safety claims if they report genuinely different data.\n\n"
        "--- BEGIN PAPER TEXT ---\n"
        + content
        + "\n--- END PAPER TEXT ---"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS,
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
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Claims extraction JSON parse error: %s\nRaw: %s", e, raw[:500])
        raise

    return data.get("claims", [])
