import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import GradeAssessment, RobAssessment

logger = logging.getLogger(__name__)


@login_required
def assessment_list(request):
    """Quality Assessment overview page — GRADE reference + paper rankings."""
    from apps.literature.models import Paper
    from django.db.models import Case, IntegerField, Value, When

    grade_order = Case(
        When(grade_assessment__overall_rating="High", then=Value(1)),
        When(grade_assessment__overall_rating="Moderate", then=Value(2)),
        When(grade_assessment__overall_rating="Low", then=Value(3)),
        When(grade_assessment__overall_rating="Very Low", then=Value(4)),
        default=Value(5),
        output_field=IntegerField(),
    )

    rating_filter = request.GET.get("grade", "")
    q = request.GET.get("q", "").strip()

    papers = (
        Paper.objects
        .select_related("grade_assessment", "rob_assessment")
        .annotate(grade_order=grade_order)
        .order_by("grade_order", "-created_at")
    )

    if q:
        papers = papers.filter(title__icontains=q)
    if rating_filter == "unassessed":
        papers = papers.filter(grade_assessment__isnull=True)
    elif rating_filter:
        papers = papers.filter(grade_assessment__overall_rating=rating_filter)

    paper_rows = []
    for paper in papers:
        try:
            gr = paper.grade_assessment
            grade_rating = gr.overall_rating
            grade_draft = True
            confirmed = gr.status == GradeAssessment.Status.CONFIRMED
        except GradeAssessment.DoesNotExist:
            grade_rating = ""
            grade_draft = False
            confirmed = False
        try:
            rob = paper.rob_assessment
            rob_judgment = rob.overall_judgment
            rob_draft = True
        except RobAssessment.DoesNotExist:
            rob_judgment = ""
            rob_draft = False
        paper_rows.append({
            "paper": paper,
            "grade_rating": grade_rating,
            "grade_draft": grade_draft,
            "confirmed": confirmed,
            "rob_judgment": rob_judgment,
            "rob_draft": rob_draft,
        })

    return render(request, "assessment/assessment_list.html", {
        "paper_rows": paper_rows,
        "rating_filter": rating_filter,
        "grade_choices": GradeAssessment.OverallRating.choices,
        "total": len(paper_rows),
    })


@login_required
def assessment_panel(request, paper_pk):
    """HTMX — return the full assessment panel for a paper (embedded in its detail modal)."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    try:
        grade = paper.grade_assessment
    except GradeAssessment.DoesNotExist:
        grade = None

    try:
        rob = paper.rob_assessment
    except RobAssessment.DoesNotExist:
        rob = None

    return render(request, "assessment/partials/assessment_panel.html", {
        "paper": paper,
        "grade": grade,
        "rob": rob,
        "grade_domain_rating_choices": GradeAssessment.DomainRating.choices,
        "rob_judgment_choices": RobAssessment.Judgment.choices,
        "grade_overall_choices": GradeAssessment.OverallRating.choices,
    })


@login_required
@require_POST
def run_ai_assessment(request, paper_pk):
    """Run AI pre-fill synchronously and return the populated assessment panel."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .services.ai_assessment import (
        run_ai_assessment as _run_ai,
        apply_grade_result,
        apply_rob_result,
    )

    ctx = {
        "paper": paper,
        "grade_domain_rating_choices": GradeAssessment.DomainRating.choices,
        "rob_judgment_choices": RobAssessment.Judgment.choices,
        "grade_overall_choices": GradeAssessment.OverallRating.choices,
    }

    try:
        result = _run_ai(paper)

        grade, _ = GradeAssessment.all_objects.get_or_create(
            paper=paper, defaults={"tenant": request.tenant}
        )
        apply_grade_result(grade, result.get("grade", {}))
        grade.save()

        rob, _ = RobAssessment.all_objects.get_or_create(
            paper=paper, defaults={"tenant": request.tenant}
        )
        apply_rob_result(rob, result.get("rob", {}))
        rob.save()

        log_action(request, paper, AuditLog.Action.AI_DRAFT,
                   after={"assessment": "AI pre-fill complete"})

        ctx["grade"] = grade
        ctx["rob"] = rob

    except Exception as exc:
        logger.error("AI assessment failed for paper %s: %s", paper_pk, exc)
        ctx["grade"] = None
        ctx["rob"] = None
        ctx["error"] = str(exc)

    return render(request, "assessment/partials/assessment_panel.html", ctx)


@login_required
@require_POST
def confirm_assessment(request, paper_pk):
    """
    Save edited GRADE + RoB 2 data, mark both as CONFIRMED, advance paper to ASSESSED.
    Expects JSON body with `grade` and `rob` keys.
    """
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    data = json.loads(request.body)

    grade_data = data.get("grade", {})
    rob_data = data.get("rob", {})

    # ── GRADE ────────────────────────────────────────────────────────────────
    grade, _ = GradeAssessment.all_objects.get_or_create(
        paper=paper,
        defaults={"tenant": request.tenant},
    )

    grade.overall_rating = grade_data.get("overall_rating", grade.overall_rating)
    for field_prefix, key in [
        ("rob", "rob"),
        ("inconsistency", "inconsistency"),
        ("indirectness", "indirectness"),
        ("imprecision", "imprecision"),
        ("publication_bias", "publication_bias"),
    ]:
        domain = grade_data.get(key, {})
        if domain:
            setattr(grade, f"{field_prefix}_rating", domain.get("rating", getattr(grade, f"{field_prefix}_rating")))
            setattr(grade, f"{field_prefix}_rationale", domain.get("rationale", getattr(grade, f"{field_prefix}_rationale")))
            setattr(grade, f"{field_prefix}_page_ref", domain.get("page_ref", getattr(grade, f"{field_prefix}_page_ref")))

    grade.status = GradeAssessment.Status.CONFIRMED
    grade.confirmed_by = request.user
    grade.confirmed_at = timezone.now()
    grade.save()

    # ── RoB 2 ────────────────────────────────────────────────────────────────
    rob, _ = RobAssessment.all_objects.get_or_create(
        paper=paper,
        defaults={"tenant": request.tenant},
    )

    rob.overall_judgment = rob_data.get("overall_judgment", rob.overall_judgment)
    for prefix in ("d1", "d2", "d3", "d4", "d5"):
        domain = rob_data.get(prefix, {})
        if domain:
            setattr(rob, f"{prefix}_judgment", domain.get("judgment", getattr(rob, f"{prefix}_judgment")))
            setattr(rob, f"{prefix}_rationale", domain.get("rationale", getattr(rob, f"{prefix}_rationale")))
            setattr(rob, f"{prefix}_page_ref", domain.get("page_ref", getattr(rob, f"{prefix}_page_ref")))

    rob.status = RobAssessment.Status.CONFIRMED
    rob.confirmed_by = request.user
    rob.confirmed_at = timezone.now()
    rob.save()

    # ── Advance paper ────────────────────────────────────────────────────────
    before = {"status": paper.status, "grade_rating": paper.grade_rating}
    paper.grade_rating = grade.overall_rating
    if paper.status == Paper.Status.INGESTED:
        paper.status = Paper.Status.ASSESSED
    paper.save(update_fields=["grade_rating", "status", "updated_at"])

    log_action(request, paper, AuditLog.Action.UPDATE,
               before=before,
               after={"status": paper.status, "grade_rating": paper.grade_rating})

    return render(request, "assessment/partials/assessment_panel.html", {
        "paper": paper,
        "grade": grade,
        "rob": rob,
        "grade_domain_rating_choices": GradeAssessment.DomainRating.choices,
        "rob_judgment_choices": RobAssessment.Judgment.choices,
        "grade_overall_choices": GradeAssessment.OverallRating.choices,
        "confirmed": True,
    })
