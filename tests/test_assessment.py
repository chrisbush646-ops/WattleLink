import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.assessment.models import GradeAssessment, RobAssessment
from apps.assessment.services.ai_assessment import (
    apply_grade_result,
    apply_rob_result,
    run_ai_assessment,
)
from apps.literature.models import Paper


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Long-term safety of TNF inhibitors in RA",
        authors=["Hughes W", "Park H"],
        journal="NEJM",
        published_date=datetime.date(2024, 3, 1),
        doi="10.1056/NEJMoa2401234",
        full_text="This RCT enrolled 1,200 patients... randomisation was computer-generated...",
        status=Paper.Status.INGESTED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def grade(db, tenant, paper):
    return GradeAssessment.all_objects.create(
        tenant=tenant,
        paper=paper,
        overall_rating="Moderate",
        rob_rating="Serious",
        rob_rationale="Observational confounding risk.",
        rob_page_ref="p.3",
        inconsistency_rating="Not serious",
        inconsistency_rationale="I² = 12%.",
        inconsistency_page_ref="p.6",
        indirectness_rating="Not serious",
        indirectness_rationale="PICO match adequate.",
        indirectness_page_ref="p.2",
        imprecision_rating="Not serious",
        imprecision_rationale="n=1200, narrow CI.",
        imprecision_page_ref="p.4",
        publication_bias_rating="Undetected",
        publication_bias_rationale="Pre-registered.",
        publication_bias_page_ref="p.2",
        ai_prefilled=True,
        status=GradeAssessment.Status.AI_DRAFT,
    )


@pytest.fixture
def rob(db, tenant, paper):
    return RobAssessment.all_objects.create(
        tenant=tenant,
        paper=paper,
        overall_judgment="Some concerns",
        d1_judgment="Low",
        d1_rationale="Computer-generated sequence.",
        d1_page_ref="p.3",
        d2_judgment="Some concerns",
        d2_rationale="Open-label design.",
        d2_page_ref="p.3",
        d3_judgment="Low",
        d3_rationale="98% completeness.",
        d3_page_ref="p.4",
        d4_judgment="Low",
        d4_rationale="Blinded adjudication.",
        d4_page_ref="p.4",
        d5_judgment="Low",
        d5_rationale="Pre-registered analysis.",
        d5_page_ref="p.2",
        ai_prefilled=True,
        status=RobAssessment.Status.AI_DRAFT,
    )


MOCK_AI_RESPONSE = {
    "grade": {
        "overall_rating": "High",
        "rob": {"rating": "Not serious", "rationale": "RCT with low bias.", "page_ref": "p.3"},
        "inconsistency": {"rating": "Not serious", "rationale": "I² = 5%.", "page_ref": "p.6"},
        "indirectness": {"rating": "Not serious", "rationale": "Direct population.", "page_ref": "p.2"},
        "imprecision": {"rating": "Not serious", "rationale": "Adequate sample.", "page_ref": "p.4"},
        "publication_bias": {"rating": "Undetected", "rationale": "Pre-registered.", "page_ref": "p.2"},
    },
    "rob": {
        "overall_judgment": "Low",
        "d1": {"judgment": "Low", "rationale": "Centralised randomisation.", "page_ref": "p.3"},
        "d2": {"judgment": "Low", "rationale": "Double-blind.", "page_ref": "p.3"},
        "d3": {"judgment": "Low", "rationale": "99% complete.", "page_ref": "p.4"},
        "d4": {"judgment": "Low", "rationale": "Blinded assessors.", "page_ref": "p.4"},
        "d5": {"judgment": "Low", "rationale": "Pre-registered.", "page_ref": "p.2"},
    },
}


# ── Model tests ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGradeAssessmentModel:
    def test_create(self, grade):
        assert grade.pk is not None
        assert grade.overall_rating == "Moderate"
        assert grade.status == GradeAssessment.Status.AI_DRAFT

    def test_domains_property_returns_five_tuples(self, grade):
        domains = grade.domains
        assert len(domains) == 5
        labels = [d[0] for d in domains]
        assert "Risk of Bias" in labels
        assert "Publication Bias" in labels

    def test_one_to_one_enforced(self, db, tenant, paper, grade):
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            GradeAssessment.all_objects.create(
                tenant=tenant,
                paper=paper,
                status=GradeAssessment.Status.AI_DRAFT,
            )

    def test_str(self, grade):
        assert "GRADE" in str(grade)
        assert "Moderate" in str(grade)


@pytest.mark.django_db
class TestRobAssessmentModel:
    def test_create(self, rob):
        assert rob.pk is not None
        assert rob.overall_judgment == "Some concerns"
        assert rob.status == RobAssessment.Status.AI_DRAFT

    def test_domains_property_returns_five_tuples(self, rob):
        domains = rob.domains
        assert len(domains) == 5
        prefixes = [d[0] for d in domains]
        assert "d1" in prefixes
        assert "d5" in prefixes

    def test_domain_labels_are_correct(self, rob):
        labels = [d[1] for d in rob.domains]
        assert "Randomisation process" in labels
        assert "Selection of the reported result" in labels

    def test_one_to_one_enforced(self, db, tenant, paper, rob):
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            RobAssessment.all_objects.create(
                tenant=tenant,
                paper=paper,
                status=RobAssessment.Status.AI_DRAFT,
            )

    def test_str(self, rob):
        assert "RoB 2" in str(rob)


# ── AI service tests ──────────────────────────────────────────────────────────

class TestAiAssessmentService:
    def _mock_claude(self, payload: dict):
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(payload))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        return mock_client

    @pytest.mark.django_db
    def test_run_ai_assessment_returns_dict(self, paper):
        mock_client = self._mock_claude(MOCK_AI_RESPONSE)
        with patch("apps.assessment.services.ai_assessment.anthropic.Anthropic", return_value=mock_client):
            result = run_ai_assessment(paper)
        assert "grade" in result
        assert "rob" in result

    @pytest.mark.django_db
    def test_apply_grade_result_maps_fields(self, tenant, paper):
        grade = GradeAssessment(tenant=tenant, paper=paper)
        apply_grade_result(grade, MOCK_AI_RESPONSE["grade"])
        assert grade.overall_rating == "High"
        assert grade.rob_rating == "Not serious"
        assert grade.inconsistency_rationale == "I² = 5%."
        assert grade.publication_bias_rating == "Undetected"
        assert grade.ai_prefilled is True

    @pytest.mark.django_db
    def test_apply_rob_result_maps_fields(self, tenant, paper):
        rob = RobAssessment(tenant=tenant, paper=paper)
        apply_rob_result(rob, MOCK_AI_RESPONSE["rob"])
        assert rob.overall_judgment == "Low"
        assert rob.d1_judgment == "Low"
        assert rob.d2_rationale == "Double-blind."
        assert rob.d5_page_ref == "p.2"
        assert rob.ai_prefilled is True

    @pytest.mark.django_db
    def test_strips_markdown_fences(self, paper):
        wrapped = f"```json\n{json.dumps(MOCK_AI_RESPONSE)}\n```"
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=wrapped)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch("apps.assessment.services.ai_assessment.anthropic.Anthropic", return_value=mock_client):
            result = run_ai_assessment(paper)

        assert result["grade"]["overall_rating"] == "High"

    @pytest.mark.django_db
    def test_no_text_raises(self, tenant):
        empty_paper = Paper.all_objects.create(
            tenant=tenant,
            title="",
            authors=[],
            journal="",
            status=Paper.Status.INGESTED,
            source=Paper.Source.MANUAL,
        )
        with pytest.raises(ValueError, match="no text to assess"):
            run_ai_assessment(empty_paper)


# ── View tests ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAssessmentViews:
    @pytest.fixture(autouse=True)
    def setup(self, client, medical_user, tenant):
        from apps.accounts.managers import set_current_tenant
        set_current_tenant(tenant)
        client.force_login(medical_user)
        self.client = client
        self.tenant = tenant
        yield
        set_current_tenant(None)

    def test_panel_returns_200(self, paper):
        url = reverse("assessment:panel", args=[paper.pk])
        resp = self.client.get(url)
        assert resp.status_code == 200

    def test_panel_shows_empty_state_when_no_assessment(self, paper):
        url = reverse("assessment:panel", args=[paper.pk])
        resp = self.client.get(url)
        assert b"No assessment yet" in resp.content

    def test_panel_shows_grade_data_when_present(self, paper, grade, rob):
        url = reverse("assessment:panel", args=[paper.pk])
        resp = self.client.get(url)
        assert b"Moderate" in resp.content
        assert b"GRADE" in resp.content

    def test_confirm_advances_paper_status(self, paper, grade, rob):
        url = reverse("assessment:confirm", args=[paper.pk])
        payload = {
            "grade": {"overall_rating": "High"},
            "rob": {"overall_judgment": "Low"},
        }
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        paper.refresh_from_db()
        assert paper.status == Paper.Status.ASSESSED
        assert paper.grade_rating == "High"

    def test_confirm_sets_grade_confirmed(self, paper, grade, rob):
        url = reverse("assessment:confirm", args=[paper.pk])
        payload = {"grade": {"overall_rating": "Moderate"}, "rob": {"overall_judgment": "Some concerns"}}
        self.client.post(url, data=json.dumps(payload), content_type="application/json")

        grade.refresh_from_db()
        assert grade.status == GradeAssessment.Status.CONFIRMED
        assert grade.confirmed_by is not None

    def test_confirm_sets_rob_confirmed(self, paper, grade, rob):
        url = reverse("assessment:confirm", args=[paper.pk])
        payload = {"grade": {"overall_rating": "Low"}, "rob": {"overall_judgment": "High"}}
        self.client.post(url, data=json.dumps(payload), content_type="application/json")

        rob.refresh_from_db()
        assert rob.status == RobAssessment.Status.CONFIRMED

    def test_confirm_writes_audit_log(self, paper, grade, rob):
        from apps.audit.models import AuditLog
        url = reverse("assessment:confirm", args=[paper.pk])
        payload = {"grade": {"overall_rating": "High"}, "rob": {"overall_judgment": "Low"}}
        self.client.post(url, data=json.dumps(payload), content_type="application/json")

        log = AuditLog.objects.filter(
            entity_type="Paper",
            entity_id=paper.pk,
            action=AuditLog.Action.UPDATE,
        ).first()
        assert log is not None

    def test_run_ai_returns_processing_partial(self, paper):
        url = reverse("assessment:run_ai", args=[paper.pk])
        with patch("apps.assessment.tasks.run_ai_assessment_task") as mock_task:
            mock_task.delay = MagicMock()
            resp = self.client.post(url)
        assert resp.status_code == 200
        assert b"Running AI assessment" in resp.content

    def test_wrong_tenant_paper_returns_404(self, db):
        from apps.accounts.models import Tenant
        other_tenant = Tenant.objects.create(name="Other", slug="other")
        other_paper = Paper.all_objects.create(
            tenant=other_tenant,
            title="Other paper",
            authors=[],
            journal="",
            status=Paper.Status.INGESTED,
            source=Paper.Source.MANUAL,
        )
        url = reverse("assessment:panel", args=[other_paper.pk])
        resp = self.client.get(url)
        assert resp.status_code == 404
