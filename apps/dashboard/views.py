import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.claims.models import CoreClaim
from apps.engagement.models import Conference, RoundTable
from apps.kol.models import KOL, KOLCandidate
from apps.literature.models import Paper
from apps.safety.models import SafetySignal
from apps.summaries.models import PaperSummary


def home_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard:index")
    return render(request, "marketing/home.html")


def faq(request):
    return render(request, "marketing/faq.html")


def contact(request):
    if request.method == "POST":
        data = {
            "first_name": request.POST.get("first_name", "").strip(),
            "last_name": request.POST.get("last_name", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "organisation": request.POST.get("organisation", "").strip(),
            "enquiry_type": request.POST.get("enquiry_type", "").strip(),
            "message": request.POST.get("message", "").strip(),
        }
        if not data["first_name"] or not data["email"] or not data["message"]:
            return render(request, "marketing/contact.html", {
                "form_data": data,
                "error": "Please fill in your first name, email address and message.",
            })
        logger.info(
            "Contact enquiry from %s %s <%s> [%s]: %s",
            data["first_name"], data["last_name"], data["email"],
            data["enquiry_type"], data["message"][:120],
        )
        return render(request, "marketing/contact.html", {"sent": True})

    return render(request, "marketing/contact.html")


@login_required
def dashboard(request):
    now = timezone.localtime()
    today = now.date()
    hour = now.hour
    if hour < 12:
        greeting = "morning"
    elif hour < 18:
        greeting = "afternoon"
    else:
        greeting = "evening"

    papers = Paper.objects.all()
    paper_statuses = [p.status for p in papers]

    counts = {
        "ingested": len(paper_statuses),
        "assessed": sum(1 for s in paper_statuses if s in (
            Paper.Status.ASSESSED, Paper.Status.SUMMARISED,
            Paper.Status.CLAIMS_GENERATED, Paper.Status.APPROVED,
        )),
        "summarised": sum(1 for s in paper_statuses if s in (
            Paper.Status.SUMMARISED, Paper.Status.CLAIMS_GENERATED, Paper.Status.APPROVED,
        )),
        "claims_generated": CoreClaim.objects.count(),
        "claims_approved": CoreClaim.objects.filter(status=CoreClaim.Status.APPROVED).count(),
    }

    awaiting = papers.filter(status__in=[
        Paper.Status.INGESTED,
        Paper.Status.ASSESSED,
        Paper.Status.SUMMARISED,
    ]).order_by("status", "published_date")[:8]

    recent_decisions = CoreClaim.objects.filter(
        status__in=[CoreClaim.Status.APPROVED, CoreClaim.Status.REJECTED]
    ).select_related("paper", "reviewed_by").order_by("-reviewed_at")[:6]

    upcoming_conferences = Conference.objects.filter(
        status=Conference.Status.UPCOMING,
        start_date__gte=today,
    ).order_by("start_date")[:4]

    upcoming_roundtables = RoundTable.objects.filter(
        date__gte=today,
    ).order_by("date")[:4]

    active_signals = SafetySignal.objects.filter(
        status=SafetySignal.Status.ACTIVE,
    ).order_by("-severity")[:6]

    top_kols = KOL.objects.filter(
        status=KOL.Status.ACTIVE,
    ).prefetch_related("paper_links").order_by("tier", "name")[:6]

    pending_candidates = KOLCandidate.objects.filter(
        status=KOLCandidate.Status.PENDING,
    ).select_related("paper").order_by("-created_at")[:5]

    kol_counts = {
        "active": KOL.objects.filter(status=KOL.Status.ACTIVE).count(),
        "candidates": KOLCandidate.objects.filter(status=KOLCandidate.Status.PENDING).count(),
    }

    next_step_labels = {
        Paper.Status.INGESTED: "Needs assessment",
        Paper.Status.ASSESSED: "Needs summary",
        Paper.Status.SUMMARISED: "Needs claims",
    }

    doi_stats = {
        "verified": Paper.objects.filter(doi_verified=True).count(),
        "unverified": Paper.objects.filter(doi_verified=False).exclude(doi="").count(),
        "missing": Paper.objects.filter(doi="").count(),
    }

    return render(request, "dashboard/index.html", {
        "counts": counts,
        "awaiting": awaiting,
        "recent_decisions": recent_decisions,
        "upcoming_conferences": upcoming_conferences,
        "upcoming_roundtables": upcoming_roundtables,
        "active_signals": active_signals,
        "top_kols": top_kols,
        "pending_candidates": pending_candidates,
        "kol_counts": kol_counts,
        "next_step_labels": next_step_labels,
        "greeting": greeting,
        "doi_stats": doi_stats,
    })


@login_required
def commercial(request):
    today = timezone.localtime().date()

    approved_summaries = (
        PaperSummary.objects.filter(status=PaperSummary.Status.CONFIRMED)
        .select_related("paper", "confirmed_by")
        .prefetch_related("findings")
        .order_by("-confirmed_at", "-updated_at")[:8]
    )

    approved_claims = (
        CoreClaim.objects.filter(status=CoreClaim.Status.APPROVED)
        .select_related("paper", "reviewed_by")
        .order_by("-reviewed_at")[:10]
    )

    key_kols = (
        KOL.objects.filter(status=KOL.Status.ACTIVE, tier__lte=2)
        .prefetch_related("paper_links__paper")
        .order_by("tier", "name")[:8]
    )

    upcoming_conferences = (
        Conference.objects.filter(status=Conference.Status.UPCOMING, start_date__gte=today)
        .order_by("start_date")[:5]
    )

    upcoming_roundtables = (
        RoundTable.objects.filter(date__gte=today)
        .order_by("date")[:5]
    )

    return render(request, "dashboard/commercial.html", {
        "approved_summaries": approved_summaries,
        "approved_claims": approved_claims,
        "key_kols": key_kols,
        "upcoming_conferences": upcoming_conferences,
        "upcoming_roundtables": upcoming_roundtables,
    })
