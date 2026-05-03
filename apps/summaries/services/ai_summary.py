import json
import logging
import re
from pathlib import Path

import anthropic

from apps.literature.services.text_processing import prepare_text_for_ai

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9a-z]+\b", re.IGNORECASE)

# Two-call path: papers above this token estimate are split into methodology +
# findings calls. 12,000 tokens ≈ 48,000 chars at ~4 chars/token.
_TOKEN_THRESHOLD = 12_000
_CHARS_PER_TOKEN = 4

# Matches standalone Results / Outcomes section headings (numbered or plain,
# any case) so we can split pre-results text from results-onwards text.
_RESULTS_SECTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:\d+\.?\s+)?(?:results?|outcomes?)\s*(?:\n|$)',
    re.IGNORECASE,
)

# ── Inline system prompts for the two-call path ──────────────────────────────
# Inlined to avoid file-path issues in containerised deployments.

_METHODOLOGY_SYSTEM = """You are a Senior Medical Affairs Professional in Australian pharma, extracting structured methodology from a clinical paper for Medical Science Liaisons.

Your output will be reviewed by a human before use. Every detail must be traceable directly to the source text.

## Critical accuracy rules

1. NEVER state a number or sample size unless it appears verbatim in the source text. Write "not reported" if you cannot find the exact figure.
2. NEVER upgrade certainty. Copy the authors' exact language — do not rephrase or strengthen.
3. NEVER add information the authors did not provide. No inferences, no external knowledge.
4. Always include a section or page reference for each methodology field.
5. If information is not in the text, state "not reported". Never fill gaps from training data.

## Output format

Return ONLY valid JSON with a single top-level key "methodology". No prose, no markdown fences.

{
  "methodology": {
    "study_design": "Exact design as stated by the authors (e.g. 'multicentre, double-blind, randomised, placebo-controlled, phase III trial'). Copy their phrasing exactly.",
    "population": {
      "description": "Inclusion criteria and population description as stated in the Methods section. Use the authors' exact wording.",
      "sample_size": "Exact N as reported (e.g. 'N=14,802'). If multiple arms, list each. Write 'not reported' if not stated.",
      "demographics": "Key baseline characteristics if reported: mean age, sex distribution, disease duration. Use exact figures. Write 'not reported' for anything not in the paper."
    },
    "intervention": "Exact intervention including drug name, dose, route, frequency, duration — as stated. If multiple arms, list each. Write 'not reported' if not stated.",
    "comparator": "Exact comparator as stated. Write 'none (single arm)' or 'placebo' as appropriate. Write 'not reported' if not stated.",
    "follow_up": "Exact follow-up duration as stated. Write 'not reported' if not stated.",
    "primary_endpoint": "The primary endpoint as defined in the Methods section. Copy the authors' definition exactly — do not paraphrase.",
    "secondary_endpoints": ["Each secondary endpoint as defined by the authors. Empty array if none stated."],
    "statistical_methods": "Key statistical methods if reported: analysis type (e.g. ITT), significance threshold, multiplicity adjustment. Write 'not reported' if not described.",
    "setting": "Countries, number of sites, time period. Write 'not reported' for anything not stated.",
    "source_reference": "Section or page reference for the Methods section (e.g. 'Methods, p.2'). Write '[LOCATION NOT FOUND]' if you cannot locate it."
  }
}

## Hard rules
- Return ONLY the JSON object above — no prose, no markdown fences, no text outside the JSON.
- All details must be extracted verbatim from the provided text.
- Do NOT generate, guess, or include DOIs anywhere in your output."""

_FINDINGS_SYSTEM = """You are a Senior Medical Affairs Professional in Australian pharma, extracting findings and writing an executive summary for a clinical paper for Medical Science Liaisons.

The study methodology has already been extracted and is provided as context in the user message. Use it to understand what primary and secondary endpoints to look for in the Results section.

Your output will be reviewed by a human before use. Every figure must be traceable directly to the source text.

## Critical accuracy rules

1. NEVER state a number, percentage, p-value, CI, or sample size unless it appears verbatim in the source text. Write "not reported" if you cannot find the exact figure.
2. NEVER upgrade certainty. If the paper says "may be associated with", write exactly that. Do not write "is associated with".
3. NEVER add conclusions the authors did not make. No causation if the paper says correlation.
4. EVERY finding must include a page or section reference. If you cannot locate it, write "[LOCATION NOT FOUND]".
5. Primary endpoint first, then secondary, then post-hoc. Label each clearly.
6. Include the study's own stated limitations only. Do not add your own.
7. Report exact adverse event rates. Do not say "well-tolerated" unless the authors use that phrase.
8. If information is not in the text, say "not reported in this paper". Never fill gaps from training data.

## Output format

Return ONLY valid JSON. No prose, no markdown fences.

{
  "executive_summary": "150-200 word paragraph written in the authors' own language. Must include: the study design type (from the provided methodology), the exact sample size (from methodology.population.sample_size), and the primary endpoint result with its exact statistic. Written as a publication-ready paragraph for MSL use.",

  "findings": [
    {
      "category": "Primary",
      "finding": "Description of the finding using authors' language",
      "quantitative_result": "Exact statistics as written in the paper (e.g. '68.4% vs 27.1%; RR 2.52 (95% CI 2.1-3.0); p<0.001'). Write 'not reported' if no numbers are available.",
      "source_reference": "Page number, table, or section where this finding appears (e.g. 'p.4, Table 2'). Write '[LOCATION NOT FOUND]' if you cannot locate it.",
      "clinical_significance": "Clinical interpretation using the authors' own words. Do not add your own clinical judgement."
    }
  ],

  "safety_profile": {
    "summary": "Narrative summary of the safety profile using exact incidence rates as reported. Do not use 'well-tolerated' unless the authors do.",
    "serious_adverse_events": [
      {
        "event": "Adverse event name",
        "incidence": "Exact rate as reported (e.g. '4.7% vs 1.1%')",
        "source_reference": "Location in paper"
      }
    ],
    "discontinuation_rate": "Exact discontinuation rate as reported, or 'not reported'",
    "source_reference": "Primary section/table where safety data appears"
  },

  "limitations": [
    {
      "limitation": "Limitation as stated by the authors. Do not paraphrase or add your own.",
      "source_reference": "Where in the paper this limitation is stated"
    }
  ],

  "confidence_flags": [
    "List any specific claims, statistics, or references you could not verify in the text.",
    "Leave this array empty if everything in your output is directly verifiable in the source text."
  ]
}

## Category values for findings
- "Primary" — primary endpoint results
- "Secondary" — secondary endpoint results
- "Post-hoc" — post-hoc or exploratory analyses (label these clearly)
- "Safety" — adverse events, tolerability, discontinuations

## Hard rules
- Return ONLY the JSON object above — no prose, no markdown fences, no text outside the JSON.
- All statistics must be extracted verbatim from the provided text.
- Include at least one Primary finding.
- The confidence_flags array must be empty only if everything is directly verifiable. Never leave it empty as a shortcut.
- Do NOT generate, guess, or include DOIs anywhere in your output."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_doi_patterns(text: str) -> str:
    """Remove DOI-like strings from AI-generated text."""
    if not text:
        return text
    return _DOI_RE.sub("", text).strip()


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```")).strip()
    return json.loads(raw)


def _split_for_two_calls(text: str) -> tuple[str, str]:
    """
    Split paper into (pre_results, results_onwards).
    pre_results  — title + abstract + intro + methods  → Call 1 input
    results_onwards — results + tables + discussion    → Call 2 input
    Falls back to a 40/60 character split when no Results heading is found.
    """
    match = _RESULTS_SECTION_RE.search(text)
    if match:
        return text[:match.start()].strip(), text[match.start():].strip()
    split_point = int(len(text) * 0.4)
    return text[:split_point].strip(), text[split_point:].strip()


# ── Two-call path ─────────────────────────────────────────────────────────────

def _run_methodology_call(client: anthropic.Anthropic, text: str) -> dict:
    user_message = (
        "Extract the methodology from the following paper text.\n\n"
        "IMPORTANT: Only use information that appears in the text below. "
        "Do not use any external knowledge. "
        "If information is not present in this text, state 'not reported'.\n\n"
        "--- BEGIN PAPER TEXT ---\n"
        + text
        + "\n--- END PAPER TEXT ---"
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
        system=[{"type": "text", "text": _METHODOLOGY_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
        timeout=120,
    )
    try:
        return _parse_json_response(response.content[0].text)
    except json.JSONDecodeError as e:
        logger.error("Methodology call JSON parse error: %s\nRaw: %s", e,
                     response.content[0].text[:500])
        raise


def _run_findings_call(
    client: anthropic.Anthropic, text: str, methodology: dict
) -> dict:
    user_message = (
        "Extract findings, safety profile, limitations, and executive summary "
        "from the following paper sections.\n\n"
        "IMPORTANT: Only use information that appears in the text below. "
        "Do not use any external knowledge. "
        "If information is not present in this text, state 'not reported'.\n\n"
        "--- METHODOLOGY CONTEXT (already extracted from Methods section) ---\n"
        + json.dumps(methodology, indent=2)
        + "\n--- END METHODOLOGY CONTEXT ---\n\n"
        "--- BEGIN PAPER TEXT (Results, Discussion, Tables) ---\n"
        + text
        + "\n--- END PAPER TEXT ---"
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0,
        system=[{"type": "text", "text": _FINDINGS_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
        timeout=180,
    )
    try:
        return _parse_json_response(response.content[0].text)
    except json.JSONDecodeError as e:
        logger.error("Findings call JSON parse error: %s\nRaw: %s", e,
                     response.content[0].text[:500])
        raise


def _run_two_call_summary(client: anthropic.Anthropic, content: str) -> dict:
    pre_results, results_onwards = _split_for_two_calls(content)
    logger.info(
        "Two-call summary: pre_results=%d chars, results_onwards=%d chars",
        len(pre_results), len(results_onwards),
    )

    call1 = _run_methodology_call(client, pre_results)
    methodology = call1.get("methodology", {})

    call2 = _run_findings_call(client, results_onwards, methodology)

    # Merge: methodology from Call 1 takes precedence over anything Call 2 might return
    return {**call2, "methodology": methodology}


# ── Public entry point ────────────────────────────────────────────────────────

def run_ai_summary(paper) -> dict:
    """
    Call Claude at temperature=0 to produce a structured MSL briefing note.

    Preprocesses the full text to remove boilerplate before any AI call.
    Papers over ~12,000 tokens (after preprocessing) are processed via two
    sequential calls (methodology extraction, then findings extraction).

    Extended thinking is intentionally not used — temperature=0 is required
    for factual accuracy and is incompatible with thinking mode.
    """
    raw_content = paper.full_text or paper.title
    if not raw_content.strip():
        raise ValueError(f"Paper {paper.pk} has no text to summarise.")

    content, preprocessing_stats = prepare_text_for_ai(raw_content)
    if not content.strip():
        content = raw_content  # fallback: preprocessing removed everything
        preprocessing_stats = {}

    client = anthropic.Anthropic()

    if _estimate_tokens(content) > _TOKEN_THRESHOLD:
        logger.info(
            "Paper %s: ~%d tokens — using two-call summary path",
            paper.pk, _estimate_tokens(content),
        )
        result = _run_two_call_summary(client, content)
        result["preprocessing_stats"] = preprocessing_stats
        return result

    # ── Single-call path (papers ≤ 12,000 tokens) ────────────────────────────
    system_prompt = _load_prompt("summarise_paper.md")
    user_message = (
        "Summarise the following paper.\n\n"
        "IMPORTANT: Only use information that appears in the text below. "
        "Do not use any external knowledge. "
        "If information is not present in this text, state 'not reported'.\n\n"
        "--- BEGIN PAPER TEXT ---\n"
        + content
        + "\n--- END PAPER TEXT ---"
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0,
        system=[{"type": "text", "text": system_prompt,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
        timeout=180,
    )
    try:
        result = _parse_json_response(response.content[0].text)
        result["preprocessing_stats"] = preprocessing_stats
        return result
    except json.JSONDecodeError as e:
        logger.error("AI summary JSON parse error: %s\nRaw: %s", e,
                     response.content[0].text[:500])
        raise


# ── Result mapping ────────────────────────────────────────────────────────────

def apply_summary_result(paper_summary, findings_data: list, data: dict) -> list:
    """
    Map AI JSON → PaperSummary fields and return FindingsRow dicts.
    Handles both the new schema (executive_summary, safety_profile) and
    the legacy schema (executive_paragraph, safety_summary) for resilience.
    Modifies paper_summary in-place (does not save).
    Returns list of FindingsRow kwargs for bulk creation.
    """
    raw_methodology = data.get("methodology", {})
    if isinstance(raw_methodology, dict):
        paper_summary.methodology = raw_methodology
    elif isinstance(raw_methodology, str) and raw_methodology.strip():
        paper_summary.methodology = {"study_design": raw_methodology.strip()}
    else:
        paper_summary.methodology = {}

    paper_summary.executive_paragraph = _strip_doi_patterns(
        data.get("executive_summary") or data.get("executive_paragraph", "")
    )

    safety_profile = data.get("safety_profile")
    if isinstance(safety_profile, dict):
        paper_summary.safety_summary = _strip_doi_patterns(safety_profile.get("summary", ""))
        paper_summary.adverse_events = safety_profile.get("serious_adverse_events", [])
    else:
        paper_summary.safety_summary = _strip_doi_patterns(data.get("safety_summary", ""))
        paper_summary.adverse_events = data.get("adverse_events", [])

    raw_limitations = data.get("limitations", [])
    normalised = []
    for lim in raw_limitations:
        if isinstance(lim, dict):
            normalised.append({
                "limitation": lim.get("limitation", ""),
                "page_ref": lim.get("source_reference") or lim.get("page_ref", ""),
            })
        else:
            normalised.append({"limitation": str(lim), "page_ref": ""})
    paper_summary.limitations = normalised

    paper_summary.confidence_flags = data.get("confidence_flags", [])
    paper_summary.ai_prefilled = True

    rows = []
    for i, f in enumerate(findings_data):
        raw_qr = f.get("quantitative_result", "")
        raw_ref = f.get("source_reference") or f.get("page_ref", "")
        rows.append({
            "category": f.get("category", "Other"),
            "finding": f.get("finding", ""),
            "quantitative_result": raw_qr[:300] if len(raw_qr) > 300 else raw_qr,
            "page_ref": raw_ref[:100] if len(raw_ref) > 100 else raw_ref,
            "clinical_significance": f.get("clinical_significance", ""),
            "order": i,
        })
    return rows
