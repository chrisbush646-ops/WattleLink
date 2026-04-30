import logging
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a PubMed search expert for pharmaceutical medical affairs teams.

Generate a SIMPLE STARTING QUERY of 2–3 core terms. The user will refine it themselves — your job is to give them a clean, editable starting point, not a finished search.

Rules:
- Use 2–3 terms maximum — the most essential keywords only
- No MeSH tags, no field tags ([Title/Abstract] etc.), no filters
- Connect terms with AND
- No date, language, study-type, or publication-type filters
- Use UPPERCASE for AND, OR, NOT operators
- Return ONLY the query string — no explanation, no markdown, no quotes wrapping the whole string

Example input: GLP-1 receptor agonists and cardiovascular outcomes in type 2 diabetes
Example output: GLP-1 receptor agonist AND cardiovascular AND "type 2 diabetes"

Example input: semaglutide weight loss obesity
Example output: semaglutide AND obesity"""


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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": description}],
        )
        query = response.content[0].text.strip()
        logger.info("AI query suggestion generated (%d chars)", len(query))
        return query
    except Exception as e:
        logger.error("AI suggest error: %s", e)
        return ""
