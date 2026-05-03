import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "boolean_suggest.md"

_EXPAND_SYSTEM = (
    "You are a PubMed search specialist. Given a search term and its field tag, "
    "return a single valid PubMed expression that groups the original term with its "
    "synonyms, abbreviations, and the most relevant MeSH term. "
    "Return ONLY the PubMed expression string, no JSON, no explanation. "
    "Example: given 'rheumatoid arthritis' in tiab, return: "
    '("rheumatoid arthritis"[MeSH] OR "rheumatoid arthritis"[tiab] OR "RA"[tiab])'
)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _client():
    import anthropic
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    return anthropic.Anthropic(api_key=api_key) if api_key else None


def suggest_pubmed_query(description: str) -> dict:
    """
    Generate a structured PubMed query from a natural language description.
    Returns dict with keys: rows (for backward compat), query_parts, recommended_filters, explanation.
    """
    client = _client()
    if not client:
        logger.warning("ANTHROPIC_API_KEY not set; returning empty suggestion")
        return {}

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0,
            system=_load_prompt(),
            messages=[{
                "role": "user",
                "content": f"Mode: query suggestion\n\nResearch topic: {description}"
            }],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```"))
        data = json.loads(raw)
    except Exception as e:
        logger.error("AI suggest query error: %s", e)
        return {}

    parts = data.get("query_parts", [])
    rows = [
        {
            "operator": p.get("operator", "AND"),
            "field": p.get("field", "tiab"),
            "term": p.get("term", ""),
            "synonyms_expanded": p.get("synonyms_expanded", False),
        }
        for p in parts
    ]

    return {
        "rows": rows,
        "query_parts": parts,
        "recommended_filters": data.get("recommended_filters", {}),
        "explanation": data.get("explanation", ""),
    }


def expand_synonyms(term: str, field: str) -> str:
    """
    Expand a single search term with synonyms and MeSH variants.
    Returns a valid PubMed group expression string.
    Falls back to a simple tagged term on error.
    """
    client = _client()
    field_tag = {"tiab": "[tiab]", "ti": "[ti]", "mesh": "[MeSH]", "all": "", "au": "[au]", "ta": "[ta]"}.get(field, "[tiab]")
    fallback = f'"{term}"{field_tag}' if " " in term else f"{term}{field_tag}"

    if not client:
        return fallback

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            temperature=0,
            system=_EXPAND_SYSTEM,
            messages=[{"role": "user", "content": f"Term: {term}\nField: {field}"}],
        )
        result = response.content[0].text.strip()
        if result:
            return result
    except Exception as e:
        logger.error("Synonym expansion error for %r: %s", term, e)

    return fallback


def suggest_refinements(query: str, result_count: int, top_mesh: list) -> list:
    """
    Suggest 3–5 refinement/exclusion terms to narrow a broad query.
    Returns list of dicts: {term, operator, rationale, estimated_impact}.
    """
    client = _client()
    if not client:
        return []

    mesh_summary = ", ".join(d.get("term", "") for d in top_mesh[:10]) if top_mesh else "not available"
    user_msg = (
        f"Mode: refinement suggestion\n\n"
        f"Original query: {query}\n"
        f"Broad result count: {result_count} papers\n"
        f"Top MeSH terms in results: {mesh_summary}\n\n"
        f"Suggest 3–5 refinements to narrow to the most clinically relevant papers."
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            system=_load_prompt(),
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```"))
        data = json.loads(raw)
        return data.get("refinement_suggestions", [])
    except Exception as e:
        logger.error("AI suggest refinements error: %s", e)
        return []
