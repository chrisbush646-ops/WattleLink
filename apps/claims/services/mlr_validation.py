import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts"

_MAX_TOKENS = 4096


def _load_prompt(filename: str) -> str:
    return (PROMPT_PATH / filename).read_text()


def validate_claim(claim) -> dict:
    """
    Run a Medicines Australia Code (Ed. 19/20) + TGA compliance check against a claim.

    Evaluates five rules: PI consistency, substantiation, no hanging comparatives,
    fair balance, and statistical accuracy. Returns a structured dict with a
    0-100 compliance score, PASS/WARN/FAIL verdict, per-rule breakdown, and red flags.
    """
    paper = claim.paper
    paper_text = (paper.full_text or paper.title or "").strip()
    if not paper_text:
        raise ValueError(f"Paper {paper.pk} has no text — cannot run MLR validation.")

    proposed_claim = _build_claim_context(claim)
    pi_summary = claim.approved_indication.strip() or (
        "No TGA Product Information summary provided. "
        "Evaluate Rule 1 against the clinical data source only and flag PI absence as a risk."
    )

    user_message = (
        f"PROPOSED CLAIM:\n{proposed_claim}\n\n"
        f"TGA PRODUCT INFORMATION (PI):\n{pi_summary}\n\n"
        f"CLINICAL DATA SOURCE:\n{paper_text[:60_000]}"
    )

    system_prompt = _load_prompt("mlr_validation.md")
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
        timeout=180,
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("MLR validation JSON parse error: %s\nRaw: %s", e, raw[:500])
        raise


def _build_claim_context(claim) -> str:
    """Assemble a rich claim description for the auditor."""
    lines = [
        f"Claim text: {claim.claim_text}",
        f"Endpoint type: {claim.get_endpoint_type_display()}",
    ]
    if claim.source_passage:
        lines.append(f"Source passage: {claim.source_passage}")
    if claim.source_reference:
        lines.append(f"Source reference: {claim.source_reference}")
    if claim.fair_balance:
        lines.append(f"Fair balance statement: {claim.fair_balance}")
    else:
        lines.append("Fair balance statement: NOT PROVIDED")
    return "\n".join(lines)


def apply_mlr_result(claim, result: dict) -> None:
    """Write MLR validation results onto the claim instance (does not save)."""
    from django.utils import timezone

    claim.mlr_compliance_score = result.get("compliance_score")
    claim.mlr_verdict = result.get("verdict", "")
    claim.mlr_red_flags = result.get("red_flags", [])
    claim.mlr_rule_results = result.get("rules", {})
    claim.mlr_rationale = result.get("rationale", "")
    claim.mlr_checked_at = timezone.now()
