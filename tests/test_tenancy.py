import datetime

import pytest

from apps.accounts.managers import get_current_tenant, set_current_tenant
from apps.accounts.models import Tenant, User
from apps.literature.models import Paper


def make_paper(tenant, doi_suffix="001", **kwargs):
    defaults = {
        "title": f"Paper {doi_suffix}",
        "authors": ["Author A"],
        "journal": "Test Journal",
        "published_date": datetime.date(2024, 1, 1),
        "doi": f"10.9999/test.{doi_suffix}",
        "status": Paper.Status.INGESTED,
        "source": Paper.Source.PUBMED_OA,
    }
    defaults.update(kwargs)
    return Paper.all_objects.create(tenant=tenant, **defaults)


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Other Pharma", slug="other-pharma")


@pytest.mark.django_db
class TestTenantIsolation:
    def test_paper_objects_filters_by_active_tenant(self, tenant, other_tenant):
        p1 = make_paper(tenant, doi_suffix="t1")
        p2 = make_paper(other_tenant, doi_suffix="t2")

        set_current_tenant(tenant)
        try:
            visible = list(Paper.objects.all())
        finally:
            set_current_tenant(None)

        ids = [p.id for p in visible]
        assert p1.id in ids
        assert p2.id not in ids

    def test_other_tenant_paper_not_visible(self, tenant, other_tenant):
        make_paper(other_tenant, doi_suffix="hidden")

        set_current_tenant(tenant)
        try:
            count = Paper.objects.count()
        finally:
            set_current_tenant(None)

        assert count == 0

    def test_all_objects_bypasses_tenant_filter(self, tenant, other_tenant):
        make_paper(tenant, doi_suffix="a")
        make_paper(other_tenant, doi_suffix="b")

        # all_objects should see both regardless of active tenant
        set_current_tenant(tenant)
        try:
            count = Paper.all_objects.count()
        finally:
            set_current_tenant(None)

        assert count == 2

    def test_no_active_tenant_returns_all(self, tenant, other_tenant):
        make_paper(tenant, doi_suffix="x")
        make_paper(other_tenant, doi_suffix="y")

        set_current_tenant(None)
        count = Paper.objects.count()
        # When no tenant is active, manager returns all records
        assert count == 2

    def test_user_objects_filters_by_tenant(self, tenant, other_tenant):
        user_a = User.objects.create_user(
            username="a@a.com",
            email="a@a.com",
            password="pass",
            tenant=tenant,
            role=User.Role.MEDICAL_AFFAIRS,
        )
        User.objects.create_user(
            username="b@b.com",
            email="b@b.com",
            password="pass",
            tenant=other_tenant,
            role=User.Role.MEDICAL_AFFAIRS,
        )

        set_current_tenant(tenant)
        try:
            users = list(User.objects.filter(email__endswith=".com"))
        finally:
            set_current_tenant(None)

        emails = [u.email for u in users]
        assert "a@a.com" in emails
        assert "b@b.com" not in emails

    def test_paper_get_404_for_wrong_tenant(self, tenant, other_tenant):
        from django.shortcuts import get_object_or_404
        from django.http import Http404

        paper = make_paper(other_tenant, doi_suffix="wrong")

        with pytest.raises(Http404):
            get_object_or_404(Paper, pk=paper.pk, tenant=tenant)


@pytest.mark.django_db
class TestSoftDelete:
    def test_soft_deleted_paper_hidden_from_objects(self, tenant):
        paper = make_paper(tenant, doi_suffix="sd")

        set_current_tenant(tenant)
        try:
            paper.soft_delete()
            count = Paper.objects.count()
        finally:
            set_current_tenant(None)

        assert count == 0

    def test_soft_deleted_visible_via_all_objects(self, tenant):
        paper = make_paper(tenant, doi_suffix="sd2")
        paper.soft_delete()

        count = Paper.all_objects.filter(tenant=tenant, doi="10.9999/test.sd2").count()
        assert count == 1

    def test_restore_makes_paper_visible(self, tenant):
        paper = make_paper(tenant, doi_suffix="sd3")
        paper.soft_delete()
        paper.restore()

        set_current_tenant(tenant)
        try:
            count = Paper.objects.count()
        finally:
            set_current_tenant(None)

        assert count == 1


@pytest.mark.django_db
class TestRemovePaperView:
    @pytest.fixture
    def client(self, medical_user):
        from django.test import Client
        c = Client()
        c.force_login(medical_user)
        return c

    @pytest.fixture
    def paper(self, tenant):
        return make_paper(tenant, doi_suffix="rm1")

    def test_remove_soft_deletes(self, client, paper, tenant):
        from django.urls import reverse
        from apps.accounts.managers import set_current_tenant
        resp = client.post(reverse("literature:remove", args=[paper.pk]))
        assert resp.status_code == 200
        assert resp.get("HX-Refresh") == "true"
        set_current_tenant(tenant)
        try:
            assert Paper.objects.filter(pk=paper.pk).count() == 0
        finally:
            set_current_tenant(None)
        paper.refresh_from_db()
        assert paper.deleted_at is not None

    def test_remove_other_tenant_404(self, client, db):
        from django.urls import reverse
        other = Tenant.objects.create(name="Other", slug="other-rm")
        other_paper = make_paper(other, doi_suffix="rm2")
        resp = client.post(reverse("literature:remove", args=[other_paper.pk]))
        assert resp.status_code == 404

    def test_remove_logged_in_audit(self, client, paper):
        from django.urls import reverse
        from apps.audit.models import AuditLog
        client.post(reverse("literature:remove", args=[paper.pk]))
        assert AuditLog.objects.filter(
            entity_type="Paper", entity_id=paper.pk, action=AuditLog.Action.DELETE
        ).exists()
