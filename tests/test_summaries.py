import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.literature.models import Paper
from apps.summaries.models import FindingsRow, PaperSummary
from apps.summaries.services.ai_summary import apply_summary_result, run_ai_summary


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper(db, tenant):
    return Paper.all_objects.create(
        tenant=tenant,
        title="Efficacy of Drug X in T2DM",
        authors=["Smith A", "Jones B"],
        journal="NEJM",
        published_date=datetime.date(2024, 6, 1),
        doi="10.1056/test0001",
        full_text="This double-blind RCT enrolled 800 patients with T2DM...",
        status=Paper.Status.ASSESSED,
        source=Paper.Source.PDF_UPLOAD,
    )


@pytest.fixture
def summary(db, tenant, paper):
    s = PaperSummary.all_objects.create(
        tenant=tenant,
        paper=paper,
        status=PaperSummary.Status.AI_DRAFT,
        methodology={"study_design": "Double-blind RCT, 800 patients.", "population": {}, "intervention": ""},
        executive_paragraph="Drug X significantly reduced HbA1c.",
        ai_prefilled=True,
    )
    FindingsRow.objects.create(
        summary=s,
        category=FindingsRow.Category.PRIMARY,
        finding="HbA1c reduction",
        quantitative_result="-1.2% (p<0.001)",
        page_ref="p.4",
        clinical_significance="Clinically meaningful reduction.",
        order=0,
    )
    return s


AI_RESPONSE = {
    "methodology": {
        "study_design": "Randomised double-blind placebo-controlled trial, n=800.",
        "population": {"description": "Adults with T2DM", "sample_size": "N=800", "demographics": "Mean age 58"},
        "intervention": "Drug X 10mg once daily",
        "comparator": "Placebo",
        "follow_up": "24 weeks",
        "primary_endpoint": "HbA1c reduction at 24 weeks",
        "secondary_endpoints": ["Weight change", "Fasting glucose"],
        "statistical_methods": "ANCOVA with last observation carried forward",
        "setting": "Multicentre, 12 countries",
        "source_reference": "Methods, p.2-3",
    },
    "findings": [
        {
            "category": "Primary",
            "finding": "HbA1c reduction at 24 weeks",
            "quantitative_result": "-1.2% vs -0.3% placebo (p<0.001)",
            "page_ref": "p.4",
            "clinical_significance": "Exceeds MCID of 0.5%.",
        },
        {
            "category": "Safety",
            "finding": "Hypoglycaemia events",
            "quantitative_result": "3.1% vs 1.8%",
            "page_ref": "p.7",
            "clinical_significance": "Mild; no serious events.",
        },
    ],
    "executive_paragraph": "Drug X demonstrated superior glycaemic control...",
    "safety_summary": "Well tolerated; mild hypoglycaemia only.",
    "adverse_events": [{"event": "Hypoglycaemia", "incidence": "3.1%", "page_ref": "p.7"}],
    "limitations": [{"limitation": "Short follow-up (24 weeks).", "page_ref": "p.10"}],
}


# ── Model tests ───────────────────────────────────────────────────────────────

class TestPaperSummaryModel:
    def test_str(self, summary, paper):
        assert str(paper) in str(summary)

    def test_default_status_is_ai_draft(self, db, tenant, paper):
        s = PaperSummary.all_objects.create(tenant=tenant, paper=paper)
        assert s.status == PaperSummary.Status.AI_DRAFT

    def test_findings_row_ordering(self, summary):
        FindingsRow.objects.create(
            summary=summary, category="Secondary", finding="Weight loss",
            quantitative_result="-2kg", order=1,
        )
        cats = list(summary.findings.values_list("order", flat=True))
        assert cats == sorted(cats)

    def test_findings_row_str(self, summary):
        row = summary.findings.first()
        assert "Primary" in str(row)
        assert "HbA1c" in str(row)


class TestSummaryTenantIsolation:
    def test_tenant_manager_excludes_other_tenant(self, db, summary):
        from apps.accounts.managers import set_current_tenant
        from apps.accounts.models import Tenant

        other_tenant = Tenant.objects.create(name="Other Co", slug="other-co")
        set_current_tenant(other_tenant)
        try:
            assert PaperSummary.objects.count() == 0
        finally:
            set_current_tenant(None)

    def test_tenant_manager_includes_own_tenant(self, db, tenant, summary):
        from apps.accounts.managers import set_current_tenant

        set_current_tenant(tenant)
        try:
            assert PaperSummary.objects.count() == 1
        finally:
            set_current_tenant(None)

    def test_soft_deleted_summary_excluded(self, db, tenant, summary):
        from apps.accounts.managers import set_current_tenant
        import django.utils.timezone as tz

        summary.deleted_at = tz.now()
        summary.save(update_fields=["deleted_at"])

        set_current_tenant(tenant)
        try:
            assert PaperSummary.objects.count() == 0
        finally:
            set_current_tenant(None)


# ── AI service tests ──────────────────────────────────────────────────────────

class TestApplySummaryResult:
    def test_maps_fields_in_place(self, db, tenant, paper):
        s = PaperSummary.all_objects.create(tenant=tenant, paper=paper)
        rows = apply_summary_result(s, AI_RESPONSE["findings"], AI_RESPONSE)

        assert s.methodology["study_design"] == AI_RESPONSE["methodology"]["study_design"]
        assert s.executive_paragraph == AI_RESPONSE["executive_paragraph"]
        assert s.safety_summary == AI_RESPONSE["safety_summary"]
        assert s.ai_prefilled is True
        assert len(s.adverse_events) == 1
        assert len(s.limitations) == 1

    def test_returns_findings_row_kwargs(self, db, tenant, paper):
        s = PaperSummary.all_objects.create(tenant=tenant, paper=paper)
        rows = apply_summary_result(s, AI_RESPONSE["findings"], AI_RESPONSE)

        assert len(rows) == 2
        assert rows[0]["category"] == "Primary"
        assert rows[0]["order"] == 0
        assert rows[1]["category"] == "Safety"
        assert rows[1]["order"] == 1

    def test_empty_findings_returns_empty_list(self, db, tenant, paper):
        s = PaperSummary.all_objects.create(tenant=tenant, paper=paper)
        rows = apply_summary_result(s, [], AI_RESPONSE)
        assert rows == []

    def test_no_text_raises(self, db, tenant):
        paper = Paper.all_objects.create(
            tenant=tenant, title="", authors=[], journal="X",
            published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.ASSESSED,
            source=Paper.Source.PDF_UPLOAD,
        )
        with pytest.raises(ValueError, match="no text to summarise"):
            run_ai_summary(paper)


class TestRunAiSummary:
    def _make_mock_response(self, data):
        msg = MagicMock()
        msg.content = [MagicMock(text=json.dumps(data))]
        return msg

    @patch("apps.summaries.services.ai_summary.anthropic.Anthropic")
    def test_returns_parsed_dict(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = \
            self._make_mock_response(AI_RESPONSE)
        result = run_ai_summary(paper)
        assert result["methodology"] == AI_RESPONSE["methodology"]
        assert len(result["findings"]) == 2

    @patch("apps.summaries.services.ai_summary.anthropic.Anthropic")
    def test_strips_markdown_fences(self, mock_anthropic, paper):
        fenced = f"```json\n{json.dumps(AI_RESPONSE)}\n```"
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=fenced)]
        )
        result = run_ai_summary(paper)
        assert "methodology" in result

    @patch("apps.summaries.services.ai_summary.anthropic.Anthropic")
    def test_raises_on_bad_json(self, mock_anthropic, paper):
        mock_anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text="not json at all")]
        )
        with pytest.raises(json.JSONDecodeError):
            run_ai_summary(paper)


# ── View tests ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(medical_user):
    c = Client()
    c.force_login(medical_user)
    return c


class TestSummaryPanelView:
    def test_returns_empty_state_when_no_summary(self, client, paper):
        url = reverse("summaries:panel", args=[paper.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"No summary yet" in resp.content

    def test_returns_panel_with_summary(self, client, paper, summary):
        url = reverse("summaries:panel", args=[paper.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"AI Draft" in resp.content
        assert b"HbA1c reduction" in resp.content

    def test_confirmed_badge_shown(self, client, paper, summary, medical_user):
        from django.utils import timezone
        summary.status = PaperSummary.Status.CONFIRMED
        summary.confirmed_by = medical_user
        summary.confirmed_at = timezone.now()
        summary.save()

        url = reverse("summaries:panel", args=[paper.pk])
        resp = client.get(url)
        assert b"Confirmed" in resp.content

    def test_other_tenant_paper_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Rival Pharma", slug="rival")
        paper2 = Paper.all_objects.create(
            tenant=other, title="Other paper", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.ASSESSED, source=Paper.Source.PDF_UPLOAD,
        )
        url = reverse("summaries:panel", args=[paper2.pk])
        resp = client.get(url)
        assert resp.status_code == 404


class TestRunAiSummaryView:
    @patch("apps.summaries.tasks.run_ai_summary_task")
    def test_returns_processing_partial(self, mock_task, client, paper):
        fake_task = MagicMock()
        fake_task.id = "test-summary-task-1234"
        mock_task.delay.return_value = fake_task
        url = reverse("summaries:run_ai", args=[paper.pk])
        resp = client.post(url)
        assert resp.status_code == 200
        assert b"Running AI summary" in resp.content

    @patch("apps.summaries.tasks.run_ai_summary_task")
    def test_dispatches_celery_task(self, mock_task, client, paper, tenant):
        fake_task = MagicMock()
        fake_task.id = "test-summary-task-5678"
        mock_task.delay.return_value = fake_task
        url = reverse("summaries:run_ai", args=[paper.pk])
        client.post(url)
        mock_task.delay.assert_called_once_with(paper.pk, tenant.pk)

    def test_get_not_allowed(self, client, paper):
        url = reverse("summaries:run_ai", args=[paper.pk])
        resp = client.get(url)
        assert resp.status_code == 405


class TestConfirmSummaryView:
    def _payload(self, **overrides):
        base = {
            "methodology": "Updated methodology text.",
            "executive_paragraph": "Updated executive paragraph.",
        }
        base.update(overrides)
        return base

    def test_creates_summary_if_missing(self, client, paper):
        url = reverse("summaries:confirm", args=[paper.pk])
        resp = client.post(
            url,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert PaperSummary.all_objects.filter(paper=paper).exists()

    def test_sets_status_confirmed(self, client, paper, summary):
        url = reverse("summaries:confirm", args=[paper.pk])
        client.post(url, data=json.dumps(self._payload()), content_type="application/json")
        summary.refresh_from_db()
        assert summary.status == PaperSummary.Status.CONFIRMED

    def test_saves_edited_methodology(self, client, paper, summary):
        url = reverse("summaries:confirm", args=[paper.pk])
        new_meth = {"study_design": "New methodology.", "population": {}, "intervention": ""}
        client.post(
            url,
            data=json.dumps(self._payload(methodology=new_meth)),
            content_type="application/json",
        )
        summary.refresh_from_db()
        assert summary.methodology["study_design"] == "New methodology."

    def test_advances_paper_assessed_to_summarised(self, client, paper, summary):
        assert paper.status == Paper.Status.ASSESSED
        url = reverse("summaries:confirm", args=[paper.pk])
        client.post(url, data=json.dumps(self._payload()), content_type="application/json")
        paper.refresh_from_db()
        assert paper.status == Paper.Status.SUMMARISED

    def test_does_not_regress_paper_status(self, client, paper, summary):
        paper.status = Paper.Status.SUMMARISED
        paper.save(update_fields=["status", "updated_at"])
        url = reverse("summaries:confirm", args=[paper.pk])
        client.post(url, data=json.dumps(self._payload()), content_type="application/json")
        paper.refresh_from_db()
        assert paper.status == Paper.Status.SUMMARISED

    def test_replaces_findings_rows(self, client, paper, summary):
        assert summary.findings.count() == 1
        new_findings = [
            {"category": "Primary", "finding": "New finding A", "quantitative_result": "p=0.01", "page_ref": "p.3", "clinical_significance": "Significant."},
            {"category": "Secondary", "finding": "New finding B", "quantitative_result": "NS", "page_ref": "p.5", "clinical_significance": "Not significant."},
        ]
        url = reverse("summaries:confirm", args=[paper.pk])
        client.post(
            url,
            data=json.dumps(self._payload(findings=new_findings)),
            content_type="application/json",
        )
        summary.refresh_from_db()
        assert summary.findings.count() == 2
        assert summary.findings.first().finding == "New finding A"

    def test_confirmed_flag_in_response(self, client, paper, summary):
        url = reverse("summaries:confirm", args=[paper.pk])
        resp = client.post(url, data=json.dumps(self._payload()), content_type="application/json")
        assert b"Summary confirmed" in resp.content

    def test_records_confirmed_by(self, client, medical_user, paper, summary):
        url = reverse("summaries:confirm", args=[paper.pk])
        client.post(url, data=json.dumps(self._payload()), content_type="application/json")
        summary.refresh_from_db()
        assert summary.confirmed_by == medical_user

    def test_other_tenant_paper_returns_404(self, db, client):
        from apps.accounts.models import Tenant

        other = Tenant.objects.create(name="Rival Pharma", slug="rival-2")
        paper2 = Paper.all_objects.create(
            tenant=other, title="Other paper", authors=[],
            journal="Lancet", published_date=datetime.date(2024, 1, 1),
            status=Paper.Status.ASSESSED, source=Paper.Source.PDF_UPLOAD,
        )
        url = reverse("summaries:confirm", args=[paper2.pk])
        resp = client.post(
            url, data=json.dumps(self._payload()), content_type="application/json"
        )
        assert resp.status_code == 404
