import datetime
import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.literature.models import Paper
from apps.safety.models import SafetySignal, SignalMention


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Drug X safety study",
        authors=["Smith A"],
        journal="NEJM",
        published_date=datetime.date(2024, 6, 1),
        doi="10.1056/safety_test_001",
        full_text="Hypoglycaemia occurred in 3.1% of treated patients vs 1.8% placebo.",
        status=Paper.Status.SUMMARISED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def signal(db, tenant, medical_user):
    return SafetySignal.objects.create(
        tenant=tenant,
        event_name="Hypoglycaemia",
        severity=SafetySignal.Severity.MODERATE,
        status=SafetySignal.Status.ACTIVE,
        description="Mild hypoglycaemia episodes reported across multiple trials.",
        prepared_response="This is consistent with the drug class; episodes were mild and self-resolving.",
        created_by=medical_user,
    )


@pytest.fixture
def mention(db, signal, paper, medical_user):
    return SignalMention.objects.create(
        signal=signal,
        paper=paper,
        incidence_treatment="3.1%",
        incidence_control="1.8%",
        page_ref="p.7",
        passage="Hypoglycaemia occurred in 3.1% of treated patients.",
        added_by=medical_user,
    )


@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


# ── Model tests ───────────────────────────────────────────────────────────────

class TestSafetySignalModel:
    def test_str(self, signal):
        assert str(signal) == "Hypoglycaemia"

    def test_mention_count_zero(self, signal):
        assert signal.mention_count == 0

    def test_mention_count_with_mention(self, signal, mention):
        assert signal.mention_count == 1

    def test_default_status_active(self, db, tenant):
        s = SafetySignal.objects.create(tenant=tenant, event_name="Test AE")
        assert s.status == SafetySignal.Status.ACTIVE

    def test_default_severity_moderate(self, db, tenant):
        s = SafetySignal.objects.create(tenant=tenant, event_name="Test AE")
        assert s.severity == SafetySignal.Severity.MODERATE


class TestSignalMentionModel:
    def test_str(self, mention, signal, paper):
        assert "Hypoglycaemia" in str(mention)

    def test_unique_together(self, db, signal, paper, medical_user, mention):
        with pytest.raises(Exception):
            SignalMention.objects.create(
                signal=signal, paper=paper,
                incidence_treatment="5%", added_by=medical_user,
            )


class TestSignalTenantIsolation:
    def test_other_tenant_excluded(self, db, signal):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other Co", slug="other-safety")
        set_current_tenant(other)
        try:
            assert SafetySignal.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_own_tenant_visible(self, db, tenant, signal):
        from apps.accounts.managers import set_current_tenant

        set_current_tenant(tenant)
        try:
            assert SafetySignal.objects.count() == 1
        finally:
            set_current_tenant(None)

    def test_soft_deleted_signal_excluded(self, db, tenant, signal):
        from apps.accounts.managers import set_current_tenant
        from django.utils import timezone

        signal.deleted_at = timezone.now()
        signal.save(update_fields=["deleted_at"])
        set_current_tenant(tenant)
        try:
            assert SafetySignal.objects.count() == 0
        finally:
            set_current_tenant(None)


# ── View tests ────────────────────────────────────────────────────────────────

class TestSignalListView:
    def test_renders_empty(self, client):
        resp = client.get(reverse("safety:list"))
        assert resp.status_code == 200
        assert b"No safety signals" in resp.content

    def test_renders_signal(self, client, signal):
        resp = client.get(reverse("safety:list"))
        assert resp.status_code == 200
        assert b"Hypoglycaemia" in resp.content

    def test_requires_login(self, db):
        resp = Client().get(reverse("safety:list"))
        assert resp.status_code == 302


class TestSignalDetailView:
    def test_renders(self, client, signal):
        resp = client.get(reverse("safety:detail", args=[signal.pk]))
        assert resp.status_code == 200
        assert b"Hypoglycaemia" in resp.content

    def test_other_tenant_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other", slug="other-det")
        s = SafetySignal.objects.create(tenant=other, event_name="Other AE")
        resp = client.get(reverse("safety:detail", args=[s.pk]))
        assert resp.status_code == 404


class TestCreateSignalView:
    def test_creates_signal(self, client, tenant):
        resp = client.post(
            reverse("safety:create"),
            data=json.dumps({"event_name": "Hepatotoxicity", "severity": "SERIOUS"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert SafetySignal.objects.filter(event_name="Hepatotoxicity").exists()

    def test_empty_name_returns_error(self, client):
        resp = client.post(
            reverse("safety:create"),
            data=json.dumps({"event_name": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert not SafetySignal.objects.exists()


class TestUpdateSignalView:
    def test_updates_severity_and_status(self, client, signal):
        resp = client.post(
            reverse("safety:update", args=[signal.pk]),
            data=json.dumps({"severity": "SERIOUS", "status": "MONITORING"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        signal.refresh_from_db()
        assert signal.severity == SafetySignal.Severity.SERIOUS
        assert signal.status == SafetySignal.Status.MONITORING

    def test_saves_prepared_response(self, client, signal):
        resp = client.post(
            reverse("safety:update", args=[signal.pk]),
            data=json.dumps({"prepared_response": "New response text."}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        signal.refresh_from_db()
        assert signal.prepared_response == "New response text."

    def test_other_tenant_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other", slug="other-upd")
        s = SafetySignal.objects.create(tenant=other, event_name="AE")
        resp = client.post(
            reverse("safety:update", args=[s.pk]),
            data=json.dumps({"severity": "MILD"}),
            content_type="application/json",
        )
        assert resp.status_code == 404


class TestAddMentionView:
    def test_links_paper_to_signal(self, client, signal, paper):
        resp = client.post(
            reverse("safety:add_mention", args=[signal.pk]),
            data=json.dumps({
                "paper_pk": paper.pk,
                "incidence_treatment": "3.1%",
                "incidence_control": "1.8%",
                "page_ref": "p.7",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert SignalMention.objects.filter(signal=signal, paper=paper).exists()

    def test_missing_paper_returns_error(self, client, signal):
        resp = client.post(
            reverse("safety:add_mention", args=[signal.pk]),
            data=json.dumps({"paper_pk": None}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert not SignalMention.objects.filter(signal=signal).exists()

    def test_duplicate_updates_existing(self, client, signal, paper, mention):
        resp = client.post(
            reverse("safety:add_mention", args=[signal.pk]),
            data=json.dumps({
                "paper_pk": paper.pk,
                "incidence_treatment": "4.0%",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert SignalMention.objects.filter(signal=signal).count() == 1
        mention.refresh_from_db()
        assert mention.incidence_treatment == "4.0%"  # view updates on duplicate


class TestRemoveMentionView:
    def test_removes_mention(self, client, signal, mention):
        resp = client.post(reverse("safety:remove_mention", args=[mention.pk]))
        assert resp.status_code == 200
        assert not SignalMention.objects.filter(pk=mention.pk).exists()

    def test_other_tenant_mention_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Other", slug="other-rm")
        other_paper = Paper.all_objects.create(
            tenant=other, title="X", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.SUMMARISED, source=Paper.Source.PDF_UPLOAD,
        )
        other_signal = SafetySignal.objects.create(tenant=other, event_name="AE")
        m = SignalMention.objects.create(signal=other_signal, paper=other_paper)
        resp = client.post(reverse("safety:remove_mention", args=[m.pk]))
        assert resp.status_code == 404
