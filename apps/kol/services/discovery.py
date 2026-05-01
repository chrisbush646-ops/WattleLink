import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"


def suggest_kols_by_keyword(query: str) -> list[dict]:
    """
    Use Claude to suggest KOL candidates for a keyword query.
    Returns a list of candidate dicts. Raises on error.
    """
    if not query.strip():
        raise ValueError("Search query is required.")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=(PROMPT_PATH / "kol_suggest.md").read_text(),
        messages=[{
            "role": "user",
            "content": (
                f"Suggest KOL candidates relevant to the following therapeutic area or keywords:\n\n{query}\n\n"
                "Return 5–8 candidates meeting Australian medical affairs KOL criteria."
            ),
        }],
        timeout=60,
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("AI returned no text.")

    raw = text_block.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```"))

    data = json.loads(raw)
    return data.get("candidates", [])


def discover_kols(paper) -> list[dict]:
    """Call Claude to extract KOL candidates from a paper. Returns list of candidate dicts."""
    content = paper.full_text or paper.title
    if not content.strip():
        raise ValueError(f"Paper {paper.pk} has no text for KOL discovery.")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=(PROMPT_PATH / "kol_discovery.md").read_text(),
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```"))

    return json.loads(raw).get("candidates", [])
