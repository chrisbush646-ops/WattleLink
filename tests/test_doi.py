"""
Tests for the DOI verification system.
Covers: DOIVerifier methods, PubMed ingest flow, PDF extraction,
APA7 citation rendering, AI text stripping, and commercial view.
"""
import datetime
import json
import re
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.literature.models import Paper
from apps.literature.services.doi import DOIVerifier


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Efficacy of semaglutide in type 2 diabetes",
        authors=["Smith AB", "Jones CD"],
        journal="New England Journal of Medicine",
        journal_short="N Engl J Med",
        published_date=datetime.date(2023, 6, 1),
        doi="10.1056/NEJMoa2304949",
        doi_verified=True,
        doi_source=Paper.DOISource.PUBMED,
        status=Paper.Status.ASSESSED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def paper_unverified_doi(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Liraglutide cardiovascular outcomes",
        authors=["Brown EF"],
        journal="Lancet",
        published_date=datetime.date(2022, 3, 1),
        doi="10.1016/S0140-6736(22)00001-1",
        doi_verified=False,
        doi_source=Paper.DOISource.PDF_METADATA,
        status=Paper.Status.INGESTED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def paper_no_doi(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Insulin resistance mechanisms",
        authors=["Lee GH"],
        journal="Diabetes Care",
        published_date=datetime.date(2021, 9, 1),
        doi="",
        doi_verified=False,
        status=Paper.Status.INGESTED,
        source=Paper.Source.PDF_UPLOAD,
    )


CROSSREF_WORK_RESPONSE = {
    "message": {
        "DOI": "10.1056/NEJMoa2304949",
        "title": ["Efficacy of semaglutide in type 2 diabetes"],
        "container-title": ["New England Journal of Medicine"],
        "author": [
            {"family": "Smith", "given": "Alice B"},
            {"family": "Jones", "given": "Chris D"},
        ],
        "published": {"date-parts": [[2023, 6, 1]]},
    }
}

CROSSREF_SEARCH_RESPONSE = {
    "message": {
        "items": [
            {
                "DOI": "10.1056/NEJMoa2304949",
                "title": ["Efficacy of semaglutide in type 2 diabetes"],
                "score": 120.5,
            }
        ]
    }
}

CROSSREF_LOW_SCORE_RESPONSE = {
    "message": {
        "items": [
            {
                "DOI": "10.9999/unrelated",
                "title": ["A completely unrelated paper about oncology"],
                "score": 45.2,
            }
        ]
    }
}


# ── a. clean_doi: strips prefixes ─────────────────────────────────────────────

class TestCleanDoi:
    def test_strips_https_prefix(self):
        v = DOIVerifier()
        assert v.clean_doi("https://doi.org/10.1056/test") == "10.1056/test"

    def test_strips_http_prefix(self):
        v = DOIVerifier()
        assert v.clean_doi("http://doi.org/10.1056/test") == "10.1056/test"

    def test_strips_doi_colon_prefix(self):
        v = DOIVerifier()
        assert v.clean_doi("doi:10.1056/test") == "10.1056/test"

    def test_strips_DOI_colon_prefix(self):
        v = DOIVerifier()
        assert v.clean_doi("DOI:10.1056/test") == "10.1056/test"

    def test_strips_whitespace(self):
        v = DOIVerifier()
        assert v.clean_doi("  10.1056/test  ") == "10.1056/test"

    # b. clean_doi: rejects bad formats

    def test_rejects_no_10_prefix(self):
        v = DOIVerifier()
        with pytest.raises(ValueError, match="Invalid DOI format"):
            v.clean_doi("not-a-doi/at-all")

    def test_rejects_missing_slash(self):
        v = DOIVerifier()
        with pytest.raises(ValueError, match="Invalid DOI format"):
            v.clean_doi("10.1056noslash")


# ── c. verify_doi: returns is_valid=True for known DOI ────────────────────────

class TestVerifyDoi:
    @patch("apps.literature.services.doi.requests.get")
    def test_returns_valid_for_known_doi(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = CROSSREF_WORK_RESPONSE
        mock_get.return_value = mock_resp

        result = DOIVerifier().verify_doi("10.1056/NEJMoa2304949")

        assert result["is_valid"] is True
        assert result["crossref_title"] == "Efficacy of semaglutide in type 2 diabetes"
        assert result["crossref_journal"] == "New England Journal of Medicine"
        assert result["match_confidence"] == "HIGH"

    @patch("apps.literature.services.doi.requests.get")
    def test_returns_invalid_for_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = DOIVerifier().verify_doi("10.9999/does-not-exist")

        assert result["is_valid"] is False


# ── d. search_doi_by_metadata: returns DOI when score >= 80 and title sim >= 0.85 ───

class TestSearchDoiByMetadata:
    @patch("apps.literature.services.doi.requests.get")
    def test_returns_doi_when_score_above_80_and_title_matches(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = CROSSREF_SEARCH_RESPONSE
        mock_get.return_value = mock_resp

        result = DOIVerifier().search_doi_by_metadata(
            title="Efficacy of semaglutide in type 2 diabetes",
            authors="Smith AB",
            journal="NEJM",
            year="2023",
        )

        assert result["doi"] == "10.1056/NEJMoa2304949"
        assert result["confidence"] in ("HIGH", "MEDIUM")

    @patch("apps.literature.services.doi.requests.get")
    def test_returns_none_when_score_below_80(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = CROSSREF_LOW_SCORE_RESPONSE
        mock_get.return_value = mock_resp

        result = DOIVerifier().search_doi_by_metadata(
            title="Some paper title",
            authors="Lee GH",
            year="2021",
        )

        assert result["doi"] is None

    @patch("apps.literature.services.doi.requests.get")
    def test_returns_none_when_title_similarity_below_85(self, mock_get):
        high_score_bad_title = {
            "message": {
                "items": [
                    {
                        "DOI": "10.9999/wrong-paper",
                        "title": ["Cardiovascular events in heart failure patients"],
                        "score": 150.0,
                    }
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = high_score_bad_title
        mock_get.return_value = mock_resp

        # Use a unique title to avoid cache collision with the passing test above
        result = DOIVerifier().search_doi_by_metadata(
            title="Unique title about oncology immunotherapy resistance",
            authors="Lee GH",
            year="2022",
        )

        assert result["doi"] is None


# ── e. PubMed ingest: saves doi_verified=True when CrossRef confirms ──────────

class TestPubmedIngestDoiVerification:
    @patch("apps.literature.services.doi.requests.get")
    def test_apply_doi_verification_sets_verified_true(self, mock_get, db, tenant):
        """When CrossRef confirms a DOI, _apply_doi_verification marks it verified."""
        from apps.literature.views import _apply_doi_verification

        crossref_resp = MagicMock()
        crossref_resp.status_code = 200
        crossref_resp.json.return_value = {
            "message": {
                "DOI": "10.1056/NEJMoa2401234",
                "title": ["Long-term safety of TNF inhibitors in RA."],
                "container-title": ["New England Journal of Medicine"],
                "author": [{"family": "Hughes", "given": "William"}],
                "published": {"date-parts": [[2024, 3, 7]]},
            }
        }
        mock_get.return_value = crossref_resp

        paper = Paper.all_objects.create(
            tenant=tenant,
            title="Long-term safety of TNF inhibitors in RA.",
            authors=["Hughes W"],
            journal="New England Journal of Medicine",
            doi="",
            doi_verified=False,
            published_date=datetime.date(2024, 3, 7),
            status=Paper.Status.INGESTED,
            source=Paper.Source.PUBMED_OA,
        )

        _apply_doi_verification(paper, "10.1056/NEJMoa2401234", Paper.DOISource.PUBMED)

        assert paper.doi == "10.1056/NEJMoa2401234"
        assert paper.doi_verified is True
        assert paper.doi_source == Paper.DOISource.PUBMED

    @patch("apps.literature.services.doi.requests.get")
    def test_ingest_saves_doi_verified_false_when_crossref_down(self, mock_get, db, tenant):
        import requests as req_module
        mock_get.side_effect = req_module.ConnectionError("CrossRef is down")

        paper = Paper.all_objects.create(
            tenant=tenant,
            title="Test paper",
            authors=["Smith A"],
            journal="NEJM",
            doi="10.1056/test",
            doi_verified=False,
            published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.INGESTED,
            source=Paper.Source.PUBMED_OA,
        )

        from apps.literature.views import _apply_doi_verification
        _apply_doi_verification(paper, "10.1056/test", Paper.DOISource.PUBMED)

        assert paper.doi_verified is False
        assert paper.doi_source == Paper.DOISource.PUBMED
        assert paper.doi == "10.1056/test"


# ── f. PDF DOI extraction finds a DOI in first page text ─────────────────────

class TestPdfDoiExtraction:
    def test_extracts_doi_from_first_page_text(self, tmp_path):
        from apps.literature.services.pdf import extract_doi_from_pdf
        import fitz

        doi_text = "Original Investigation\nDOI: 10.1056/NEJMoa2304949\nPublished June 2023"
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), doi_text)
        doc.save(str(pdf_path))
        doc.close()

        result = extract_doi_from_pdf(str(pdf_path))
        assert result is not None
        assert result.startswith("10.")
        assert "NEJMoa2304949" in result

    def test_returns_none_when_no_doi_in_pdf(self, tmp_path):
        from apps.literature.services.pdf import extract_doi_from_pdf
        import fitz

        pdf_path = tmp_path / "nodoi.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "This paper has no DOI mentioned anywhere.")
        doc.save(str(pdf_path))
        doc.close()

        result = extract_doi_from_pdf(str(pdf_path))
        assert result is None


# ── g. APA7 citation: DOI states ─────────────────────────────────────────────

class TestApa7DoiRendering:
    def test_omits_doi_when_empty(self, db, tenant):
        paper = Paper.all_objects.create(
            tenant=tenant, title="Test", authors=["Smith A"],
            journal="Lancet", published_date=datetime.date(2023, 1, 1),
            doi="", doi_verified=False,
            status=Paper.Status.INGESTED, source=Paper.Source.PDF_UPLOAD,
        )
        citation = paper.apa7_citation()
        assert "doi.org" not in citation
        assert "10." not in citation

    def test_shows_doi_link_when_verified(self, paper):
        citation = paper.apa7_citation()
        assert "https://doi.org/10.1056/NEJMoa2304949" in citation

    def test_omits_doi_when_unverified(self, paper_unverified_doi):
        citation = paper_unverified_doi.apa7_citation()
        assert "doi.org" not in citation


# ── h. AI text stripping: DOI patterns removed from generated text ────────────

class TestAiDoiStripping:
    def test_strips_doi_from_executive_paragraph(self, db, tenant):
        from apps.summaries.services.ai_summary import apply_summary_result
        from apps.summaries.models import PaperSummary

        paper = Paper.all_objects.create(
            tenant=tenant, title="Test Paper",
            authors=["A B"], journal="J", published_date=datetime.date(2023, 1, 1),
            doi="", status=Paper.Status.INGESTED, source=Paper.Source.PDF_UPLOAD,
        )
        summary = PaperSummary.all_objects.create(tenant=tenant, paper=paper)

        data_with_doi = {
            "methodology": {"study_design": "RCT"},
            "executive_paragraph": "Drug X (see 10.1056/NEJMoa999 for details) reduced HbA1c.",
            "safety_summary": "Well tolerated.",
            "adverse_events": [],
            "limitations": [],
            "confidence_flags": [],
        }
        apply_summary_result(summary, [], data_with_doi)

        assert "10.1056" not in summary.executive_paragraph
        assert "HbA1c" in summary.executive_paragraph

    def test_strips_doi_from_safety_summary(self, db, tenant):
        from apps.summaries.services.ai_summary import apply_summary_result
        from apps.summaries.models import PaperSummary

        paper = Paper.all_objects.create(
            tenant=tenant, title="Test Paper 2",
            authors=["B C"], journal="J", published_date=datetime.date(2023, 1, 1),
            doi="", status=Paper.Status.INGESTED, source=Paper.Source.PDF_UPLOAD,
        )
        summary = PaperSummary.all_objects.create(tenant=tenant, paper=paper)

        data = {
            "methodology": {},
            "executive_paragraph": "OK.",
            "safety_summary": "See doi: 10.9999/safety-ref for adverse events.",
            "adverse_events": [],
            "limitations": [],
            "confidence_flags": [],
        }
        apply_summary_result(summary, [], data)
        assert "10.9999" not in summary.safety_summary


# ── i. Commercial view never shows unverified DOIs ────────────────────────────

class TestCommercialViewDoi:
    def test_commercial_view_omits_unverified_doi(self, db, tenant, medical_user):
        from apps.summaries.models import PaperSummary

        paper = Paper.all_objects.create(
            tenant=tenant,
            title="Unverified DOI Paper",
            authors=["Test A"],
            journal="Test Journal",
            published_date=datetime.date(2023, 1, 1),
            doi="10.9999/unverified-doi",
            doi_verified=False,
            status=Paper.Status.APPROVED,
            source=Paper.Source.PDF_UPLOAD,
        )
        PaperSummary.all_objects.create(
            tenant=tenant,
            paper=paper,
            status=PaperSummary.Status.CONFIRMED,
            confirmed_by=medical_user,
            confirmed_at=datetime.datetime(2023, 6, 1, tzinfo=datetime.timezone.utc),
        )

        # The commercial template uses: {% if s.paper.doi and s.paper.doi_verified %}
        # We verify the model-level check works correctly
        assert paper.doi_verified is False
        apa7 = paper.apa7_citation()
        assert "10.9999/unverified-doi" not in apa7
