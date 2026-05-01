import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.engagement.models import AdvisoryBoard, Conference, OtherEvent, RoundTable
from apps.literature.models import Paper

from .models import KOL, KOLCandidate, KOLPaperLink, KOLTalkingPoint

logger = logging.getLogger(__name__)

_CANDIDATE_CTX = lambda: {"tier_range": range(1, 6)}


def _candidate_list_ctx(request):
    return KOLCandidate.objects.filter(
        tenant=request.tenant,
        status=KOLCandidate.Status.PENDING,
    ).select_related("paper").order_by("-created_at")


def _candidate_counts(request):
    base = KOLCandidate.objects.filter(tenant=request.tenant)
    return {
        "pending":  base.filter(status=KOLCandidate.Status.PENDING).count(),
        "accepted": base.filter(status=KOLCandidate.Status.ACCEPTED).count(),
        "rejected": base.filter(status=KOLCandidate.Status.REJECTED).count(),
    }


def _render_candidate_list(request, tab="pending", toast=None):
    counts = _candidate_counts(request)
    if tab == "accepted":
        candidates = KOLCandidate.objects.filter(
            tenant=request.tenant,
            status=KOLCandidate.Status.ACCEPTED,
        ).select_related("paper", "kol", "reviewed_by").order_by("-reviewed_at")
    elif tab == "rejected":
        candidates = KOLCandidate.objects.filter(
            tenant=request.tenant,
            status=KOLCandidate.Status.REJECTED,
        ).select_related("paper", "reviewed_by").order_by("-reviewed_at")
    else:
        tab = "pending"
        candidates = KOLCandidate.objects.filter(
            tenant=request.tenant,
            status=KOLCandidate.Status.PENDING,
        ).select_related("paper").order_by("-created_at")
    ctx = {
        "candidates": candidates,
        "tab": tab,
        "counts": counts,
        "tier_range": range(1, 6),
    }
    if toast:
        ctx["toast"] = toast
    return render(request, "kol/partials/candidate_list.html", ctx)


# ── KOL Directory ─────────────────────────────────────────────────────────────

@login_required
def kol_list(request):
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    status_filter = request.GET.get("status", "")
    tier_filter = request.GET.get("tier", "")
    location_filter = request.GET.get("location", "").strip()
    specialty_filter = request.GET.get("specialty", "").strip()

    if status_filter:
        kols = kols.filter(status=status_filter)
    if tier_filter:
        kols = kols.filter(tier=tier_filter)
    if location_filter:
        kols = kols.filter(location__icontains=location_filter)
    if specialty_filter:
        kols = kols.filter(specialty__icontains=specialty_filter)

    pending_candidates = _candidate_list_ctx(request)
    candidate_counts = _candidate_counts(request)
    total_candidate_count = sum(candidate_counts.values())

    ctx = {
        "kols": kols,
        "pending_candidates": pending_candidates,
        "pending_count": candidate_counts["pending"],
        "candidate_counts": candidate_counts,
        "total_candidate_count": total_candidate_count,
        "status_filter": status_filter,
        "tier_filter": tier_filter,
        "location_filter": location_filter,
        "specialty_filter": specialty_filter,
        "status_choices": KOL.Status.choices,
        "tier_range": range(1, 6),
    }

    if request.htmx:
        return render(request, "kol/partials/kol_list_inner.html", ctx)
    return render(request, "kol/kol_list.html", ctx)


@login_required
def kol_directory(request):
    """Accepted KOLs directory — no AI panels, full tier/status/location filtering."""
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    status_filter = request.GET.get("status", "")
    tier_filter   = request.GET.get("tier", "")
    location_filter  = request.GET.get("location", "").strip()
    specialty_filter = request.GET.get("specialty", "").strip()
    search_filter    = request.GET.get("q", "").strip()

    if status_filter:
        kols = kols.filter(status=status_filter)
    if tier_filter:
        kols = kols.filter(tier=tier_filter)
    if location_filter:
        kols = kols.filter(location__icontains=location_filter)
    if specialty_filter:
        kols = kols.filter(specialty__icontains=specialty_filter)
    if search_filter:
        kols = kols.filter(name__icontains=search_filter)

    # Tier counts for KPI bar
    from django.db.models import Count
    tier_counts = {
        i: KOL.objects.filter(tenant=request.tenant, tier=i).count()
        for i in range(1, 6)
    }

    ctx = {
        "kols": kols,
        "status_filter": status_filter,
        "tier_filter": tier_filter,
        "location_filter": location_filter,
        "specialty_filter": specialty_filter,
        "search_filter": search_filter,
        "status_choices": KOL.Status.choices,
        "tier_range": range(1, 6),
        "tier_counts": tier_counts,
        "total_kols": KOL.objects.filter(tenant=request.tenant).count(),
    }

    if request.htmx:
        return render(request, "kol/partials/kol_list_inner.html", ctx)
    return render(request, "kol/accepted_kols.html", ctx)


@login_required
def kol_detail(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    paper_links = kol.paper_links.select_related("paper")
    available_papers = Paper.objects.exclude(
        pk__in=paper_links.values_list("paper_id", flat=True)
    )
    events_attended = {
        "conferences": Conference.objects.filter(kols=kol),
        "round_tables": RoundTable.objects.filter(kols=kol),
        "advisory_boards": AdvisoryBoard.objects.filter(kols=kol),
        "other_events": OtherEvent.objects.filter(kols=kol),
    }
    return render(request, "kol/kol_detail.html", {
        "kol": kol,
        "paper_links": paper_links,
        "available_papers": available_papers,
        "tier_range": range(1, 6),
        "status_choices": KOL.Status.choices,
        "events_attended": events_attended,
    })


@login_required
@require_POST
def create_kol(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    if not name:
        return render(request, "kol/partials/kol_form_error.html", {"error": "Name is required."})

    kol = KOL.objects.create(
        tenant=request.tenant,
        name=name,
        institution=data.get("institution", ""),
        specialty=data.get("specialty", ""),
        tier=int(data.get("tier", 3)),
        location=data.get("location", ""),
        bio=data.get("bio", ""),
        status=KOL.Status.CANDIDATE,
        created_by=request.user,
    )
    log_action(request, kol, AuditLog.Action.CREATE, after={"name": kol.name})
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    return render(request, "kol/partials/kol_list_inner.html", {
        "kols": kols,
        "tier_range": range(1, 6),
        "status_choices": KOL.Status.choices,
    })


@login_required
def suggest_papers_for_kol(request, kol_pk):
    """Return papers from the database whose titles/journals match the KOL's specialty and bio."""
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)

    _STOP = {
        'a','an','the','and','or','but','in','on','at','to','for','of','with','by',
        'is','are','was','were','has','have','had','been','being','be','not','no',
        'this','that','which','who','from','into','over','after','about','as','can',
        'will','may','also','more','most','such','both','all','any','some','than',
        'then','its','his','her','they','them','our','we','he','she','it','very',
        'one','two','type','study','clinical','trial','trials','drug','drugs',
        'patient','patients','treatment','treatments','including','however','within',
        'without','whether','often','well','new','many','other','these','those',
        'through','between','during','part','their','first','second','third','using',
        'used','use','based','high','low','compared','associated','results','data',
        'effect','effects','outcome','outcomes','risk','risks',
    }

    terms = []
    if kol.specialty:
        for t in kol.specialty.replace(',', ' ').replace('/', ' ').split():
            t = t.strip('.,;:()"\'').lower()
            if len(t) > 2:
                terms.append(t)
    if kol.bio:
        for w in kol.bio.lower().split():
            w = w.strip('.,;:()"\'!?-')
            if len(w) > 4 and w not in _STOP:
                terms.append(w)

    # Deduplicate preserving order, keep top 12 most specific
    seen = set()
    unique_terms = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique_terms.append(t)
        if len(unique_terms) == 12:
            break

    already_linked = kol.paper_links.values_list("paper_id", flat=True)

    if unique_terms:
        from django.db.models import Q
        q = Q()
        for term in unique_terms:
            q |= Q(title__icontains=term) | Q(journal__icontains=term)
        papers = (
            Paper.objects
            .filter(q)
            .exclude(pk__in=already_linked)
            .order_by("-published_date")[:12]
        )
    else:
        papers = Paper.objects.none()

    return render(request, "kol/partials/suggested_papers.html", {
        "kol": kol,
        "papers": papers,
        "terms": unique_terms[:8],
    })


@login_required
@require_POST
def delete_kol(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    log_action(request, kol, AuditLog.Action.UPDATE, before={"name": kol.name, "status": kol.status})
    kol.soft_delete()
    return render(request, "kol/partials/kol_deleted.html", {"kol": kol})


@login_required
@require_POST
def update_kol(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    data = json.loads(request.body)
    before = {"status": kol.status, "tier": kol.tier}
    kol.status = data.get("status", kol.status)
    kol.tier = int(data.get("tier", kol.tier))
    kol.institution = data.get("institution", kol.institution)
    kol.specialty = data.get("specialty", kol.specialty)
    kol.location = data.get("location", kol.location)
    kol.bio = data.get("bio", kol.bio)
    kol.notes = data.get("notes", kol.notes)
    kol.email = data.get("email", kol.email)
    kol.linkedin = data.get("linkedin", kol.linkedin)
    kol.save()
    log_action(request, kol, AuditLog.Action.UPDATE,
               before=before, after={"status": kol.status, "tier": kol.tier})
    return render(request, "kol/partials/kol_card.html", {
        "kol": kol,
        "tier_range": range(1, 6),
        "status_choices": KOL.Status.choices,
    })


@login_required
@require_POST
def suggest_kols(request):
    """Run AI keyword search and create KOLCandidate records. Returns suggest results partial."""
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "kol/partials/suggest_results.html", {
            "error": "Please enter a search term.",
            "query": query,
        })

    from .services.discovery import suggest_kols_by_keyword

    try:
        candidates_data = suggest_kols_by_keyword(query)
    except Exception as exc:
        logger.error("KOL suggest failed: %s", exc)
        return render(request, "kol/partials/suggest_results.html", {
            "error": f"AI search failed: {exc}",
            "query": query,
        })

    created = []
    for c in candidates_data:
        candidate = KOLCandidate.objects.create(
            tenant=request.tenant,
            paper=None,
            search_query=query,
            name=c.get("name", ""),
            institution=c.get("institution", ""),
            specialty=c.get("specialty", ""),
            tier=int(c.get("tier", 3)),
            location=c.get("location", ""),
            bio=c.get("bio", ""),
            relevance_note=c.get("relevance_note", ""),
            status=KOLCandidate.Status.PENDING,
        )
        created.append(candidate)

    return render(request, "kol/partials/suggest_results.html", {
        "candidates": created,
        "query": query,
        "tier_range": range(1, 6),
    })


@login_required
@require_POST
def discover_from_paper(request, paper_pk):
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    from .tasks import discover_kols_task
    discover_kols_task.delay(paper.pk, request.tenant.pk)
    return render(request, "kol/partials/discovery_queued.html", {"paper": paper})


@login_required
@require_POST
def link_paper(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    data = json.loads(request.body)
    paper_pk = data.get("paper_pk")
    if not paper_pk:
        return render(request, "kol/partials/kol_form_error.html", {"error": "Paper is required."})
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    KOLPaperLink.objects.get_or_create(
        kol=kol, paper=paper,
        defaults={
            "relevance_note": data.get("relevance_note", ""),
            "is_author": data.get("is_author", False),
        },
    )
    paper_links = kol.paper_links.select_related("paper")
    return render(request, "kol/partials/paper_links_table.html", {
        "kol": kol, "paper_links": paper_links
    })


@login_required
@require_POST
def unlink_paper(request, link_pk):
    link = get_object_or_404(KOLPaperLink, pk=link_pk, kol__tenant=request.tenant)
    kol = link.kol
    link.delete()
    paper_links = kol.paper_links.select_related("paper")
    return render(request, "kol/partials/paper_links_table.html", {
        "kol": kol, "paper_links": paper_links
    })


# ── KOL Talking Points ───────────────────────────────────────────────────────

_TALKING_POINTS_SYSTEM = """You are an expert medical affairs strategist supporting MSLs (Medical Science Liaisons) in Australia.
Your task is to generate specific, evidence-based talking points for an MSL meeting with a Key Opinion Leader (KOL).

Each talking point must:
- Be directly relevant to the KOL's research specialty and linked publications
- Be a concrete, discussion-opening statement or question — not generic
- Reference specific evidence where possible (study names, endpoints, mechanisms)
- Be appropriate for a scientific exchange between peers (not promotional)
- Be 1-3 sentences long

Return ONLY a JSON object in this exact format:
{
  "talking_points": [
    {"text": "...", "source_note": "Based on [paper/topic]"},
    ...
  ]
}

Generate 6-8 talking points. No preamble, no explanation outside the JSON."""


def _generate_talking_points_for_kol(kol, paper_links):
    """Call Claude to generate talking points. Returns list of {text, source_note} dicts."""
    import anthropic
    import json as json_module
    from django.conf import settings

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    papers_summary = ""
    for link in paper_links[:8]:
        p = link.paper
        year = p.published_date.year if p.published_date else "n.d."
        authors = ", ".join(p.authors[:2]) if isinstance(p.authors, list) else str(p.authors)
        papers_summary += f"- {authors} ({year}). {p.title}. {p.journal}.\n"
        if link.is_author:
            papers_summary += "  (KOL is an author on this paper)\n"
        if link.relevance_note:
            papers_summary += f"  Relevance: {link.relevance_note}\n"

    user_message = f"""KOL Profile:
Name: {kol.name}
Institution: {kol.institution or 'Not specified'}
Specialty: {kol.specialty or 'Not specified'}
Location: {kol.location or 'Not specified'}
Tier: {kol.tier} (1=highest influence, 5=lowest)
Bio: {kol.bio or 'Not provided'}

Linked Publications:
{papers_summary if papers_summary else 'No linked papers yet.'}

Generate talking points for an MSL meeting with this KOL."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_TALKING_POINTS_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json_module.loads(raw)
    return data.get("talking_points", [])


@login_required
@require_POST
def generate_talking_points(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    paper_links = kol.paper_links.select_related("paper")
    try:
        draft_points = _generate_talking_points_for_kol(kol, paper_links)
    except Exception as exc:
        logger.error("Talking points generation failed for KOL %s: %s", kol_pk, exc)
        return render(request, "kol/partials/talking_points_draft.html", {
            "kol": kol,
            "error": str(exc),
        })
    return render(request, "kol/partials/talking_points_draft.html", {
        "kol": kol,
        "draft_points": draft_points,
    })


@login_required
@require_POST
def save_talking_point(request, kol_pk):
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    text = request.POST.get("text", "").strip()
    source_note = request.POST.get("source_note", "").strip()
    if text:
        KOLTalkingPoint.objects.create(
            kol=kol,
            text=text,
            source_note=source_note,
            created_by=request.user,
        )
    return render(request, "kol/partials/talking_points_saved.html", {
        "kol": kol,
        "talking_points": kol.talking_points.all(),
    })


@login_required
@require_POST
def delete_talking_point(request, tp_pk):
    tp = get_object_or_404(KOLTalkingPoint, pk=tp_pk, kol__tenant=request.tenant)
    kol = tp.kol
    tp.delete()
    return render(request, "kol/partials/talking_points_saved.html", {
        "kol": kol,
        "talking_points": kol.talking_points.all(),
    })


# ── KOL Candidates ────────────────────────────────────────────────────────────

@login_required
def candidate_list(request):
    """HTMX — return candidate list filtered by tab (pending/accepted/rejected)."""
    tab = request.GET.get("tab", "pending")
    return _render_candidate_list(request, tab=tab)


@login_required
def candidate_verify_status(request, candidate_pk):
    """HTMX poll — returns the verification badge once AI check completes."""
    candidate = get_object_or_404(KOLCandidate, pk=candidate_pk, tenant=request.tenant)
    return render(request, "kol/partials/candidate_verify_badge.html", {
        "candidate": candidate,
    })


@login_required
@require_POST
def accept_candidate(request, candidate_pk):
    """Accept an AI-suggested KOL: creates or finds a KOL record and marks the candidate accepted."""
    candidate = get_object_or_404(KOLCandidate, pk=candidate_pk, tenant=request.tenant)
    data = json.loads(request.body) if request.body else {}

    tier = int(data.get("tier", candidate.tier))
    status_choice = data.get("kol_status", KOL.Status.CANDIDATE)

    # Find existing KOL by name, or create new one
    kol, created = KOL.objects.get_or_create(
        tenant=request.tenant,
        name=candidate.name,
        defaults={
            "institution": candidate.institution,
            "specialty": candidate.specialty,
            "tier": tier,
            "location": candidate.location,
            "bio": candidate.bio,
            "status": status_choice,
            "ai_generated": True,
            "created_by": request.user,
        },
    )
    if not created:
        # KOL already exists — just update tier if passed explicitly
        if "tier" in data:
            kol.tier = tier
            kol.save(update_fields=["tier", "updated_at"])

    # Link the source paper (only if candidate came from a paper, not a keyword search)
    if candidate.paper:
        KOLPaperLink.objects.get_or_create(
            kol=kol,
            paper=candidate.paper,
            defaults={
                "relevance_note": candidate.relevance_note,
                "is_author": candidate.is_author,
            },
        )

    candidate.status = KOLCandidate.Status.ACCEPTED
    candidate.kol = kol
    candidate.reviewed_by = request.user
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["status", "kol", "reviewed_by", "reviewed_at"])

    log_action(request, kol, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
               after={"from_candidate": candidate.pk, "name": kol.name})

    return _render_candidate_list(request, tab="pending", toast=f"{candidate.name} added to KOL directory.")


@login_required
@require_POST
def reject_candidate(request, candidate_pk):
    candidate = get_object_or_404(KOLCandidate, pk=candidate_pk, tenant=request.tenant)
    data = json.loads(request.body) if request.body else {}
    reason = data.get("reason", "").strip()

    candidate.status = KOLCandidate.Status.REJECTED
    candidate.rejection_reason = reason
    candidate.reviewed_by = request.user
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"])

    return _render_candidate_list(request, tab="pending")


@login_required
@require_POST
def hold_candidate(request, candidate_pk):
    candidate = get_object_or_404(KOLCandidate, pk=candidate_pk, tenant=request.tenant)
    data = json.loads(request.body) if request.body else {}
    reason = data.get("reason", "").strip()

    candidate.status = KOLCandidate.Status.ON_HOLD
    candidate.hold_reason = reason
    candidate.reviewed_by = request.user
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["status", "hold_reason", "reviewed_by", "reviewed_at"])

    return _render_candidate_list(request, tab="pending")
