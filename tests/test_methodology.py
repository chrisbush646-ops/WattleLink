import pytest
from apps.summaries.services.validation import validate_summary
from apps.drafting.services.talking_points import build_study_context
from apps.drafting.services.lit_review import build_methodology_section
from unittest.mock import MagicMock


def _methodology(**overrides) -> dict:
    base = {
        "study_design": "multicentre, double-blind, randomised, placebo-controlled phase III trial",
        "population": {
            "description": "Adults with moderate-to-severe RA who failed ≥2 DMARDs",
            "sample_size": "N=842",
            "demographics": "Mean age 54.2 years; 78% female",
        },
        "intervention": "bDMARD 200mg SC every 2 weeks",
        "comparator": "Placebo",
        "follow_up": "52 weeks",
        "primary_endpoint": "ACR20 response at 24 weeks",
        "secondary_endpoints": ["DAS28-CRP remission at 52 weeks", "HAQ-DI change from baseline"],
        "statistical_methods": "ITT analysis; α=0.05; multiplicity-adjusted",
        "setting": "42 sites across 8 countries; 2019–2022",
        "source_reference": "Methods, pp.2–4",
    }
    base.update(overrides)
    return base


def _base_summary(**overrides) -> dict:
    data = {
        "executive_summary": (
            "This multicentre, double-blind, randomised, placebo-controlled phase III trial (N=842) "
            "demonstrated that bDMARD significantly improved ACR20 response at 24 weeks compared "
            "with placebo (68.4% vs 27.1%; RR 2.52; 95% CI 2.1–3.0; p<0.001; NNT 2.4), a "
            "clinically and statistically meaningful difference. Secondary endpoints showed "
            "sustained DAS28-CRP remission at 52 weeks (41.2% vs 12.8%; HR 3.21; p<0.001). "
            "Grade 3/4 serious infections occurred in 4.7% of treated patients versus 1.1% with "
            "placebo (p=0.002), requiring pre-treatment screening per local guidelines. "
            "Discontinuation rates were 6.8% versus 2.3% in the placebo arm. Patients over 75 and "
            "those with eGFR less than 30 were excluded. Results align with EULAR 2022 "
            "treat-to-target guidance recommending bDMARD addition after failure of two DMARDs."
        ),
        "methodology": _methodology(),
        "findings": [
            {
                "category": "Primary",
                "finding": "ACR20 response at 24 weeks",
                "quantitative_result": "68.4% vs 27.1%; RR 2.52 (95% CI 2.1–3.0); p<0.001",
                "source_reference": "p.4, Table 2",
                "clinical_significance": "Supports second-line use",
            }
        ],
        "safety_profile": {
            "summary": "Grade 3/4 infections: 4.7% vs 1.1% (p=0.002). Discontinuations: 6.8% vs 2.3%.",
            "serious_adverse_events": [],
            "discontinuation_rate": "6.8%",
            "source_reference": "p.6, Table 4",
        },
        "limitations": [
            {"limitation": "52-week follow-up insufficient for chronic disease", "source_reference": "p.7"}
        ],
        "confidence_flags": [],
    }
    data.update(overrides)
    return data


_PAPER_TEXT = (
    "N=842 patients were enrolled. ACR20 response rate: 68.4% vs 27.1%; RR 2.52 "
    "(95% CI 2.1–3.0); p<0.001. DAS28-CRP remission: 41.2% vs 12.8%; HR 3.21; p<0.001. "
    "Grade 3/4 infections: 4.7% vs 1.1% (p=0.002). Discontinuation: 6.8% vs 2.3%."
)


# a. Missing study_design generates a warning
def test_missing_study_design_generates_warning():
    m = _methodology(study_design="not reported")
    summary = _base_summary(methodology=m)
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("study_design" in w for w in warnings)


# b. Missing primary_endpoint generates a warning
def test_missing_primary_endpoint_generates_warning():
    m = _methodology(primary_endpoint="not reported")
    summary = _base_summary(methodology=m)
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("primary_endpoint" in w for w in warnings)


# c. Missing intervention generates a warning
def test_missing_intervention_generates_warning():
    m = _methodology(intervention="not reported")
    summary = _base_summary(methodology=m)
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("intervention" in w for w in warnings)


# d. Sample size mismatch between methodology and exec summary generates a warning
def test_sample_size_mismatch_generates_warning():
    m = _methodology(population={"description": "RA patients", "sample_size": "N=999", "demographics": ""})
    summary = _base_summary(methodology=m)
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("sample size" in w.lower() for w in warnings)


# e. Complete methodology produces no methodology-related warnings
def test_complete_methodology_no_warnings():
    warnings = validate_summary(_base_summary(), _PAPER_TEXT)
    assert warnings == []


# f. build_study_context includes study design, sample size, and primary endpoint
def test_build_study_context_includes_key_fields():
    summary = _make_summary_mock()
    context = build_study_context(summary)
    assert "842" in context
    assert "ACR20" in context
    assert "bDMARD" in context


# g. build_study_context handles empty methodology gracefully
def test_build_study_context_empty_methodology():
    summary = _make_summary_mock(methodology={})
    context = build_study_context(summary)
    assert "Key findings:" in context


# h. build_methodology_section produces a non-empty paragraph
def test_build_methodology_section_returns_paragraph():
    summary = _make_summary_mock()
    text = build_methodology_section(summary)
    assert "842" in text
    assert "phase III" in text
    assert "ACR20" in text


# i. build_methodology_section handles empty methodology gracefully
def test_build_methodology_section_empty_returns_empty():
    summary = _make_summary_mock(methodology={})
    assert build_methodology_section(summary) == ""


def _make_summary_mock(methodology=None):
    if methodology is None:
        methodology = _methodology()

    finding = MagicMock()
    finding.category = "Primary"
    finding.finding = "ACR20 response at 24 weeks"
    finding.quantitative_result = "68.4% vs 27.1%; p<0.001"
    finding.page_ref = "p.4"
    finding.order = 0

    findings_qs = MagicMock()
    findings_qs.filter.return_value.order_by.return_value = [finding]

    summary = MagicMock()
    summary.methodology = methodology
    summary.findings = findings_qs
    summary.safety_summary = "Grade 3/4 infections: 4.7% vs 1.1%."
    return summary
