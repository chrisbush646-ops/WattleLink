import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_BOOLEAN_SUGGEST_SYSTEM = """You are a medical librarian and PubMed search specialist. You help pharmaceutical medical affairs teams build broad, high-recall PubMed searches.

## Mode 1: Query suggestion

Generate a simple Boolean search with 2–3 concept rows maximum. The goal is to FIND papers, not filter them — err heavily on the side of breadth. The user can narrow results afterwards.

### Query generation rules

- Use 2 concept rows for most topics: (1) drug/intervention and (2) disease/condition
- Add a 3rd row only if the topic is very specific (e.g., a particular outcome or subpopulation)
- Each row `term` must be a SINGLE plain word or short phrase — the most common name for the concept
- Do NOT put OR expressions or synonyms in the `term` field — the user expands synonyms separately
- Do NOT include outcome terms, study design terms, or population terms as separate AND rows
- Do NOT include date, language, publication type, or species filters
- Use field `tiab` for drug/disease terms; use `mesh` only if the topic maps exactly to a known MeSH heading

### Output format

Return ONLY valid JSON (no markdown fences, no prose):

{
  "query_parts": [
    {
      "operator": "AND",
      "field": "tiab",
      "term": "semaglutide",
      "synonyms_expanded": false,
      "explanation": "Primary drug — INN name, user can expand synonyms separately"
    },
    {
      "operator": "AND",
      "field": "tiab",
      "term": "type 2 diabetes",
      "synonyms_expanded": false,
      "explanation": "Target disease"
    }
  ],
  "recommended_filters": {
    "study_types": ["rct", "meta", "sr"],
    "date_preset": "last5",
    "language_english": true,
    "species_humans": true
  },
  "explanation": "Broad 2-row search: drug AND disease. Use synonym expansion or refinement to narrow further."
}

`operator` must be one of: `AND`, `OR`, `NOT`
`field` must be one of: `tiab`, `ti`, `mesh`, `au`, `ta`, `all`
`synonyms_expanded` must be `false` unless the term already contains OR-connected synonyms
`study_types` valid values: `rct`, `meta`, `sr`, `obs`, `case_report`, `clinical_trial`, `review`, `guideline`
`date_preset` valid values: `last1`, `last2`, `last5`, `last10`

---

## Mode 2: Refinement suggestion

When asked to suggest refinements to a broad query, analyse what is likely returning irrelevant results and suggest specific terms to AND or NOT into the query.

### Refinement rules

- Never suggest removing core concept terms
- Suggest MeSH subheading qualifiers where appropriate (e.g., `/adverse effects`, `/therapy`, `/drug therapy`)
- Prefer AND refinements that add specificity over NOT exclusions where possible
- Reserve NOT for clearly out-of-scope populations or study types
- For each suggestion, estimate the impact in plain language

### Refinement output format

Return ONLY valid JSON (no markdown fences, no prose):

{
  "refinement_suggestions": [
    {
      "term": "long-term[tiab] OR 52-week[tiab] OR 2-year[tiab]",
      "operator": "AND",
      "rationale": "Narrows to papers with durability data — likely removes short-term pharmacokinetic studies",
      "estimated_impact": "Removes ~30–40% of short-duration studies"
    },
    {
      "term": "animal[tiab] OR rodent[tiab] OR murine[tiab]",
      "operator": "NOT",
      "rationale": "Excludes pre-clinical animal studies if species filter is not active",
      "estimated_impact": "Removes ~10–15% of results"
    }
  ]
}

## Hard rules

- Return ONLY valid JSON matching the schema above — no markdown, no prose, no code fences
- All PubMed syntax must be valid — use only recognised field tags
- Do not fabricate MeSH terms — only suggest MeSH terms you are confident exist
- If a term has no established MeSH, use `[tiab]` only
- Do NOT generate, guess, or include DOIs anywhere in your output"""

_EXPAND_SYSTEM = (
    "You are a PubMed search specialist. Given a search term and its field tag, "
    "return a single valid PubMed expression that groups the original term with its "
    "synonyms, abbreviations, and the most relevant MeSH term. "
    "Return ONLY the PubMed expression string, no JSON, no explanation. "
    "Example: given 'rheumatoid arthritis' in tiab, return: "
    '("rheumatoid arthritis"[MeSH] OR "rheumatoid arthritis"[tiab] OR "RA"[tiab])'
)


def _client():
    import anthropic
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    return anthropic.Anthropic(api_key=api_key) if api_key else None


def suggest_pubmed_query(description: str) -> dict:
    """
    Generate a structured PubMed query from a natural language description.
    Returns dict with keys: rows, query_parts, recommended_filters, explanation.
    """
    client = _client()
    if not client:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
        system=_BOOLEAN_SUGGEST_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Generate a PubMed Boolean search query for the following research topic.\n\n"
                f"Research topic: {description}\n\n"
                "Return ONLY the JSON object matching the Mode 1 schema. No prose, no markdown fences."
            ),
        }],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if the model adds them despite instructions
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("AI suggest: JSON parse failed. Raw response: %r", raw[:500])
        raise ValueError(f"AI returned unparseable response: {exc}") from exc

    parts = data.get("query_parts", [])
    if not parts:
        logger.error("AI suggest: no query_parts in response. Full data: %r", data)
        raise ValueError("AI returned a response with no query rows.")

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
            system=_BOOLEAN_SUGGEST_SYSTEM,
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
