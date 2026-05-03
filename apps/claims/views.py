import json
import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
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
    source_passage = request.POST.get("source_passage", "").strip()
    source_reference = request.POST.get("source_reference", "").strip()

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
        source_passage=source_passage,
        source_reference=source_reference,
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
    """Dispatch AI claim extraction as a background task and return the processing indicator."""
    from django.core.cache import cache
    from .tasks import extract_claims_task

    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    task = extract_claims_task.delay(paper.pk, request.tenant.pk)
    cache.set(f"ai_claims_task:{paper_pk}", task.id, timeout=3600)
    return render(request, "claims/partials/ai_processing.html", {"paper": paper})


@role_required(User.Role.MEDICAL_AFFAIRS, User.Role.MEDICAL_LEAD, User.Role.ADMIN, User.Role.EDITOR)
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


@role_required(User.Role.MEDICAL_AFFAIRS, User.Role.MEDICAL_LEAD, User.Role.ADMIN, User.Role.EDITOR)
@require_POST
def reject_claim(request, claim_pk):
    """Reject a claim with a mandatory reason. Returns 200 with unchanged claim if reason is empty."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    data = json.loads(request.body) if request.body else {}
    reason = data.get("reason", "").strip()

    if not reason:
        return render(request, "claims/partials/claim_card.html", {"claim": claim})

    before = {"status": claim.status}
    claim.status = CoreClaim.Status.REJECTED
    claim.rejection_reason = reason
    claim.reviewed_by = request.user
    claim.reviewed_at = timezone.now()
    claim.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])
    log_action(request, claim, AuditLog.Action.REJECT,
               before=before, after={"status": claim.status, "reason": reason[:200]})
    return render(request, "claims/partials/claim_card.html", {"claim": claim})


@login_required
@require_POST
def match_source_passage(request):
    """Given a claim text and paper pk, return the best matching source passage."""
    from django.http import JsonResponse
    import anthropic
    from django.conf import settings

    data = json.loads(request.body)
    claim_text = data.get("claim_text", "").strip()
    paper_pk = data.get("paper_pk")

    if not claim_text or not paper_pk:
        return JsonResponse({"error": "claim_text and paper_pk required"}, status=400)

    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    full_text = paper.full_text or ""
    if not full_text.strip():
        return JsonResponse({"passage": "", "reference": "Full text not available"})

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        return JsonResponse({"error": "AI not configured"}, status=500)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=(
                "You are a medical literature assistant. Given a claim and a paper's full text, "
                "find the single best passage (1–3 sentences) that directly supports the claim. "
                "Return a JSON object with two keys: "
                "\"passage\" (the exact verbatim text from the paper) and "
                "\"reference\" (page, section, or table reference if identifiable, otherwise empty string). "
                "Return ONLY valid JSON, no prose."
            ),
            messages=[{"role": "user", "content": f"CLAIM: {claim_text}\n\nPAPER TEXT:\n{full_text[:12000]}"}],
        )
        import json as _json
        result = _json.loads(response.content[0].text.strip())
        return JsonResponse({"passage": result.get("passage", ""), "reference": result.get("reference", "")})
    except Exception as e:
        logger.error("match_source_passage error: %s", e)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def delete_claim(request, claim_pk):
    """Permanently soft-delete a claim."""
    claim = get_object_or_404(CoreClaim.all_objects, pk=claim_pk, tenant=request.tenant)
    claim.deleted_at = timezone.now()
    claim.save(update_fields=["deleted_at", "updated_at"])
    log_action(request, claim, AuditLog.Action.REJECT,
               before={"status": claim.status}, after={"deleted": True})
    return HttpResponse("")


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
def claims_stats(request):
    """Lightweight partial returning just the KPI counts — used by the auto-refresh mechanism."""
    all_qs = CoreClaim.all_objects.filter(tenant=request.tenant, deleted_at__isnull=True)
    return render(request, "claims/partials/claims_stats.html", {
        "approved_count": all_qs.filter(status=CoreClaim.Status.APPROVED).count(),
        "pending_count": all_qs.filter(status__in=[CoreClaim.Status.AI_DRAFT, CoreClaim.Status.IN_REVIEW]).count(),
        "total_count": all_qs.count(),
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
