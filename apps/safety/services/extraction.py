import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"
_MAX_TOKENS = 4096
_TEXT_LIMIT = 40_000


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def extract_safety_signals(paper) -> list[dict]:
    """
    Call Claude to identify adverse events in a paper's full text.
    Returns a list of AE dicts ready for SignalMention creation.
    """
    content = (paper.full_text or "").strip()
    if not content:
        return []

    client = anthropic.Anthropic()
    system_prompt = _load_prompt("extract_safety_signals.md")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                f"Paper title: {paper.title}\n\n"
                f"Full text:\n{content[:_TEXT_LIMIT]}"
            ),
        }],
        timeout=120,
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        return []

    raw = text_block.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.startswith("```")
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(
            "Safety extraction JSON parse error for paper %s: %s — raw: %s",
            paper.pk, exc, raw[:400],
        )
        return []

    return data.get("adverse_events", [])
