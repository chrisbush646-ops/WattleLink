import json
import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import CoreClaim

logger = logging.getLogger(__name__)


@login_required
def claims_list(request):
    """Main Core Claims page — approved claims and those awaiting approval."""
    qs = CoreClaim.all_objects.filter(
        tenant=request.tenant,
        deleted_at__isnull=True,
    ).select_related("paper", "reviewed_by")

    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")

    if q:
        qs = qs.filter(
            Q(claim_text__icontains=q) |
            Q(paper__title__icontains=q) |
            Q(paper__journal__icontains=q)
        )

    if status_filter == "approved":
        qs = qs.filter(status=CoreClaim.Status.APPROVED)
    elif status_filter == "pending":
        qs = qs.filter(status__in=[CoreClaim.Status.AI_DRAFT, CoreClaim.Status.IN_REVIEW])
    elif status_filter == "rejected":
        qs = qs.filter(status=CoreClaim.Status.REJECTED)

    all_qs = CoreClaim.all_objects.filter(tenant=request.tenant, deleted_at__isnull=True)
    approved_count = all_qs.filter(status=CoreClaim.Status.APPROVED).count()
    pending_count = all_qs.filter(status__in=[CoreClaim.Status.AI_DRAFT, CoreClaim.Status.IN_REVIEW]).count()
    rejected_count = all_qs.filter(status=CoreClaim.Status.REJECTED).count()

    claims = list(qs.order_by("-updated_at"))

    if request.headers.get("HX-Request"):
        return render(request, "claims/partials/claims_list_results.html", {
            "claims": claims,
            "q": q,
            "status_filter": status_filter,
        })

    return render(request, "claims/claims_list.html", {
        "claims": claims,
        "q": q,
        "status_filter": status_filter,
        "approved_count": approved_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "total_count": approved_count + pending_count + rejected_count,
    })


@login_required
@require_POST
def create_claim(request, paper_pk):
    """Create a manual (human-authored) claim and return the updated claims panel."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    claim_text = request.POST.get("claim_text", "").strip()
    endpoint_type = request.POST.get("endpoint_type", CoreClaim.EndpointType.PRIMARY)

    def _panel(error=None):
        claims = list(CoreClaim.all_objects.filter(paper=paper, deleted_at__isnull=True))
        approved_count = sum(1 for c in claims if c.status == CoreClaim.Status.APPROVED)
        return render(request, "claims/partials/claims_panel.html", {
            "paper": paper,
            "claims": claims,
            "approved_count": approved_count,
            "error": error,
        })

    if not claim_text:
        return _panel("Claim text is required.")

    if endpoint_type not in CoreClaim.EndpointType.values:
        endpoint_type = CoreClaim.EndpointType.PRIMARY

    claim = CoreClaim.all_objects.create(
        tenant=request.tenant,
        paper=paper,
        claim_text=claim_text,
        endpoint_type=endpoint_type,
        status=CoreClaim.Status.IN_REVIEW,
        ai_generated=False,
    )
    log_action(request, claim, AuditLog.Action.CREATE,
               after={"claim_text": claim_text, "source": "manual"})

    return _panel()


@login_required
def claims_panel(request, paper_pk):
    """HTMX — return the claims panel for a paper."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    claims = list(CoreClaim.all_objects.filter(paper=paper, deleted_at__isnull=True))
    approved_count = sum(1 for c in claims if c.status == CoreClaim.Status.APPROVED)
    return render(request, "claims/partials/claims_panel.html", {
        "paper": paper,
        "claims": claims,
        "approved_count": approved_count,
    })


@login_required
@require_POST
def run_extraction(request, paper_pk):
    """Run AI claim extraction synchronously and return the populated claims panel."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .services.extraction import extract_claims as _extract

    try:
        claims_data = _extract(paper)

        CoreClaim.all_objects.filter(paper=paper, status=CoreClaim.Status.AI_DRAFT).delete()

        CoreClaim.all_objects.bulk_create([
            CoreClaim(
                tenant=request.tenant,
                paper=paper,
                commercial_headline=c.get("commercial_headline", ""),
                claim_text=c.get("claim_text", ""),
                endpoint_type=c.get("endpoint_type", CoreClaim.EndpointType.OTHER),
                source_passage=c.get("source_passage", ""),
                source_reference=c.get("source_reference", ""),
                fair_balance=c.get("fair_balance", ""),
                fair_balance_reference=c.get("fair_balance_reference", ""),
                fidelity_checklist=c.get("fidelity_checklist", {}),
                status=CoreClaim.Status.AI_DRAFT,
                ai_generated=True,
            )
            for c in claims_data
        ])

        log_action(request, paper, AuditLog.Action.AI_DRAFT,
                   after={"claims_extracted": len(claims_data)})

    except Exception as exc:
        logger.error("Claim extraction failed for paper %s: %s", paper_pk, exc)
        claims = list(CoreClaim.all_objects.filter(paper=paper, deleted_at__isnull=True))
        approved_count = sum(1 for c in claims if c.status == CoreClaim.Status.APPROVED)
        return render(request, "claims/partials/claims_panel.html", {
            "paper": paper,
            "claims": claims,
            "approved_count": approved_count,
            "error": str(exc),
        })

    claims = list(CoreClaim.all_objects.filter(paper=paper, deleted_at__isnull=True))
    approved_count = sum(1 for c in claims if c.status == CoreClaim.Status.APPROVED)
    return render(request, "claims/partials/claims_panel.html", {
        "paper": paper,
        "claims": claims,
        "approved_count": approved_count,
    })


@login_required
@require_POST
def approve_claim(request, claim_pk):
    """Approve a claim — advances paper to CLAIMS_GENERATED if first approval."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    linked = request.GET.get("linked")
    tmpl = "claims/partials/linked_claim_row.html" if linked else "claims/partials/claim_card.html"

    if not linked:
        if not claim.fidelity_complete:
            return render(request, tmpl, {"claim": claim, "error": "Complete the fidelity checklist before approving."})
        if not claim.fair_balance.strip():
            return render(request, tmpl, {"claim": claim, "error": "A fair balance statement is required before approving."})

    before = {"status": claim.status}
    claim.status = CoreClaim.Status.APPROVED
    claim.reviewed_by = request.user
    claim.reviewed_at = timezone.now()
    claim.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    log_action(request, claim, AuditLog.Action.APPROVE,
               before=before, after={"status": claim.status})

    paper = claim.paper
    if paper.status == Paper.Status.SUMMARISED:
        paper.status = Paper.Status.CLAIMS_GENERATED
        paper.save(update_fields=["status", "updated_at"])

    return render(request, tmpl, {"claim": claim})


@login_required
@require_POST
def reject_claim(request, claim_pk):
    """Reject a claim with a required reason."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    linked = request.GET.get("linked")
    tmpl = "claims/partials/linked_claim_row.html" if linked else "claims/partials/claim_card.html"
    data = json.loads(request.body)
    reason = data.get("reason", "").strip()

    if not reason:
        return render(request, tmpl, {"claim": claim, "error": "A rejection reason is required."})

    before = {"status": claim.status}
    claim.status = CoreClaim.Status.REJECTED
    claim.rejection_reason = reason
    claim.reviewed_by = request.user
    claim.reviewed_at = timezone.now()
    claim.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])

    log_action(request, claim, AuditLog.Action.REJECT,
               before=before, after={"status": claim.status})

    return render(request, tmpl, {"claim": claim})


@login_required
@require_POST
def edit_claim(request, claim_pk):
    """Save inline edits to a claim and bump version."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    linked = request.GET.get("linked")
    tmpl = "claims/partials/linked_claim_row.html" if linked else "claims/partials/claim_card.html"

    if claim.status == CoreClaim.Status.APPROVED:
        return render(request, tmpl, {
            "claim": claim,
            "error": "Approved claims cannot be edited. Reject first to revise.",
        })

    data = json.loads(request.body)
    before = {
        "claim_text": claim.claim_text,
        "fair_balance": claim.fair_balance,
        "fidelity_checklist": claim.fidelity_checklist,
    }

    claim.commercial_headline = data.get("commercial_headline", claim.commercial_headline)
    claim.claim_text = data.get("claim_text", claim.claim_text)
    claim.endpoint_type = data.get("endpoint_type", claim.endpoint_type)
    claim.source_passage = data.get("source_passage", claim.source_passage)
    claim.source_reference = data.get("source_reference", claim.source_reference)
    claim.fair_balance = data.get("fair_balance", claim.fair_balance)
    claim.fair_balance_reference = data.get("fair_balance_reference", claim.fair_balance_reference)
    claim.fidelity_checklist = data.get("fidelity_checklist", claim.fidelity_checklist)

    if claim.status == CoreClaim.Status.REJECTED:
        claim.status = CoreClaim.Status.IN_REVIEW
        claim.rejection_reason = ""

    claim.version += 1
    claim.save()

    log_action(request, claim, AuditLog.Action.UPDATE,
               before=before, after={"claim_text": claim.claim_text})

    return render(request, tmpl, {"claim": claim})


@login_required
@require_POST
def run_mlr_validation(request, claim_pk):
    """Run MLR compliance check against a claim and return the updated claim card."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)

    from .services.mlr_validation import validate_claim, apply_mlr_result

    try:
        result = validate_claim(claim)
        apply_mlr_result(claim, result)
        claim.save(update_fields=[
            "mlr_compliance_score", "mlr_verdict", "mlr_red_flags",
            "mlr_rule_results", "mlr_rationale", "mlr_checked_at", "updated_at",
        ])
        log_action(request, claim, AuditLog.Action.UPDATE,
                   after={"mlr_verdict": claim.mlr_verdict, "mlr_score": claim.mlr_compliance_score})
    except Exception as exc:
        logger.error("MLR validation failed for claim %s: %s", claim_pk, exc)
        return render(request, "claims/partials/claim_card.html", {
            "claim": claim,
            "error": f"MLR check failed: {exc}",
        })

    return render(request, "claims/partials/claim_card.html", {"claim": claim})


@login_required
@require_POST
def suggest_claims(request, paper_pk):
    """Run AI extraction from the paper detail modal and return the claims section partial."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .services.extraction import extract_claims as _extract

    error = None
    try:
        claims_data = _extract(paper)

        CoreClaim.all_objects.filter(paper=paper, status=CoreClaim.Status.AI_DRAFT).delete()

        CoreClaim.all_objects.bulk_create([
            CoreClaim(
                tenant=request.tenant,
                paper=paper,
                commercial_headline=c.get("commercial_headline", ""),
                claim_text=c.get("claim_text", ""),
                endpoint_type=c.get("endpoint_type", CoreClaim.EndpointType.OTHER),
                source_passage=c.get("source_passage", ""),
                source_reference=c.get("source_reference", ""),
                fair_balance=c.get("fair_balance", ""),
                fair_balance_reference=c.get("fair_balance_reference", ""),
                fidelity_checklist=c.get("fidelity_checklist", {}),
                status=CoreClaim.Status.AI_DRAFT,
                ai_generated=True,
            )
            for c in claims_data
        ])

        log_action(request, paper, AuditLog.Action.AI_DRAFT,
                   after={"claims_extracted": len(claims_data)})

    except Exception as exc:
        logger.error("Suggest claims failed for paper %s: %s", paper_pk, exc)
        error = str(exc)

    claims = list(CoreClaim.all_objects.filter(paper=paper, deleted_at__isnull=True))
    return render(request, "literature/partials/paper_claims_section.html", {
        "paper": paper,
        "claims": claims,
        "error": error,
    })


@login_required
@require_POST
def update_fidelity(request, claim_pk):
    """Save fidelity checklist state (individual checkbox toggle)."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    data = json.loads(request.body)
    claim.fidelity_checklist = data.get("fidelity_checklist", claim.fidelity_checklist)
    claim.save(update_fields=["fidelity_checklist", "updated_at"])
    return render(request, "claims/partials/claim_card.html", {"claim": claim})
