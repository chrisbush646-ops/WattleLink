import datetime
import io
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.claims.models import CoreClaim
from apps.export.models import ExportPackage
from apps.export.services.annotate import annotate_pdf, build_metadata_snapshot
from apps.literature.models import Paper


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Export test paper",
        authors=["Smith A"],
        journal="NEJM",
        published_date=datetime.date(2024, 6, 1),
        doi="10.1056/export_test_001",
        full_text="Drug X reduced HbA1c by 1.2% vs placebo (p<0.001).",
        status=Paper.Status.CLAIMS_GENERATED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def approved_claim(db, tenant, paper, medical_user):
    from django.utils import timezone
    return CoreClaim.all_objects.create(
        tenant=tenant,
        paper=paper,
        claim_text="Drug X reduced HbA1c by 1.2% vs placebo (p<0.001).",
        endpoint_type=CoreClaim.EndpointType.PRIMARY,
        source_passage="Drug X reduced HbA1c by 1.2% vs placebo.",
        source_reference="p.4, Table 2",
        fair_balance="Study limited to 24 weeks.",
        fair_balance_reference="p.10",
        fidelity_checklist={
            "verbatim_data": True, "population_match": True,
            "endpoint_match": True, "no_extrapolation": True,
            "fair_balance_present": True,
        },
        status=CoreClaim.Status.APPROVED,
        reviewed_by=medical_user,
        reviewed_at=timezone.now(),
    )


@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


def _minimal_pdf() -> bytes:
    """Return a minimal valid PDF as bytes."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Drug X reduced HbA1c by 1.2% vs placebo.", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ── Annotation service tests ──────────────────────────────────────────────────

class TestAnnotatePdf:
    def test_returns_bytes_for_valid_pdf(self, approved_claim):
        pdf = _minimal_pdf()
        result = annotate_pdf(pdf, [approved_claim])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_returns_original_on_empty_bytes(self, approved_claim):
        result = annotate_pdf(b"", [approved_claim])
        assert result == b""

    def test_returns_original_on_invalid_pdf(self, approved_claim):
        result = annotate_pdf(b"not a pdf", [approved_claim])
        assert result == b"not a pdf"

    def test_no_claims_returns_unannotated(self):
        pdf = _minimal_pdf()
        result = annotate_pdf(pdf, [])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_claim_with_no_passage_skipped(self, db, tenant, paper, medical_user):
        from django.utils import timezone
        claim = CoreClaim.all_objects.create(
            tenant=tenant, paper=paper,
            claim_text="No passage.", endpoint_type="PRIMARY",
            source_passage="",
            status=CoreClaim.Status.APPROVED,
            reviewed_by=medical_user, reviewed_at=timezone.now(),
        )
        pdf = _minimal_pdf()
        result = annotate_pdf(pdf, [claim])
        assert isinstance(result, bytes)


class TestBuildMetadataSnapshot:
    def test_contains_paper_and_claims(self, paper, approved_claim):
        snapshot = build_metadata_snapshot(paper, [approved_claim])
        assert snapshot["paper"]["id"] == paper.pk
        assert snapshot["paper"]["doi"] == paper.doi
        assert len(snapshot["claims"]) == 1
        assert snapshot["claims"][0]["id"] == approved_claim.pk

    def test_empty_claims(self, paper):
        snapshot = build_metadata_snapshot(paper, [])
        assert snapshot["claims"] == []

    def test_reviewed_by_email_included(self, paper, approved_claim, medical_user):
        snapshot = build_metadata_snapshot(paper, [approved_claim])
        assert snapshot["claims"][0]["reviewed_by"] == medical_user.email


# ── Model tests ───────────────────────────────────────────────────────────────

class TestExportPackageModel:
    def test_str(self, db, tenant, paper, medical_user):
        pkg = ExportPackage.objects.create(
            tenant=tenant, paper=paper, created_by=medical_user
        )
        assert "Export #" in str(pkg)

    def test_default_status_pending(self, db, tenant, paper, medical_user):
        pkg = ExportPackage.objects.create(
            tenant=tenant, paper=paper, created_by=medical_user
        )
        assert pkg.status == ExportPackage.Status.PENDING

    def test_tenant_isolation(self, db, tenant, paper, medical_user):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant

        ExportPackage.objects.create(tenant=tenant, paper=paper, created_by=medical_user)
        other = Tenant.objects.create(name="Other", slug="other-exp")
        set_current_tenant(other)
        try:
            assert ExportPackage.objects.count() == 0
        finally:
            set_current_tenant(None)


# ── View tests ────────────────────────────────────────────────────────────────

class TestExportPanelView:
    def test_empty_state_no_approved_claims(self, client, paper):
        resp = client.get(reverse("export:panel", args=[paper.pk]))
        assert resp.status_code == 200
        assert b"No approved claims" in resp.content

    def test_shows_approved_claims(self, client, paper, approved_claim):
        resp = client.get(reverse("export:panel", args=[paper.pk]))
        assert resp.status_code == 200
        assert b"Generate Export" in resp.content

    def test_other_tenant_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other", slug="other-ep")
        p = Paper.all_objects.create(
            tenant=other, title="X", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.CLAIMS_GENERATED, source=Paper.Source.PDF_UPLOAD,
        )
        resp = client.get(reverse("export:panel", args=[p.pk]))
        assert resp.status_code == 404


class TestCreateExportView:
    @patch("apps.export.tasks.build_export_package_task")
    def test_creates_package_and_returns_spinner(self, mock_task, client, paper, approved_claim):
        mock_task.delay.return_value = None
        resp = client.post(reverse("export:create", args=[paper.pk]))
        assert resp.status_code == 200
        assert b"Building export" in resp.content
        assert ExportPackage.objects.filter(paper=paper).exists()

    @patch("apps.export.tasks.build_export_package_task")
    def test_dispatches_task(self, mock_task, client, paper, approved_claim):
        mock_task.delay.return_value = None
        client.post(reverse("export:create", args=[paper.pk]))
        assert mock_task.delay.called

    def test_no_approved_claims_returns_error(self, client, paper):
        resp = client.post(reverse("export:create", args=[paper.pk]))
        assert resp.status_code == 200
        assert b"No approved claims" in resp.content
        assert not ExportPackage.objects.filter(paper=paper).exists()

    def test_get_not_allowed(self, client, paper):
        resp = client.get(reverse("export:create", args=[paper.pk]))
        assert resp.status_code == 405


class TestPollExportView:
    def test_returns_spinner_while_processing(self, client, paper, medical_user):
        pkg = ExportPackage.objects.create(
            tenant=paper.tenant, paper=paper, created_by=medical_user,
            status=ExportPackage.Status.PROCESSING,
        )
        resp = client.get(reverse("export:poll", args=[pkg.pk]))
        assert resp.status_code == 200
        assert b"Building export" in resp.content

    def test_returns_panel_when_ready(self, client, paper, medical_user, approved_claim):
        pkg = ExportPackage.objects.create(
            tenant=paper.tenant, paper=paper, created_by=medical_user,
            status=ExportPackage.Status.READY, claim_count=1,
        )
        resp = client.get(reverse("export:poll", args=[pkg.pk]))
        assert resp.status_code == 200
        assert b"export-panel" in resp.content
