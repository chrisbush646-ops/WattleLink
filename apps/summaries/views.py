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

    from apps.summaries.tasks import _ensure_full_text
    _ensure_full_text(paper)
    paper.refresh_from_db(fields=["full_text"])

    from .services.ai_summary import run_ai_summary as _run_ai, apply_summary_result
    from .services.validation import validate_summary

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

        summary.validation_warnings = validate_summary(result, paper.full_text or "")
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

    raw_meth = data.get("methodology", None)
    if raw_meth is not None:
        if isinstance(raw_meth, dict):
            summary.methodology = raw_meth
        elif isinstance(raw_meth, str) and raw_meth.strip():
            summary.methodology = {"study_design": raw_meth.strip()}
        # else: leave as-is
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


@login_required
@require_POST
def generate_results_section(request):
    """Generate a systematic-review-style results section from ingested papers matching keywords."""
    from django.http import JsonResponse
    import anthropic
    from django.conf import settings
    from django.db.models import Q

    keywords = request.POST.get("keywords", "").strip()
    if not keywords:
        return JsonResponse({"error": "Keywords are required."}, status=400)

    # Find papers matching the keywords (title or full text)
    terms = [t.strip() for t in keywords.replace(",", " ").split() if t.strip()]
    q_filter = Q()
    for term in terms:
        q_filter |= Q(title__icontains=term) | Q(full_text__icontains=term)

    papers = (
        Paper.objects
        .filter(q_filter)
        .select_related("grade_assessment")
        .prefetch_related("summary__findings")
        .distinct()[:20]
    )

    if not papers:
        return JsonResponse({"error": "No ingested papers match those keywords."}, status=404)

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        return JsonResponse({"error": "AI not configured."}, status=500)

    # Build context for Claude
    paper_blocks = []
    for p in papers:
        block = f"**{p.title}**\n"
        block += f"Authors: {', '.join(p.authors) if isinstance(p.authors, list) else p.authors}\n"
        block += f"Journal: {p.journal} ({p.published_date.year if p.published_date else 'n.d.'})\n"
        block += f"Study type: {p.study_type}\n"
        try:
            gr = p.grade_assessment
            block += f"GRADE: {gr.overall_rating}\n"
        except Exception:
            pass
        try:
            summary = p.summary
            if summary.executive_paragraph:
                block += f"Summary: {summary.executive_paragraph[:600]}\n"
            findings = list(summary.findings.all()[:6])
            if findings:
                block += "Key findings:\n"
                for f in findings:
                    block += f"  - [{f.category}] {f.finding} ({f.value})\n"
        except Exception:
            if p.full_text:
                block += f"Abstract/text excerpt: {p.full_text[:400]}\n"
        paper_blocks.append(block)

    papers_text = "\n\n---\n\n".join(paper_blocks)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system="""You are a medical writer producing the Results section of a systematic review for a pharmaceutical medical affairs team in Australia.

Your output has two parts:

1. A markdown table with columns: Study | Design | Population | Intervention | Key Finding | GRADE
   - One row per paper
   - Keep cells concise (1–2 sentences max per cell)
   - Use "—" for any field not available

2. A Discussion paragraph (3–5 sentences) synthesising the overall body of evidence: consistency of findings, quality of evidence, key limitations, and clinical implications. Write in academic medical prose.

Format your response as JSON with two keys: "table_markdown" and "discussion".
Return ONLY valid JSON, no prose outside it.""",
            messages=[{
                "role": "user",
                "content": f"Keywords: {keywords}\n\nPapers:\n\n{papers_text}"
            }],
        )
        import json as _json
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        result = _json.loads(raw)
        return JsonResponse({
            "table_markdown": result.get("table_markdown", ""),
            "discussion": result.get("discussion", ""),
            "paper_count": len(papers),
        })
    except _json.JSONDecodeError as e:
        logger.error("generate_results_section JSON error: %s\nRaw: %s", e, locals().get("raw", "")[:300])
        return JsonResponse({"error": "AI returned an unexpected format. Please try again."}, status=500)
    except Exception as e:
        logger.error("generate_results_section error: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
