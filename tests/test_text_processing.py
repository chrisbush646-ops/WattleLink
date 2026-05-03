"""Tests for apps.literature.services.text_processing.prepare_text_for_ai"""
import pytest

from apps.literature.services.text_processing import prepare_text_for_ai


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_paper(sections: dict) -> str:
    """Build a minimal paper string from named sections."""
    parts = []
    if "title" in sections:
        parts.append(sections["title"])
    if "abstract" in sections:
        parts.append("Abstract\n\n" + sections["abstract"])
    if "intro" in sections:
        parts.append("Introduction\n\n" + sections["intro"])
    if "methods" in sections:
        parts.append("Methods\n\n" + sections["methods"])
    if "results" in sections:
        parts.append("Results\n\n" + sections["results"])
    if "discussion" in sections:
        parts.append("Discussion\n\n" + sections["discussion"])
    if "ack" in sections:
        parts.append("Acknowledgements\n\n" + sections["ack"])
    if "refs" in sections:
        parts.append("References\n\n" + sections["refs"])
    return "\n\n".join(parts)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_references_section_removed():
    text = _make_paper({
        "title": "A Study",
        "abstract": "We studied X.",
        "refs": "1. Smith J. (2020). Lancet.\n2. Jones A. (2021). NEJM.",
    })
    cleaned, stats = prepare_text_for_ai(text)

    assert "Smith J." not in cleaned
    assert "Jones A." not in cleaned
    assert "References" in stats["sections_removed"]


def test_no_references_section_passthrough():
    text = "Title\n\nAbstract\n\nThis paper has no references section."
    cleaned, stats = prepare_text_for_ai(text)

    assert "no references section" in cleaned
    assert "References" not in stats["sections_removed"]


def test_methods_results_discussion_preserved():
    text = _make_paper({
        "title": "A RCT",
        "methods": "Patients were randomised to drug A or placebo.",
        "results": "The primary endpoint was met (p<0.001).",
        "discussion": "These results suggest a significant benefit.",
        "refs": "1. Author A.",
    })
    cleaned, stats = prepare_text_for_ai(text)

    assert "randomised to drug A" in cleaned
    assert "primary endpoint was met" in cleaned
    assert "significant benefit" in cleaned


def test_author_affiliation_lines_removed():
    affil_block = (
        "Jane Smith\n"
        "1 Department of Cardiology, Royal Melbourne Hospital, Melbourne, VIC\n"
        "2 Faculty of Medicine, University of Melbourne\n"
        "j.smith@unimelb.edu.au\n"
        "0000-0002-1234-5678\n\n"
        "Abstract\n\nWe studied X.\n\n"
        "Methods\n\nPatients were enrolled."
    )
    cleaned, stats = prepare_text_for_ai(affil_block)

    assert "j.smith@unimelb.edu.au" not in cleaned
    assert "0000-0002-1234-5678" not in cleaned
    assert "Royal Melbourne Hospital" not in cleaned
    assert "Author affiliations" in stats["sections_removed"]


def test_copyright_lines_removed():
    text = (
        "© 2023 Elsevier Ltd. All rights reserved.\n"
        "Published by Elsevier\n"
        "Open-access article under CC BY\n\n"
        "Abstract\n\nWe studied Y.\n\n"
        "Methods\n\nDouble-blind design."
    )
    cleaned, stats = prepare_text_for_ai(text)

    assert "Elsevier" not in cleaned
    assert "All rights reserved" not in cleaned
    assert "Copyright/boilerplate" in stats["sections_removed"]


def test_conflict_of_interest_preserved():
    """COI section must NOT be removed — it's a stop pattern for Acknowledgements removal."""
    text = (
        "Methods\n\nDouble-blind RCT.\n\n"
        "Acknowledgements\n\nFunded by NHMRC grant 12345.\n\n"
        "Conflict of Interest\n\nThe authors declare no conflicts."
    )
    cleaned, stats = prepare_text_for_ai(text)

    assert "declare no conflicts" in cleaned
    assert "Acknowledgements/Funding" in stats["sections_removed"]
    assert "Funded by NHMRC" not in cleaned


def test_stats_dict_accuracy():
    long_text = "A " * 10_000  # ~20,000 chars
    refs_section = "\nReferences\n\nSmith J. (2020)."
    text = long_text + refs_section

    cleaned, stats = prepare_text_for_ai(text)

    assert stats["original_tokens"] == len(text) // 4
    assert stats["cleaned_tokens"] == len(cleaned) // 4
    assert 0 < stats["reduction_pct"] < 100
    assert isinstance(stats["sections_removed"], list)


def test_empty_input():
    cleaned, stats = prepare_text_for_ai("")

    assert cleaned == ""
    assert stats["original_tokens"] == 0
    assert stats["cleaned_tokens"] == 0
    assert stats["reduction_pct"] == 0.0
    assert stats["sections_removed"] == []


def test_short_paper_no_boilerplate():
    """A clean short paper with no boilerplate should be returned essentially unchanged."""
    text = (
        "A Randomised Trial of Drug X\n\n"
        "Abstract\n\n"
        "Background: Drug X may reduce events. "
        "Methods: 200 patients randomised. "
        "Results: Primary endpoint met. "
        "Conclusion: Drug X is effective.\n\n"
        "Methods\n\nDouble-blind, placebo-controlled.\n\n"
        "Results\n\nHR 0.72 (95% CI 0.58–0.89; p=0.003).\n\n"
        "Discussion\n\nThese findings support use of Drug X."
    )
    cleaned, stats = prepare_text_for_ai(text)

    assert "HR 0.72" in cleaned
    assert "Double-blind" in cleaned
    assert stats["reduction_pct"] < 5  # essentially unchanged
