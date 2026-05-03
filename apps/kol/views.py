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
    private = request.session.get("view_mode") == "personal"
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    if private:
        kols = kols.filter(created_by=request.user)
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    type_filter = request.GET.get("type", "")
    tier_filter = request.GET.get("tier", "")
    location_filter = request.GET.get("location", "").strip()
    specialty_filter = request.GET.get("specialty", "").strip()

    if q:
        from django.db.models import Q as _Q
        kols = kols.filter(
            _Q(name__icontains=q) |
            _Q(specialty__icontains=q) |
            _Q(institution__icontains=q) |
            _Q(location__icontains=q) |
            _Q(bio__icontains=q)
        )
    if type_filter:
        kols = kols.filter(kol_type=type_filter)
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
    deleted_kols = KOL.all_objects.filter(tenant=request.tenant, deleted_at__isnull=False).order_by("-deleted_at")

    ctx = {
        "kols": kols,
        "pending_candidates": pending_candidates,
        "pending_count": candidate_counts["pending"],
        "candidate_counts": candidate_counts,
        "total_candidate_count": total_candidate_count,
        "deleted_kols": deleted_kols,
        "q": q,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "tier_filter": tier_filter,
        "location_filter": location_filter,
        "specialty_filter": specialty_filter,
        "status_choices": KOL.Status.choices,
        "kol_type_choices": KOL.KolType.choices,
        "tier_range": range(1, 6),
    }

    if request.htmx:
        return render(request, "kol/partials/kol_list_inner.html", ctx)
    return render(request, "kol/kol_list.html", ctx)


@login_required
def kol_directory(request):
    """Accepted KOLs directory — no AI panels, full tier/status/location filtering."""
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    status_filter    = request.GET.get("status", "")
    type_filter      = request.GET.get("type", "")
    tier_filter      = request.GET.get("tier", "")
    location_filter  = request.GET.get("location", "").strip()
    specialty_filter = request.GET.get("specialty", "").strip()
    search_filter    = request.GET.get("q", "").strip()

    if type_filter:
        kols = kols.filter(kol_type=type_filter)
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

    tier_counts = {
        i: KOL.objects.filter(tenant=request.tenant, tier=i).count()
        for i in range(1, 6)
    }

    ctx = {
        "kols": kols,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "tier_filter": tier_filter,
        "location_filter": location_filter,
        "specialty_filter": specialty_filter,
        "search_filter": search_filter,
        "status_choices": KOL.Status.choices,
        "kol_type_choices": KOL.KolType.choices,
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

    kol_type = data.get("kol_type", KOL.KolType.PHYSICIAN)
    if kol_type not in KOL.KolType.values:
        kol_type = KOL.KolType.PHYSICIAN
    kol = KOL.objects.create(
        tenant=request.tenant,
        name=name,
        institution=data.get("institution", ""),
        specialty=data.get("specialty", ""),
        tier=int(data.get("tier", 3)),
        location=data.get("location", ""),
        bio=data.get("bio", ""),
        kol_type=kol_type,
        status=KOL.Status.CANDIDATE,
        created_by=request.user,
    )
    log_action(request, kol, AuditLog.Action.CREATE, after={"name": kol.name})
    kols = KOL.objects.select_related("created_by").prefetch_related("paper_links")
    return render(request, "kol/partials/kol_list_inner.html", {
        "kols": kols,
        "tier_range": range(1, 6),
        "status_choices": KOL.Status.choices,
        "kol_type_choices": KOL.KolType.choices,
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
    before = {"status": kol.status, "tier": kol.tier, "kol_type": kol.kol_type}
    kol.status = data.get("status", kol.status)
    kol.tier = int(data.get("tier", kol.tier))
    kol_type = data.get("kol_type", kol.kol_type)
    kol.kol_type = kol_type if kol_type in KOL.KolType.values else kol.kol_type
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
        "kol_type_choices": KOL.KolType.choices,
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
    _, created = KOLPaperLink.objects.get_or_create(
        kol=kol, paper=paper,
        defaults={
            "relevance_note": data.get("relevance_note", ""),
            "is_author": data.get("is_author", False),
        },
    )
    if created:
        log_action(request, kol, AuditLog.Action.UPDATE,
                   after={"linked_paper_pk": paper.pk, "paper_title": paper.title[:120]})
    paper_links = kol.paper_links.select_related("paper")
    return render(request, "kol/partials/paper_links_table.html", {
        "kol": kol, "paper_links": paper_links
    })


@login_required
@require_POST
def unlink_paper(request, link_pk):
    link = get_object_or_404(KOLPaperLink, pk=link_pk, kol__tenant=request.tenant)
    kol = link.kol
    paper_title = link.paper.title[:120]
    paper_pk = link.paper.pk
    link.delete()
    log_action(request, kol, AuditLog.Action.UPDATE,
               before={"unlinked_paper_pk": paper_pk, "paper_title": paper_title})
    paper_links = kol.paper_links.select_related("paper")
    return render(request, "kol/partials/paper_links_table.html", {
        "kol": kol, "paper_links": paper_links
    })


# ── KOL Talking Points ───────────────────────────────────────────────────────

_TALKING_POINTS_SYSTEM = """You are an expert medical affairs strategist supporting MSLs (Medical Science Liaisons) in Australia.
Your task is to generate specific, evidence-based talking points for an upcoming MSL meeting with a Key Opinion Leader (KOL).

## Priority order for source content

1. **Stored library papers (most recent first)** — cite these precisely with author, year, journal, and specific endpoint or finding.
2. **Recent Australian developments you know about** — TGA approvals or safety updates, PBAC decisions, PBS listings/restrictions or delisting, RACGP/specialist college guideline updates, Australian conference presentations (COSA, CSANZ, ANZAN, RACP Congress, Endocrine Society of Australia ASM, ANZSN, ANZCHOG), recent Australian medical media (MJA, Australian Prescriber, NPS MedicineWise, Healthed, Australian Medical Observer, ABC Health, The Guardian Australia Health & Science).
3. **Global landmark studies** directly relevant to this KOL's work — use as supporting context for an Australian discussion.

## Rules for each talking point

- Must be directly relevant to the KOL's research specialty and specific interests — NOT generic
- Opens a scientific peer-to-peer discussion — NOT promotional in tone
- References a specific data point, endpoint, mechanism, or Australian context
- 1–3 sentences. Concrete and precise.
- `source_note` must be specific: paper reference (Author et al., Journal, Year) OR Australian context description (e.g. "TGA approval Oct 2024", "PBAC November 2024 meeting", "MJA editorial March 2025", "CSANZ 2024 abstract")

Return ONLY a JSON object in this exact format (no preamble, no text outside the JSON):
{
  "talking_points": [
    {"text": "...", "source_note": "..."},
    ...
  ]
}

Generate 6–8 talking points. Lead with the most recent and topical ones first."""


def _generate_talking_points_for_kol(kol, paper_links):
    """Generate talking points anchored to recent library papers and Australian context."""
    import anthropic
    import json as json_module
    from datetime import date as date_type
    from django.conf import settings

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    # Sort linked papers most recent first
    sorted_links = sorted(
        paper_links,
        key=lambda l: l.paper.published_date or date_type.min,
        reverse=True,
    )
    linked_paper_ids = set()
    linked_papers_text = ""
    for link in sorted_links[:10]:
        p = link.paper
        linked_paper_ids.add(p.pk)
        pub_date = p.published_date.strftime("%b %Y") if p.published_date else "n.d."
        authors = ", ".join(p.authors[:3]) if isinstance(p.authors, list) else str(p.authors)
        linked_papers_text += f"- [{pub_date}] {authors}. \"{p.title}\". {p.journal}."
        if link.is_author:
            linked_papers_text += " ★ KOL IS AN AUTHOR ON THIS PAPER"
        if link.relevance_note:
            linked_papers_text += f" | Note: {link.relevance_note}"
        linked_papers_text += "\n"

    # Search the library for recent unlinked papers matching the KOL's specialty
    recent_library_text = ""
    terms = []
    for field in [kol.specialty or "", kol.bio or ""]:
        for t in field.replace(',', ' ').replace('/', ' ').split():
            t = t.strip('.,;:()"\'').lower()
            if len(t) > 3 and t not in {
                'with', 'that', 'this', 'from', 'have', 'been', 'were', 'their',
                'into', 'over', 'through', 'including', 'also', 'such', 'both',
            }:
                terms.append(t)
        if len(terms) >= 8:
            break

    if terms:
        from django.db.models import Q
        q = Q()
        for term in terms[:6]:
            q |= Q(title__icontains=term) | Q(journal__icontains=term)
        recent_papers = (
            Paper.objects
            .exclude(pk__in=linked_paper_ids)
            .filter(q)
            .order_by("-published_date")[:8]
        )
        for p in recent_papers:
            pub_date = p.published_date.strftime("%b %Y") if p.published_date else "n.d."
            authors = ", ".join(p.authors[:2]) if isinstance(p.authors, list) else str(p.authors)
            recent_library_text += f"- [{pub_date}] {authors}. \"{p.title}\". {p.journal}.\n"

    user_message = f"""KOL Profile:
Name: {kol.name}
Institution: {kol.institution or 'Not specified'}
Specialty / Research area: {kol.specialty or 'Not specified'}
Location: {kol.location or 'Not specified'}
Tier: {kol.tier} (1 = highest national influence, 5 = emerging)
Bio / Expertise: {kol.bio or 'Not provided'}

## Linked publications — sorted most recent first
{linked_papers_text or 'None linked yet.'}

## Additional recent library papers matching their specialty — not yet linked
{recent_library_text or 'None found.'}

## Task
Generate 6–8 talking points for an MSL meeting with this KOL.
Lead with the most recent and topical content — prioritise papers from the last 24 months and any recent Australian regulatory, guideline, or media developments in their area.
Draw on both the library papers above AND your knowledge of recent Australian developments (TGA, PBAC, Australian specialist college guidelines, Australian medical media) relevant to their specialty."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        temperature=0,
        system=[{"type": "text", "text": _TALKING_POINTS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()
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
        tp = KOLTalkingPoint.objects.create(
            kol=kol,
            text=text,
            source_note=source_note,
            created_by=request.user,
        )
        log_action(request, kol, AuditLog.Action.CREATE,
                   after={"talking_point_pk": tp.pk, "text_preview": text[:100]})
    return render(request, "kol/partials/talking_points_saved.html", {
        "kol": kol,
        "talking_points": kol.talking_points.all(),
    })


@login_required
@require_POST
def delete_talking_point(request, tp_pk):
    tp = get_object_or_404(KOLTalkingPoint, pk=tp_pk, kol__tenant=request.tenant)
    kol = tp.kol
    log_action(request, kol, AuditLog.Action.DELETE,
               before={"talking_point_pk": tp.pk, "text_preview": tp.text[:100]})
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

    log_action(request, candidate, AuditLog.Action.UPDATE,
               after={"status": "REJECTED", "reason": reason[:200] if reason else ""})

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

    log_action(request, candidate, AuditLog.Action.UPDATE,
               after={"status": "ON_HOLD", "reason": reason[:200] if reason else ""})

    return _render_candidate_list(request, tab="pending")


@login_required
@require_POST
def re_add_candidate(request, candidate_pk):
    candidate = get_object_or_404(KOLCandidate, pk=candidate_pk, tenant=request.tenant)
    candidate.status = KOLCandidate.Status.PENDING
    candidate.rejection_reason = ""
    candidate.reviewed_by = None
    candidate.reviewed_at = None
    candidate.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"])
    log_action(request, candidate, AuditLog.Action.UPDATE,
               after={"status": "PENDING", "re_added_by": request.user.pk})
    return _render_candidate_list(
        request, tab="pending",
        toast=f"{candidate.name} moved back to pending review."
    )


@login_required
@require_POST
def restore_kol(request, kol_pk):
    from django.http import HttpResponse
    kol = get_object_or_404(KOL.all_objects, pk=kol_pk, tenant=request.tenant)
    kol.restore()
    log_action(request, kol, AuditLog.Action.UPDATE,
               after={"name": kol.name, "restored": True})
    return HttpResponse(f'<div id="removed-kol-{kol.pk}" style="display:none"></div>')


@login_required
@require_POST
def permanently_delete_kol(request, kol_pk):
    from django.http import HttpResponse
    kol = get_object_or_404(KOL.all_objects, pk=kol_pk, tenant=request.tenant)
    log_action(request, kol, AuditLog.Action.DELETE,
               before={"name": kol.name, "permanent_delete": True})
    kol.delete()
    return HttpResponse(f'<div id="removed-kol-{kol_pk}" style="display:none"></div>')
