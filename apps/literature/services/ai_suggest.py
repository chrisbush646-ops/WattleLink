import logging
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a PubMed search expert for pharmaceutical medical affairs.

Given a natural language description of a research topic, return a single valid PubMed Boolean query string.

Rules:
- Use MeSH terms where appropriate: term[Mesh]
- Use field tags: [Title/Abstract], [Title], [Author], [Journal]
- Combine terms with AND, OR, NOT (uppercase)
- Group with parentheses
- Return ONLY the query string — no explanation, no markdown, no quotes around the whole thing

Example output:
("rheumatoid arthritis"[Mesh] OR "RA"[Title/Abstract]) AND ("TNF inhibitor"[Title/Abstract] OR "anti-TNF"[Title/Abstract]) AND ("long-term"[Title/Abstract] OR "safety"[Title/Abstract])"""


def suggest_pubmed_query(description: str) -> str:
    """Call Claude to suggest a PubMed Boolean query from a natural language description."""
    import anthropic

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set; returning empty suggestion")
        return ""

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": description}],
        )
        query = response.content[0].text.strip()
        logger.info("AI query suggestion generated (%d chars)", len(query))
        return query
    except Exception as e:
        logger.error("AI suggest error: %s", e)
        return ""
