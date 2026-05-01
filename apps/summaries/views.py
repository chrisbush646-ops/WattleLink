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
def summaries_list(request):
    """Summaries overview page — searchable list + literature reviews."""
    from apps.drafting.models import LiteratureReview

    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")

    summaries = (
        PaperSummary.objects
        .select_related("paper")
        .prefetch_related("findings")
        .order_by("-updated_at")
    )

    if status_filter:
        summaries = summaries.filter(status=status_filter)

    if search:
        summaries = summaries.filter(paper__title__icontains=search)

    lit_reviews = LiteratureReview.objects.select_related("created_by").prefetch_related("papers")

    total = PaperSummary.objects.count()
    confirmed = PaperSummary.objects.filter(status=PaperSummary.Status.CONFIRMED).count()

    return render(request, "summaries/summaries_list.html", {
        "summaries": summaries,
        "search": search,
        "status_filter": status_filter,
        "lit_reviews": lit_reviews,
        "total_summaries": total,
        "confirmed_count": confirmed,
        "pending_count": total - confirmed,
    })


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
    """Run AI summarisation synchronously and return the populated summary panel."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .services.ai_summary import run_ai_summary as _run_ai, apply_summary_result

    ctx = {
        "paper": paper,
        "category_choices": FindingsRow.Category.choices,
    }

    try:
        result = _run_ai(paper)

        summary, _ = PaperSummary.all_objects.get_or_create(
            paper=paper, defaults={"tenant": request.tenant}
        )

        findings_data = result.get("findings", [])
        row_kwargs = apply_summary_result(summary, findings_data, result)
        summary.save()

        FindingsRow.objects.filter(summary=summary).delete()
        FindingsRow.objects.bulk_create([
            FindingsRow(summary=summary, **kw) for kw in row_kwargs
        ])

        log_action(request, paper, AuditLog.Action.AI_DRAFT,
                   after={"summary": "AI summary generated", "findings_rows": len(findings_data)})

        ctx["summary"] = summary
        ctx["findings"] = list(summary.findings.all())

    except Exception as exc:
        logger.error("AI summary failed for paper %s: %s", paper_pk, exc)
        ctx["summary"] = None
        ctx["findings"] = []
        ctx["error"] = str(exc)

    return render(request, "summaries/partials/summary_panel.html", ctx)


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
