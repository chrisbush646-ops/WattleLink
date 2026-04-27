import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import FindingsRow, PaperSummary

logger = logging.getLogger(__name__)


@login_required
def summary_panel(request, paper_pk):
    """HTMX — return the summary panel for a paper."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    try:
        summary = paper.summary
        findings = list(summary.findings.all())
    except PaperSummary.DoesNotExist:
        summary = None
        findings = []

    return render(request, "summaries/partials/summary_panel.html", {
        "paper": paper,
        "summary": summary,
        "findings": findings,
        "category_choices": FindingsRow.Category.choices,
    })


@login_required
@require_POST
def run_ai_summary(request, paper_pk):
    """Trigger async AI summarisation, return spinner immediately."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .tasks import run_ai_summary_task
    run_ai_summary_task.delay(paper.pk, request.tenant.pk)

    return render(request, "summaries/partials/ai_processing.html", {
        "paper": paper,
    })


@login_required
@require_POST
def confirm_summary(request, paper_pk):
    """
    Save edited summary, confirm, advance paper from ASSESSED → SUMMARISED.
    Expects JSON body with summary fields and findings array.
    """
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    data = json.loads(request.body)

    summary, _ = PaperSummary.all_objects.get_or_create(
        paper=paper,
        defaults={"tenant": request.tenant},
    )

    summary.methodology = data.get("methodology", summary.methodology)
    summary.executive_paragraph = data.get("executive_paragraph", summary.executive_paragraph)
    summary.safety_summary = data.get("safety_summary", summary.safety_summary)
    summary.adverse_events = data.get("adverse_events", summary.adverse_events)
    summary.limitations = data.get("limitations", summary.limitations)
    summary.status = PaperSummary.Status.CONFIRMED
    summary.confirmed_by = request.user
    summary.confirmed_at = timezone.now()
    summary.save()

    # Replace findings if provided
    findings_data = data.get("findings")
    if findings_data is not None:
        FindingsRow.objects.filter(summary=summary).delete()
        FindingsRow.objects.bulk_create([
            FindingsRow(
                summary=summary,
                category=f.get("category", "Other"),
                finding=f.get("finding", ""),
                quantitative_result=f.get("quantitative_result", ""),
                page_ref=f.get("page_ref", ""),
                clinical_significance=f.get("clinical_significance", ""),
                order=i,
            )
            for i, f in enumerate(findings_data)
        ])

    before = {"status": paper.status}
    if paper.status == Paper.Status.ASSESSED:
        paper.status = Paper.Status.SUMMARISED
        paper.save(update_fields=["status", "updated_at"])

    log_action(request, paper, AuditLog.Action.UPDATE,
               before=before,
               after={"status": paper.status})

    findings = list(summary.findings.all())
    return render(request, "summaries/partials/summary_panel.html", {
        "paper": paper,
        "summary": summary,
        "findings": findings,
        "category_choices": FindingsRow.Category.choices,
        "confirmed": True,
    })
