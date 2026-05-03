import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"


def verify_kol_currency(candidate) -> dict:
    """
    Ask Claude to assess whether a KOL candidate is currently active.
    Returns dict with current_status, note, concerns.
    """
    profile = f"""Name: {candidate.name}
Institution: {candidate.institution or "Unknown"}
Specialty: {candidate.specialty or "Unknown"}
Location: {candidate.location or "Unknown"}
Bio: {candidate.bio[:400] if candidate.bio else "Not provided"}
Relevance note: {candidate.relevance_note[:200] if candidate.relevance_note else "Not provided"}"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        temperature=0,
        system=(PROMPT_PATH / "kol_verification.md").read_text(),
        messages=[{"role": "user", "content": profile}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```"))

    result = json.loads(raw)
    return {
        "current_status": result.get("current_status", "UNCERTAIN"),
        "note": result.get("note", ""),
        "concerns": result.get("concerns", []),
    }
