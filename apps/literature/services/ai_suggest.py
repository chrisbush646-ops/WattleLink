import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a PubMed search expert for pharmaceutical medical affairs teams.

Generate a comprehensive Boolean query broken into individual rows. Each row is one concept group.

Rules:
- Return a JSON array of row objects. Each object has: "operator" (AND/OR/NOT), "field" (tiab/mesh/all), "term" (string)
- First row always has operator "AND" (it is the anchor term)
- Group synonyms and variants inside a single term using OR: e.g. "semaglutide OR ozempic OR wegovy"
- Build 4–8 rows covering: intervention/drug, disease/condition, comparator or population (if relevant), key outcomes, study design (if specific)
- Use "mesh" field for well-established MeSH terms (diseases, drug classes), "tiab" for specific drug names and outcomes
- Do NOT add date, language, or publication-type filters — those are handled by the UI
- Return ONLY valid JSON — no markdown, no explanation, no code fences

Example input: semaglutide cardiovascular outcomes type 2 diabetes

Example output:
[
  {"operator":"AND","field":"tiab","term":"semaglutide OR ozempic OR wegovy"},
  {"operator":"AND","field":"mesh","term":"Diabetes Mellitus, Type 2"},
  {"operator":"AND","field":"tiab","term":"cardiovascular outcomes OR MACE OR major adverse cardiac events"},
  {"operator":"AND","field":"tiab","term":"randomized controlled trial OR RCT OR clinical trial"},
  {"operator":"NOT","field":"tiab","term":"animal study OR in vitro"}
]

Example input: TNF inhibitors rheumatoid arthritis joint damage

Example output:
[
  {"operator":"AND","field":"mesh","term":"Tumor Necrosis Factor Inhibitors"},
  {"operator":"AND","field":"tiab","term":"adalimumab OR etanercept OR infliximab OR certolizumab OR golimumab"},
  {"operator":"AND","field":"mesh","term":"Arthritis, Rheumatoid"},
  {"operator":"AND","field":"tiab","term":"joint damage OR radiographic progression OR erosion OR joint destruction"},
  {"operator":"AND","field":"tiab","term":"disease activity OR DAS28 OR ACR response"}
]"""


def suggest_pubmed_query(description: str) -> list[dict]:
    """Call Claude to suggest structured PubMed query rows from a natural language description."""
    import anthropic

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set; returning empty suggestion")
        return []

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": description}],
        )
        raw = response.content[0].text.strip()
        rows = json.loads(raw)
        logger.info("AI query suggestion generated (%d rows)", len(rows))
        return rows
    except Exception as e:
        logger.error("AI suggest error: %s", e)
        return []
