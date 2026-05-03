import pytest
from apps.summaries.services.validation import validate_summary


def _base_summary(**overrides) -> dict:
    """Return a minimal valid summary dict, with optional field overrides."""
    data = {
        "executive_summary": (
            "This randomised double-blind placebo-controlled trial (n=842) demonstrated that bDMARD "
            "significantly improved ACR20 response at 24 weeks compared with placebo (68.4% vs 27.1%; "
            "RR 2.52; 95% CI 2.1–3.0; p<0.001; NNT 2.4), a clinically and statistically meaningful "
            "difference. Secondary endpoints showed sustained DAS28-CRP remission at 52 weeks "
            "(41.2% vs 12.8%; HR 3.21; p<0.001). Grade 3/4 serious infections occurred in 4.7% of "
            "treated patients versus 1.1% with placebo (p=0.002), requiring pre-treatment screening. "
            "Discontinuation rates were 6.8% versus 2.3% in the placebo arm. Patients over 75 and "
            "those with eGFR less than 30 were excluded from the trial population. The findings "
            "align with EULAR 2022 treat-to-target guidance recommending bDMARD addition after "
            "failure of two conventional DMARDs."
        ),
        "findings": [
            {
                "category": "Primary",
                "finding": "ACR20 response higher with bDMARD at 24 weeks",
                "quantitative_result": "68.4% vs 27.1%; RR 2.52 (95% CI 2.1–3.0); p<0.001",
                "source_reference": "p.4, Table 2",
                "clinical_significance": "Supports second-line use after MTX failure",
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


# Paper text that contains all the numbers in the base summary
_PAPER_TEXT = (
    "n=842 patients were enrolled. ACR20 response rate: 68.4% vs 27.1%; RR 2.52 "
    "(95% CI 2.1–3.0); p<0.001. DAS28-CRP remission: 41.2% vs 12.8%; HR 3.21; p<0.001. "
    "Grade 3/4 infections: 4.7% vs 1.1% (p=0.002). Discontinuation: 6.8% vs 2.3%."
)


def test_finding_with_no_numbers_generates_warning():
    summary = _base_summary(findings=[{
        "category": "Primary",
        "finding": "ACR20 response improved",
        "quantitative_result": "statistically significant improvement",
        "source_reference": "p.4",
        "clinical_significance": "Clinically meaningful",
    }])
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("no numbers in quantitative_result" in w for w in warnings)


def test_statistic_not_in_source_generates_warning():
    summary = _base_summary(findings=[{
        "category": "Primary",
        "finding": "ACR20 response improved",
        "quantitative_result": "72.5% vs 30.1%; p<0.001",  # 72.5 and 30.1 not in paper
        "source_reference": "p.4",
        "clinical_significance": "Clinically meaningful",
    }])
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("not found verbatim" in w for w in warnings)


def test_short_executive_summary_generates_warning():
    summary = _base_summary(executive_summary="Short summary with no detail.")
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("words" in w and "100" in w for w in warnings)


def test_nonempty_confidence_flags_generates_warning():
    summary = _base_summary(confidence_flags=["Could not verify patient count on p.2"])
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("AI flagged" in w for w in warnings)


def test_missing_source_reference_generates_warning():
    summary = _base_summary(findings=[{
        "category": "Primary",
        "finding": "ACR20 response improved",
        "quantitative_result": "68.4% vs 27.1%",
        "source_reference": "",
        "clinical_significance": "Clinically meaningful",
    }])
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("source reference" in w for w in warnings)


def test_location_not_found_reference_generates_warning():
    summary = _base_summary(findings=[{
        "category": "Primary",
        "finding": "ACR20 response improved",
        "quantitative_result": "68.4% vs 27.1%",
        "source_reference": "[LOCATION NOT FOUND]",
        "clinical_significance": "Clinically meaningful",
    }])
    warnings = validate_summary(summary, _PAPER_TEXT)
    assert any("source reference" in w for w in warnings)


def test_certainty_upgrade_detected():
    paper = _PAPER_TEXT + " The drug may be associated with improved outcomes."
    summary = _base_summary(
        executive_summary=(
            "This 52-week RCT (n=842) showed bDMARD is associated with improved ACR20 response "
            "(68.4% vs 27.1%; p<0.001). Secondary endpoints also showed improvement. "
            "Serious infections occurred in 4.7% of patients. Patients over 75 were excluded. "
            "Results align with current guidelines. MSLs should note the discontinuation rate "
            "of 6.8% versus 2.3% with placebo."
        )
    )
    warnings = validate_summary(summary, paper)
    assert any("certainty upgrade" in w.lower() for w in warnings)


def test_clean_summary_returns_no_warnings():
    warnings = validate_summary(_base_summary(), _PAPER_TEXT)
    assert warnings == []
