import datetime

import pytest
from django.test import Client
from django.urls import reverse

from apps.claims.models import CoreClaim
from apps.engagement.models import Conference, RoundTable
from apps.literature.models import Paper
from apps.safety.models import SafetySignal


@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant, title="Dashboard Test Paper", authors=["Smith A"],
        journal="NEJM", published_date=datetime.date(2024, 6, 1),
        doi="10.1056/dash", full_text="text",
        status=Paper.Status.INGESTED, source=Paper.Source.PDF_UPLOAD,
    )


class TestDashboard:
    def test_renders_ok(self, client):
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200

    def test_requires_login(self, db):
        c = Client()
        resp = c.get(reverse("dashboard:index"))
        assert resp.status_code == 302

    def test_kpi_counts_appear(self, client, paper):
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"Papers ingested" in resp.content

    def test_awaiting_paper_shown(self, client, paper):
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"Dashboard Test Paper" in resp.content

    def test_approved_claim_in_decisions(self, client, db, tenant, paper, medical_user):
        claim = CoreClaim.objects.create(
            tenant=tenant, paper=paper,
            claim_text="Drug X reduces HbA1c significantly.",
            endpoint_type=CoreClaim.EndpointType.PRIMARY,
            status=CoreClaim.Status.APPROVED,
            reviewed_by=medical_user,
            reviewed_at=datetime.datetime(2024, 7, 1, tzinfo=datetime.timezone.utc),
            fair_balance="May cause hypoglycaemia.",
            fidelity_checklist={},
        )
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"Drug X reduces" in resp.content

    def test_upcoming_conference_shown(self, client, db, tenant, medical_user):
        Conference.objects.create(
            tenant=tenant, name="EASD 2099",
            start_date=datetime.date(2099, 9, 11),
            status=Conference.Status.UPCOMING,
            created_by=medical_user,
        )
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"EASD 2099" in resp.content

    def test_active_signal_shown(self, client, db, tenant, medical_user):
        SafetySignal.objects.create(
            tenant=tenant, event_name="Hepatotoxicity risk",
            severity=SafetySignal.Severity.SERIOUS,
            status=SafetySignal.Status.ACTIVE,
            created_by=medical_user,
        )
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"Hepatotoxicity risk" in resp.content

    def test_empty_state_no_errors(self, client, db):
        resp = client.get(reverse("dashboard:index"))
        assert resp.status_code == 200
        assert b"No papers awaiting action" in resp.content
        assert b"No upcoming events" in resp.content
        assert b"No active safety signals" in resp.content
