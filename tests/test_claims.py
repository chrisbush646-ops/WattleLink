import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.claims.models import CoreClaim
from apps.claims.services.extraction import extract_claims
from apps.literature.models import Paper


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Phase III trial of Drug X in T2DM",
        authors=["Smith A", "Jones B"],
        journal="NEJM",
        published_date=datetime.date(2024, 6, 1),
        doi="10.1056/claims_test_001",
        full_text="This double-blind RCT enrolled 800 patients. Primary endpoint: HbA1c at 24 weeks...",
        status=Paper.Status.SUMMARISED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def draft_claim(db, tenant, paper):
    return CoreClaim.all_objects.create(
        tenant=tenant,
        paper=paper,
        claim_text="Drug X reduced HbA1c by 1.2% vs placebo (p<0.001, 95% CI -1.5 to -0.9).",
        endpoint_type=CoreClaim.EndpointType.PRIMARY,
        source_passage="The primary endpoint HbA1c reduction was -1.2% (p<0.001).",
        source_reference="p.4, Table 2",
        fair_balance="The study was 24 weeks; long-term safety data are limited.",
        fair_balance_reference="p.10, Limitations",
        fidelity_checklist={
            "verbatim_data": True,
            "population_match": True,
            "endpoint_match": True,
            "no_extrapolation": True,
            "fair_balance_present": True,
            "approved_indication_only": True,
        },
        status=CoreClaim.Status.AI_DRAFT,
    )


@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


AI_RESPONSE = {
    "claims": [
        {
            "claim_text": "Drug X reduced HbA1c by 1.2% vs placebo (p<0.001).",
            "endpoint_type": "PRIMARY",
            "source_passage": "The primary endpoint HbA1c was reduced by 1.2%.",
            "source_reference": "p.4, Table 2",
            "fair_balance": "Study duration limited to 24 weeks.",
            "fair_balance_reference": "p.10",
            "fidelity_checklist": {
                "verbatim_data": True,
                "population_match": True,
                "endpoint_match": True,
                "no_extrapolation": True,
                "fair_balance_present": True,
            },
        }
    ]
}


# ── Model tests ───────────────────────────────────────────────────────────────

class TestCoreClaimModel:
    def test_str(self, draft_claim):
        assert "Drug X" in str(draft_claim)

    def test_fidelity_complete_true(self, draft_claim):
        assert draft_claim.fidelity_complete is True

    def test_fidelity_complete_false_when_missing(self, db, tenant, paper):
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="Test.",
            endpoint_type=CoreClaim.EndpointType.PRIMARY,
            fair_balance="Some balance.",
            fidelity_checklist={"verbatim_data": True, "population_match": False},
        )
        assert claim.fidelity_complete is False

    def test_fidelity_complete_false_when_empty(self, db, tenant, paper):
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="Test.",
            endpoint_type=CoreClaim.EndpointType.PRIMARY,
            fidelity_checklist={},
        )
        assert claim.fidelity_complete is False

    def test_default_status_ai_draft(self, db, tenant, paper):
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="Test.", endpoint_type="PRIMARY",
        )
        assert claim.status == CoreClaim.Status.AI_DRAFT

    def test_version_default_one(self, draft_claim):
        assert draft_claim.version == 1


class TestClaimTenantIsolation:
    def test_other_tenant_excluded(self, db, draft_claim):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other Co", slug="other-claims")
        set_current_tenant(other)
        try:
            assert CoreClaim.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_own_tenant_visible(self, db, tenant, draft_claim):
        from apps.accounts.managers import set_current_tenant

        set_current_tenant(tenant)
        try:
            assert CoreClaim.objects.count() == 1
        finally:
            set_current_tenant(None)

    def test_soft_deleted_claim_excluded(self, db, tenant, draft_claim):
        from apps.accounts.managers import set_current_tenant
        from django.utils import timezone

        draft_claim.deleted_at = timezone.now()
        draft_claim.save(update_fields=["deleted_at"])

        set_current_tenant(tenant)
        try:
            assert CoreClaim.objects.count() == 0
        finally:
            set_current_tenant(None)


# ── AI service tests ──────────────────────────────────────────────────────────

class TestExtractClaims:
    @patch("apps.claims.services.extraction.anthropic.Anthropic")
    def test_returns_claims_list(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(AI_RESPONSE))]
        )
        result = extract_claims(paper)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["endpoint_type"] == "PRIMARY"

    @patch("apps.claims.services.extraction.anthropic.Anthropic")
    def test_strips_markdown_fences(self, mock_anthropic, paper):
        fenced = f"```json\n{json.dumps(AI_RESPONSE)}\n```"
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=fenced)]
        )
        result = extract_claims(paper)
        assert len(result) == 1

    @patch("apps.claims.services.extraction.anthropic.Anthropic")
    def test_empty_claims_array(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps({"claims": []}))]
        )
        result = extract_claims(paper)
        assert result == []

    def test_no_text_raises(self, db, tenant):
        paper = Paper.all_objects.create(
            tenant=tenant, title="", authors=[],
            journal="X", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.SUMMARISED, source=Paper.Source.PDF_UPLOAD,
        )
        with pytest.raises(ValueError, match="no text"):
            extract_claims(paper)

    @patch("apps.claims.services.extraction.anthropic.Anthropic")
    def test_raises_on_bad_json(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text="not valid json")]
        )
        with pytest.raises(json.JSONDecodeError):
            extract_claims(paper)


# ── View tests ────────────────────────────────────────────────────────────────

class TestClaimsPanelView:
    def test_empty_state_no_claims(self, client, paper):
        url = reverse("claims:panel", args=[paper.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"No claims yet" in resp.content

    def test_shows_existing_claims(self, client, paper, draft_claim):
        url = reverse("claims:panel", args=[paper.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"Drug X" in resp.content

    def test_other_tenant_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Rival", slug="rival-claims")
        paper2 = Paper.all_objects.create(
            tenant=other, title="Other", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.SUMMARISED, source=Paper.Source.PDF_UPLOAD,
        )
        resp = client.get(reverse("claims:panel", args=[paper2.pk]))
        assert resp.status_code == 404


class TestRunExtractionView:
    @patch("apps.claims.tasks.extract_claims_task")
    def test_returns_spinner(self, mock_task, client, paper):
        fake_task = MagicMock()
        fake_task.id = "test-extract-task-1234"
        mock_task.delay.return_value = fake_task
        resp = client.post(reverse("claims:run_extraction", args=[paper.pk]))
        assert resp.status_code == 200
        assert b"Extracting claims" in resp.content

    @patch("apps.claims.tasks.extract_claims_task")
    def test_dispatches_task(self, mock_task, client, paper, tenant):
        fake_task = MagicMock()
        fake_task.id = "test-extract-task-5678"
        mock_task.delay.return_value = fake_task
        client.post(reverse("claims:run_extraction", args=[paper.pk]))
        mock_task.delay.assert_called_once_with(paper.pk, tenant.pk)

    def test_get_not_allowed(self, client, paper):
        resp = client.get(reverse("claims:run_extraction", args=[paper.pk]))
        assert resp.status_code == 405


class TestApproveClaimView:
    def test_approves_complete_claim(self, client, draft_claim, paper, medical_user):
        resp = client.post(reverse("claims:approve", args=[draft_claim.pk]))
        assert resp.status_code == 200
        draft_claim.refresh_from_db()
        assert draft_claim.status == CoreClaim.Status.APPROVED
        assert draft_claim.reviewed_by == medical_user

    def test_advances_paper_to_claims_generated(self, client, draft_claim, paper):
        assert paper.status == Paper.Status.SUMMARISED
        client.post(reverse("claims:approve", args=[draft_claim.pk]))
        paper.refresh_from_db()
        assert paper.status == Paper.Status.CLAIMS_GENERATED

    def test_blocks_approval_without_fidelity(self, db, client, tenant, paper):
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="Incomplete.", endpoint_type="PRIMARY",
            fair_balance="Some balance.",
            fidelity_checklist={"verbatim_data": False},
        )
        resp = client.post(reverse("claims:approve", args=[claim.pk]))
        assert resp.status_code == 200
        claim.refresh_from_db()
        assert claim.status == CoreClaim.Status.AI_DRAFT

    def test_blocks_approval_without_fair_balance(self, db, client, tenant, paper):
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="No fair balance.", endpoint_type="PRIMARY",
            fair_balance="",
            fidelity_checklist={
                "verbatim_data": True, "population_match": True,
                "endpoint_match": True, "no_extrapolation": True,
                "fair_balance_present": True,
            },
        )
        resp = client.post(reverse("claims:approve", args=[claim.pk]))
        assert resp.status_code == 200
        claim.refresh_from_db()
        assert claim.status == CoreClaim.Status.AI_DRAFT

    def test_other_tenant_claim_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other", slug="other-approve")
        other_paper = Paper.all_objects.create(
            tenant=other, title="X", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.SUMMARISED, source=Paper.Source.PDF_UPLOAD,
        )
        claim = CoreClaim.all_objects.create(
            tenant=other, paper=other_paper,
            claim_text="X.", endpoint_type="PRIMARY",
        )
        resp = client.post(reverse("claims:approve", args=[claim.pk]))
        assert resp.status_code == 404


class TestRejectClaimView:
    def test_rejects_with_reason(self, client, draft_claim, medical_user):
        resp = client.post(
            reverse("claims:reject", args=[draft_claim.pk]),
            data=json.dumps({"reason": "Extrapolates beyond study population."}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_claim.refresh_from_db()
        assert draft_claim.status == CoreClaim.Status.REJECTED
        assert draft_claim.reviewed_by == medical_user
        assert "Extrapolates" in draft_claim.rejection_reason

    def test_requires_reason(self, client, draft_claim):
        resp = client.post(
            reverse("claims:reject", args=[draft_claim.pk]),
            data=json.dumps({"reason": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_claim.refresh_from_db()
        assert draft_claim.status == CoreClaim.Status.AI_DRAFT


class TestEditClaimView:
    def _payload(self, claim, **overrides):
        base = {
            "claim_text": claim.claim_text,
            "endpoint_type": claim.endpoint_type,
            "source_passage": claim.source_passage,
            "source_reference": claim.source_reference,
            "fair_balance": claim.fair_balance,
            "fair_balance_reference": claim.fair_balance_reference,
            "fidelity_checklist": claim.fidelity_checklist,
        }
        base.update(overrides)
        return base

    def test_saves_edits_and_bumps_version(self, client, draft_claim):
        resp = client.post(
            reverse("claims:edit", args=[draft_claim.pk]),
            data=json.dumps(self._payload(draft_claim, claim_text="Updated claim text.")),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_claim.refresh_from_db()
        assert draft_claim.claim_text == "Updated claim text."
        assert draft_claim.version == 2

    def test_rejected_claim_moves_to_in_review(self, client, draft_claim):
        draft_claim.status = CoreClaim.Status.REJECTED
        draft_claim.rejection_reason = "Too broad."
        draft_claim.save()

        client.post(
            reverse("claims:edit", args=[draft_claim.pk]),
            data=json.dumps(self._payload(draft_claim, claim_text="Narrowed claim.")),
            content_type="application/json",
        )
        draft_claim.refresh_from_db()
        assert draft_claim.status == CoreClaim.Status.IN_REVIEW
        assert draft_claim.rejection_reason == ""

    def test_approved_claim_cannot_be_edited(self, client, draft_claim, medical_user):
        from django.utils import timezone
        draft_claim.status = CoreClaim.Status.APPROVED
        draft_claim.reviewed_by = medical_user
        draft_claim.reviewed_at = timezone.now()
        draft_claim.save()

        resp = client.post(
            reverse("claims:edit", args=[draft_claim.pk]),
            data=json.dumps(self._payload(draft_claim, claim_text="Sneaky edit.")),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_claim.refresh_from_db()
        assert "Drug X" in draft_claim.claim_text  # unchanged
