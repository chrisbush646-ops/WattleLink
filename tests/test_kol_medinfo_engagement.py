import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.engagement.models import Conference, RoundTable
from apps.kol.models import KOL, KOLCandidate, KOLPaperLink
from apps.kol.services.discovery import discover_kols
from apps.literature.models import Paper
from apps.medinfo.models import Enquiry


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant, title="RCT of Drug X", authors=["Smith A", "Jones B"],
        journal="NEJM", published_date=datetime.date(2024, 6, 1),
        doi="10.1056/kol_test", full_text="Smith A, Jones B. This RCT...",
        status=Paper.Status.APPROVED, source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def kol(db, tenant, medical_user):
    return KOL.objects.create(
        tenant=tenant, name="Prof. Jane Smith", institution="Royal Melbourne Hospital",
        specialty="Endocrinology", tier=2, status=KOL.Status.ACTIVE,
        created_by=medical_user,
    )


@pytest.fixture
def enquiry(db, tenant, medical_user):
    return Enquiry.objects.create(
        tenant=tenant,
        question="What is the recommended dose of Drug X in renal impairment?",
        source=Enquiry.Source.HCP,
        created_by=medical_user,
    )


@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


# ════════════════════════════════════════════════════════════════════════════════
# KOL
# ════════════════════════════════════════════════════════════════════════════════

class TestKOLModel:
    def test_str(self, kol):
        assert str(kol) == "Prof. Jane Smith"

    def test_default_status_candidate(self, db, tenant):
        k = KOL.objects.create(tenant=tenant, name="New KOL")
        assert k.status == KOL.Status.CANDIDATE

    def test_tenant_isolation(self, db, kol):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant
        other = Tenant.objects.create(name="Other", slug="other-kol")
        set_current_tenant(other)
        try:
            assert KOL.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_soft_deleted_excluded(self, db, tenant, kol):
        from apps.accounts.managers import set_current_tenant
        from django.utils import timezone
        kol.deleted_at = timezone.now()
        kol.save(update_fields=["deleted_at"])
        set_current_tenant(tenant)
        try:
            assert KOL.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_paper_link_unique_together(self, db, kol, paper, medical_user):
        KOLPaperLink.objects.create(kol=kol, paper=paper)
        with pytest.raises(Exception):
            KOLPaperLink.objects.create(kol=kol, paper=paper)


class TestKOLDiscoveryService:
    AI_RESPONSE = {
        "candidates": [
            {
                "name": "Prof. Jane Smith", "institution": "RMH",
                "specialty": "Endocrinology", "tier": 1, "location": "Melbourne, AU",
                "bio": "Leading researcher.", "is_author": True,
                "relevance_note": "Corresponding author.",
            }
        ]
    }

    @patch("apps.kol.services.discovery.anthropic.Anthropic")
    def test_returns_candidates(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(self.AI_RESPONSE))]
        )
        result = discover_kols(paper)
        assert len(result) == 1
        assert result[0]["name"] == "Prof. Jane Smith"

    @patch("apps.kol.services.discovery.anthropic.Anthropic")
    def test_strips_fences(self, mock_anthropic, paper):
        fenced = f"```json\n{json.dumps(self.AI_RESPONSE)}\n```"
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=fenced)]
        )
        result = discover_kols(paper)
        assert len(result) == 1

    def test_no_text_raises(self, db, tenant):
        p = Paper.all_objects.create(
            tenant=tenant, title="", authors=[], journal="X",
            published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.APPROVED, source=Paper.Source.PDF_UPLOAD,
        )
        with pytest.raises(ValueError):
            discover_kols(p)


class TestKOLViews:
    def test_list_renders(self, client, kol):
        resp = client.get(reverse("kol:list"))
        assert resp.status_code == 200
        assert b"Prof. Jane Smith" in resp.content

    def test_detail_renders(self, client, kol):
        resp = client.get(reverse("kol:detail", args=[kol.pk]))
        assert resp.status_code == 200
        assert b"Prof. Jane Smith" in resp.content

    def test_detail_other_tenant_404(self, db, client):
        from apps.accounts.models import Tenant
        other = Tenant.objects.create(name="Other", slug="other-kd")
        k = KOL.objects.create(tenant=other, name="X")
        resp = client.get(reverse("kol:detail", args=[k.pk]))
        assert resp.status_code == 404

    def test_create_kol(self, client, tenant):
        resp = client.post(
            reverse("kol:create"),
            data=json.dumps({"name": "New KOL", "tier": 3}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert KOL.objects.filter(name="New KOL").exists()

    def test_create_kol_requires_name(self, client):
        resp = client.post(
            reverse("kol:create"),
            data=json.dumps({"name": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert not KOL.objects.filter(name="").exists()

    def test_update_kol(self, client, kol):
        resp = client.post(
            reverse("kol:update", args=[kol.pk]),
            data=json.dumps({"tier": 1, "status": "ACTIVE"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        kol.refresh_from_db()
        assert kol.tier == 1

    def test_link_paper(self, client, kol, paper):
        resp = client.post(
            reverse("kol:link_paper", args=[kol.pk]),
            data=json.dumps({"paper_pk": paper.pk, "is_author": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert KOLPaperLink.objects.filter(kol=kol, paper=paper).exists()

    def test_unlink_paper(self, client, kol, paper):
        link = KOLPaperLink.objects.create(kol=kol, paper=paper)
        resp = client.post(reverse("kol:unlink_paper", args=[link.pk]))
        assert resp.status_code == 200
        assert not KOLPaperLink.objects.filter(pk=link.pk).exists()

    @patch("apps.kol.tasks.discover_kols_task")
    def test_discover_queues_task(self, mock_task, client, paper, tenant):
        mock_task.delay.return_value = None
        resp = client.post(reverse("kol:discover", args=[paper.pk]))
        assert resp.status_code == 200
        mock_task.delay.assert_called_once_with(paper.pk, tenant.pk)

    def test_filter_by_location(self, client, db, tenant, medical_user):
        KOL.objects.create(tenant=tenant, name="Dr Melbourne", location="Melbourne, VIC",
                           specialty="Cardiology", created_by=medical_user)
        KOL.objects.create(tenant=tenant, name="Dr Sydney", location="Sydney, NSW",
                           specialty="Oncology", created_by=medical_user)
        resp = client.get(reverse("kol:list"), {"location": "Melbourne"},
                          HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert b"Dr Melbourne" in resp.content
        assert b"Dr Sydney" not in resp.content

    def test_filter_by_specialty(self, client, db, tenant, medical_user):
        KOL.objects.create(tenant=tenant, name="Dr Endo", location="Brisbane",
                           specialty="Endocrinology", created_by=medical_user)
        KOL.objects.create(tenant=tenant, name="Dr Cardio", location="Perth",
                           specialty="Cardiology", created_by=medical_user)
        resp = client.get(reverse("kol:list"), {"specialty": "Endo"},
                          HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert b"Dr Endo" in resp.content
        assert b"Dr Cardio" not in resp.content

    def test_filter_combined(self, client, db, tenant, medical_user):
        KOL.objects.create(tenant=tenant, name="Dr Match", location="Adelaide, SA",
                           specialty="Endocrinology", created_by=medical_user)
        KOL.objects.create(tenant=tenant, name="Dr NoMatch", location="Darwin, NT",
                           specialty="Endocrinology", created_by=medical_user)
        resp = client.get(reverse("kol:list"), {"specialty": "Endocrinology", "location": "Adelaide"},
                          HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert b"Dr Match" in resp.content
        assert b"Dr NoMatch" not in resp.content

    def test_filter_no_results_empty_state(self, client, db, tenant):
        resp = client.get(reverse("kol:list"), {"location": "Atlantis"},
                          HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert b"No KOLs match these filters" in resp.content


class TestKOLCandidateWorkflow:
    @pytest.fixture
    def candidate(self, db, tenant, paper, medical_user):
        return KOLCandidate.objects.create(
            tenant=tenant,
            paper=paper,
            name="Dr. AI Suggested",
            institution="Monash University",
            specialty="Cardiology",
            tier=2,
            location="Melbourne, VIC",
            bio="Highly cited researcher in cardiac outcomes.",
            relevance_note="Corresponding author on included RCT.",
            is_author=True,
            verification_status=KOLCandidate.VerificationStatus.LIKELY_CURRENT,
            verification_note="Likely still at Monash based on training data.",
        )

    def test_candidate_str(self, candidate):
        assert "Dr. AI Suggested" in str(candidate)

    def test_candidate_default_status_pending(self, db, tenant, paper):
        c = KOLCandidate.objects.create(tenant=tenant, paper=paper, name="New Candidate")
        assert c.status == KOLCandidate.Status.PENDING

    def test_verification_color_likely_current(self, candidate):
        candidate.verification_status = KOLCandidate.VerificationStatus.LIKELY_CURRENT
        assert candidate.verification_color == "euc"

    def test_verification_color_uncertain(self, candidate):
        candidate.verification_status = KOLCandidate.VerificationStatus.UNCERTAIN
        assert candidate.verification_color == "wattle"

    def test_verification_color_possibly_inactive(self, candidate):
        candidate.verification_status = KOLCandidate.VerificationStatus.POSSIBLY_INACTIVE
        assert candidate.verification_color == "coral"

    def test_accept_candidate_creates_kol(self, client, candidate, tenant):
        resp = client.post(
            reverse("kol:accept_candidate", args=[candidate.pk]),
            data=json.dumps({"tier": 1}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        candidate.refresh_from_db()
        assert candidate.status == KOLCandidate.Status.ACCEPTED
        assert candidate.kol is not None
        assert KOL.objects.filter(name="Dr. AI Suggested", tenant=tenant).exists()

    def test_accept_candidate_links_paper(self, client, candidate, paper):
        client.post(
            reverse("kol:accept_candidate", args=[candidate.pk]),
            data=json.dumps({}),
            content_type="application/json",
        )
        candidate.refresh_from_db()
        assert KOLPaperLink.objects.filter(kol=candidate.kol, paper=paper).exists()

    def test_accept_idempotent_for_existing_kol(self, client, candidate, tenant, medical_user):
        existing = KOL.objects.create(tenant=tenant, name="Dr. AI Suggested", created_by=medical_user)
        client.post(
            reverse("kol:accept_candidate", args=[candidate.pk]),
            data=json.dumps({"tier": 1}),
            content_type="application/json",
        )
        assert KOL.objects.filter(name="Dr. AI Suggested", tenant=tenant).count() == 1
        existing.refresh_from_db()
        assert existing.tier == 1

    def test_reject_candidate(self, client, candidate):
        resp = client.post(
            reverse("kol:reject_candidate", args=[candidate.pk]),
            data=json.dumps({"reason": "Not relevant to our portfolio."}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        candidate.refresh_from_db()
        assert candidate.status == KOLCandidate.Status.REJECTED
        assert "Not relevant" in candidate.rejection_reason

    def test_hold_candidate(self, client, candidate):
        resp = client.post(
            reverse("kol:hold_candidate", args=[candidate.pk]),
            data=json.dumps({"reason": "Need to verify registration."}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        candidate.refresh_from_db()
        assert candidate.status == KOLCandidate.Status.ON_HOLD
        assert "verify registration" in candidate.hold_reason

    def test_candidate_verify_status_view(self, client, candidate):
        resp = client.get(reverse("kol:candidate_verify_status", args=[candidate.pk]))
        assert resp.status_code == 200
        assert b"Likely Current" in resp.content

    def test_candidate_other_tenant_404(self, db, client, paper):
        from apps.accounts.models import Tenant
        other = Tenant.objects.create(name="Other", slug="other-cand")
        c = KOLCandidate.objects.create(tenant=other, paper=paper, name="Foreign Candidate")
        resp = client.post(
            reverse("kol:accept_candidate", args=[c.pk]),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_candidate_list_shows_pending_count(self, client, candidate):
        resp = client.get(reverse("kol:list"))
        assert resp.status_code == 200
        assert b"AI Suggestions" in resp.content


# ════════════════════════════════════════════════════════════════════════════════
# Medical Information
# ════════════════════════════════════════════════════════════════════════════════

class TestEnquiryModel:
    def test_str(self, enquiry):
        assert "renal impairment" in str(enquiry)

    def test_default_status_open(self, db, tenant, medical_user):
        e = Enquiry.objects.create(tenant=tenant, question="Test?", created_by=medical_user)
        assert e.status == Enquiry.Status.OPEN

    def test_tenant_isolation(self, db, enquiry):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant
        other = Tenant.objects.create(name="Other", slug="other-enq")
        set_current_tenant(other)
        try:
            assert Enquiry.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_soft_deleted_excluded(self, db, tenant, enquiry):
        from apps.accounts.managers import set_current_tenant
        from django.utils import timezone
        enquiry.deleted_at = timezone.now()
        enquiry.save(update_fields=["deleted_at"])
        set_current_tenant(tenant)
        try:
            assert Enquiry.objects.count() == 0
        finally:
            set_current_tenant(None)


class TestEnquiryViews:
    def test_list_renders(self, client, enquiry):
        resp = client.get(reverse("medinfo:list"))
        assert resp.status_code == 200
        assert b"renal impairment" in resp.content

    def test_detail_renders(self, client, enquiry):
        resp = client.get(reverse("medinfo:detail", args=[enquiry.pk]))
        assert resp.status_code == 200
        assert b"renal impairment" in resp.content

    def test_detail_other_tenant_404(self, db, client):
        from apps.accounts.models import Tenant
        other = Tenant.objects.create(name="Other", slug="other-mi")
        e = Enquiry.objects.create(tenant=other, question="X?")
        resp = client.get(reverse("medinfo:detail", args=[e.pk]))
        assert resp.status_code == 404

    def test_create_enquiry(self, client, tenant):
        resp = client.post(
            reverse("medinfo:create"),
            data=json.dumps({"question": "What is the dose?", "source": "HCP"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert Enquiry.objects.filter(question="What is the dose?").exists()

    def test_create_requires_question(self, client):
        resp = client.post(
            reverse("medinfo:create"),
            data=json.dumps({"question": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert Enquiry.objects.count() == 0

    def test_save_response_as_draft(self, client, enquiry):
        resp = client.post(
            reverse("medinfo:respond", args=[enquiry.pk]),
            data=json.dumps({"response": "Based on the literature…", "action": "draft"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        enquiry.refresh_from_db()
        assert enquiry.status == Enquiry.Status.DRAFT
        assert "Based on" in enquiry.response

    def test_mark_as_responded(self, client, enquiry, medical_user):
        resp = client.post(
            reverse("medinfo:respond", args=[enquiry.pk]),
            data=json.dumps({"response": "Final response.", "action": "respond"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        enquiry.refresh_from_db()
        assert enquiry.status == Enquiry.Status.RESPONDED
        assert enquiry.responded_by == medical_user

    def test_close_enquiry(self, client, enquiry):
        resp = client.post(reverse("medinfo:close", args=[enquiry.pk]))
        assert resp.status_code == 200
        enquiry.refresh_from_db()
        assert enquiry.status == Enquiry.Status.CLOSED


# ════════════════════════════════════════════════════════════════════════════════
# Engagement
# ════════════════════════════════════════════════════════════════════════════════

class TestConferenceModel:
    def test_str(self, db, tenant, medical_user):
        c = Conference.objects.create(
            tenant=tenant, name="ADA 2024", start_date=datetime.date(2024, 6, 21),
            created_by=medical_user,
        )
        assert str(c) == "ADA 2024"

    def test_tenant_isolation(self, db, tenant, medical_user):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant
        Conference.objects.create(tenant=tenant, name="ADA 2024", start_date=datetime.date(2024, 6, 21))
        other = Tenant.objects.create(name="Other", slug="other-conf")
        set_current_tenant(other)
        try:
            assert Conference.objects.count() == 0
        finally:
            set_current_tenant(None)


class TestRoundTableModel:
    def test_str(self, db, tenant):
        rt = RoundTable.objects.create(tenant=tenant, name="T2DM Advisory", date=datetime.date(2024, 9, 1))
        assert str(rt) == "T2DM Advisory"


class TestEngagementViews:
    def test_list_renders(self, client):
        resp = client.get(reverse("engagement:list"))
        assert resp.status_code == 200

    def test_create_conference(self, client, tenant):
        resp = client.post(
            reverse("engagement:create_conference"),
            data=json.dumps({"name": "EASD 2024", "start_date": "2024-09-11"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert Conference.objects.filter(name="EASD 2024").exists()

    def test_create_conference_requires_name(self, client):
        resp = client.post(
            reverse("engagement:create_conference"),
            data=json.dumps({"name": "", "start_date": "2024-09-11"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert not Conference.objects.filter(name="").exists()

    def test_create_round_table(self, client, tenant):
        resp = client.post(
            reverse("engagement:create_round_table"),
            data=json.dumps({"name": "T2DM Advisory", "date": "2024-08-15", "discussion_themes": ["Safety", "Efficacy"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert RoundTable.objects.filter(name="T2DM Advisory").exists()
        rt = RoundTable.objects.get(name="T2DM Advisory")
        assert rt.discussion_themes == ["Safety", "Efficacy"]

    def test_update_conference(self, client, tenant, medical_user):
        conf = Conference.objects.create(
            tenant=tenant, name="Test Conf", start_date=datetime.date(2024, 6, 1),
            created_by=medical_user,
        )
        resp = client.post(
            reverse("engagement:update_conference", args=[conf.pk]),
            data=json.dumps({"status": "ATTENDED"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        conf.refresh_from_db()
        assert conf.status == Conference.Status.ATTENDED
