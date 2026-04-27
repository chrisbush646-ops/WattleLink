import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def extract_claims(paper) -> list[dict]:
    """
    Call Claude to extract core claims from the paper.
    Returns list of claim dicts on success, raises on error.
    """
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to extract claims from.")

    system_prompt = _load_prompt("extract_claims.md")
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
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Claims extraction JSON parse error: %s\nRaw: %s", e, raw[:500])
        raise

    return data.get("claims", [])
