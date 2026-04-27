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
    """Trigger async AI pre-fill, return immediately with a 'processing' state."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .tasks import run_ai_assessment_task
    run_ai_assessment_task.delay(paper.pk, request.tenant.pk)

    return render(request, "assessment/partials/ai_processing.html", {
        "paper": paper,
    })


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
