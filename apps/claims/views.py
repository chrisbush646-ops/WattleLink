import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import CoreClaim

logger = logging.getLogger(__name__)


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
    """Trigger async AI claim extraction, return spinner immediately."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    from .tasks import extract_claims_task
    extract_claims_task.delay(paper.pk, request.tenant.pk)

    return render(request, "claims/partials/ai_processing.html", {
        "paper": paper,
    })


@login_required
@require_POST
def approve_claim(request, claim_pk):
    """Approve a claim — advances paper to CLAIMS_GENERATED if first approval."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)

    if not claim.fidelity_complete:
        return render(request, "claims/partials/claim_card.html", {
            "claim": claim,
            "error": "Complete the fidelity checklist before approving.",
        })

    if not claim.fair_balance.strip():
        return render(request, "claims/partials/claim_card.html", {
            "claim": claim,
            "error": "A fair balance statement is required before approving.",
        })

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

    return render(request, "claims/partials/claim_card.html", {"claim": claim})


@login_required
@require_POST
def reject_claim(request, claim_pk):
    """Reject a claim with a required reason."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    data = json.loads(request.body)
    reason = data.get("reason", "").strip()

    if not reason:
        return render(request, "claims/partials/claim_card.html", {
            "claim": claim,
            "error": "A rejection reason is required.",
        })

    before = {"status": claim.status}
    claim.status = CoreClaim.Status.REJECTED
    claim.rejection_reason = reason
    claim.reviewed_by = request.user
    claim.reviewed_at = timezone.now()
    claim.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])

    log_action(request, claim, AuditLog.Action.REJECT,
               before=before, after={"status": claim.status})

    return render(request, "claims/partials/claim_card.html", {"claim": claim})


@login_required
@require_POST
def edit_claim(request, claim_pk):
    """Save inline edits to a claim and bump version."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)

    if claim.status == CoreClaim.Status.APPROVED:
        return render(request, "claims/partials/claim_card.html", {
            "claim": claim,
            "error": "Approved claims cannot be edited. Reject first to revise.",
        })

    data = json.loads(request.body)
    before = {
        "claim_text": claim.claim_text,
        "fair_balance": claim.fair_balance,
        "fidelity_checklist": claim.fidelity_checklist,
    }

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

    return render(request, "claims/partials/claim_card.html", {"claim": claim})


@login_required
@require_POST
def update_fidelity(request, claim_pk):
    """Save fidelity checklist state (individual checkbox toggle)."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    data = json.loads(request.body)
    claim.fidelity_checklist = data.get("fidelity_checklist", claim.fidelity_checklist)
    claim.save(update_fields=["fidelity_checklist", "updated_at"])
    return render(request, "claims/partials/claim_card.html", {"claim": claim})
