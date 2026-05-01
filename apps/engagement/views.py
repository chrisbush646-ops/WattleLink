import json
import logging
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.kol.models import KOL
from apps.literature.models import Paper

from .models import AdvisoryBoard, Conference, OtherEvent, RoundTable

_MODEL_MAP = {
    'conference': Conference,
    'roundtable': RoundTable,
    'advisory': AdvisoryBoard,
    'other': OtherEvent,
}

_CARD_CTX_KEY = {
    'conference': 'conf',
    'roundtable': 'rt',
    'advisory': 'ab',
    'other': 'oe',
}

_CARD_TEMPLATE_MAP = {
    'conference': 'engagement/partials/conference_card.html',
    'roundtable': 'engagement/partials/round_table_card.html',
    'advisory': 'engagement/partials/advisory_board_card.html',
    'other': 'engagement/partials/other_event_card.html',
}

logger = logging.getLogger(__name__)

_SUGGEST_STOP = {
    'a', 'an', 'the', 'of', 'in', 'for', 'and', 'or', 'with', 'to', 'from',
    'at', 'by', 'is', 'are', 'was', 'were', 'study', 'trial', 'clinical',
    'patients', 'patient', 'treatment', 'phase', 'results', 'effect', 'effects',
    'analysis', 'randomized', 'controlled', 'double', 'blind', 'placebo',
    'versus', 'among', 'based', 'after', 'during', 'using', 'versus', 'compared',
    'following', 'open', 'label',
}


def _kol_choices(request):
    return KOL.objects.filter(
        status__in=[KOL.Status.CANDIDATE, KOL.Status.ACTIVE]
    ).order_by("name")


@login_required
def engagement_list(request):
    conferences = Conference.objects.prefetch_related("kols", "papers")
    round_tables = RoundTable.objects.prefetch_related("kols")
    advisory_boards = AdvisoryBoard.objects.prefetch_related("kols")
    other_events = OtherEvent.objects.prefetch_related("kols")

    conf_events = [
        {'date': c.start_date.isoformat(), 'end_date': c.end_date.isoformat() if c.end_date else None, 'name': c.name, 'type': 'conference'}
        for c in conferences
    ]
    rt_events = [
        {'date': rt.date.isoformat(), 'end_date': None, 'name': rt.name, 'type': 'roundtable'}
        for rt in round_tables
    ]
    ab_events = [
        {'date': ab.date.isoformat(), 'end_date': None, 'name': ab.name, 'type': 'advisory'}
        for ab in advisory_boards
    ]
    other_ev_events = [
        {'date': oe.date.isoformat(), 'end_date': None, 'name': oe.name, 'type': 'other'}
        for oe in other_events
    ]

    active_tab = request.GET.get("tab", "conferences")
    tab_items = [
        ("conferences", "Conferences", conferences.count()),
        ("roundtables", "Round Tables", round_tables.count()),
        ("advisory", "Advisory Boards", advisory_boards.count()),
        ("other", "Other Events", other_events.count()),
    ]

    return render(request, "engagement/engagement_list.html", {
        "conferences": conferences,
        "round_tables": round_tables,
        "advisory_boards": advisory_boards,
        "other_events": other_events,
        "conf_status_choices": Conference.Status.choices,
        "conf_events_json": json.dumps(conf_events),
        "rt_events_json": json.dumps(rt_events),
        "ab_events_json": json.dumps(ab_events),
        "other_events_json": json.dumps(other_ev_events),
        "active_tab": active_tab,
        "tab_items": tab_items,
        "kol_choices": _kol_choices(request),
    })


@login_required
def suggest_conferences(request):
    papers = list(Paper.objects.values_list('title', flat=True)[:60])
    words = []
    for title in papers:
        for w in title.lower().split():
            w = w.strip('.,;:()[]"\'-/')
            if len(w) > 4 and w not in _SUGGEST_STOP:
                words.append(w)

    terms = [t for t, _ in Counter(words).most_common(10)]

    if not terms:
        return render(request, 'engagement/partials/suggested_conferences.html',
                      {'suggestions': [], 'terms': [], 'no_data': True})

    import anthropic
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=(
                "You are a medical affairs assistant. Suggest relevant medical conferences "
                "for an Australian pharmaceutical MSL team. Return only valid JSON, no markdown."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Our therapeutic area is indicated by these keywords: {', '.join(terms)}.\n\n"
                    "Suggest 6 relevant medical conferences (Australian and key international) "
                    "this team should consider attending in the next 12–18 months. "
                    "For each provide: name (string), location (city, country), "
                    "timing (e.g. 'March 2026'), relevance (one sentence why it fits). "
                    'Return as JSON: {"suggestions": [{"name":"...","location":"...","timing":"...","relevance":"..."}]}'
                ),
            }],
            timeout=40,
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(ln for ln in raw.splitlines() if not ln.startswith("```"))
        suggestions = json.loads(raw).get("suggestions", [])
    except Exception as exc:
        logger.error("Conference suggestion error: %s", exc)
        return render(request, 'engagement/partials/suggested_conferences.html',
                      {'suggestions': [], 'terms': terms, 'error': True})

    return render(request, 'engagement/partials/suggested_conferences.html',
                  {'suggestions': suggestions, 'terms': terms})


@login_required
@require_POST
def create_conference(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    start_date = data.get("start_date", "")
    if not name or not start_date:
        return render(request, "engagement/partials/form_error.html",
                      {"error": "Name and start date are required."})
    conf = Conference.objects.create(
        tenant=request.tenant,
        name=name,
        location=data.get("location", ""),
        start_date=start_date,
        end_date=data.get("end_date") or None,
        status=data.get("status", Conference.Status.UPCOMING),
        notes=data.get("notes", ""),
        created_by=request.user,
    )
    log_action(request, conf, AuditLog.Action.CREATE, after={"name": conf.name})
    conferences = Conference.objects.prefetch_related("kols", "papers")
    return render(request, "engagement/partials/conference_list_inner.html",
                  {"conferences": conferences, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def update_conference(request, conf_pk):
    conf = get_object_or_404(Conference, pk=conf_pk, tenant=request.tenant)
    data = json.loads(request.body)
    conf.name = data.get("name", conf.name)
    conf.location = data.get("location", conf.location)
    conf.status = data.get("status", conf.status)
    conf.notes = data.get("notes", conf.notes)
    conf.save()
    log_action(request, conf, AuditLog.Action.UPDATE, after={"status": conf.status})
    return render(request, "engagement/partials/conference_card.html",
                  {"conf": conf, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def create_round_table(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    date = data.get("date", "")
    if not name or not date:
        return render(request, "engagement/partials/form_error.html",
                      {"error": "Name and date are required."})
    rt = RoundTable.objects.create(
        tenant=request.tenant,
        name=name,
        date=date,
        location=data.get("location", ""),
        discussion_themes=data.get("discussion_themes", []),
        notes=data.get("notes", ""),
        created_by=request.user,
    )
    log_action(request, rt, AuditLog.Action.CREATE, after={"name": rt.name})
    round_tables = RoundTable.objects.prefetch_related("kols")
    return render(request, "engagement/partials/round_table_list_inner.html",
                  {"round_tables": round_tables, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def create_advisory_board(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    date = data.get("date", "")
    if not name or not date:
        return render(request, "engagement/partials/form_error.html",
                      {"error": "Name and date are required."})
    ab = AdvisoryBoard.objects.create(
        tenant=request.tenant,
        name=name,
        date=date,
        location=data.get("location", ""),
        agenda_items=data.get("agenda_items", []),
        notes=data.get("notes", ""),
        created_by=request.user,
    )
    log_action(request, ab, AuditLog.Action.CREATE, after={"name": ab.name})
    advisory_boards = AdvisoryBoard.objects.prefetch_related("kols")
    return render(request, "engagement/partials/advisory_board_list_inner.html",
                  {"advisory_boards": advisory_boards, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def create_other_event(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    date = data.get("date", "")
    if not name or not date:
        return render(request, "engagement/partials/form_error.html",
                      {"error": "Name and date are required."})
    oe = OtherEvent.objects.create(
        tenant=request.tenant,
        name=name,
        date=date,
        location=data.get("location", ""),
        event_type=data.get("event_type", ""),
        notes=data.get("notes", ""),
        created_by=request.user,
    )
    log_action(request, oe, AuditLog.Action.CREATE, after={"name": oe.name})
    other_events = OtherEvent.objects.prefetch_related("kols")
    return render(request, "engagement/partials/other_event_list_inner.html",
                  {"other_events": other_events, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def add_kol_to_event(request, event_type, event_pk):
    model = _MODEL_MAP.get(event_type)
    if not model:
        raise Http404
    event = get_object_or_404(model, pk=event_pk, tenant=request.tenant)
    data = json.loads(request.body)
    kol = get_object_or_404(KOL, pk=data.get("kol_pk"), tenant=request.tenant)
    event.kols.add(kol)
    ctx_key = _CARD_CTX_KEY[event_type]
    return render(request, _CARD_TEMPLATE_MAP[event_type],
                  {ctx_key: event, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def remove_kol_from_event(request, event_type, event_pk, kol_pk):
    model = _MODEL_MAP.get(event_type)
    if not model:
        raise Http404
    event = get_object_or_404(model, pk=event_pk, tenant=request.tenant)
    kol = get_object_or_404(KOL, pk=kol_pk, tenant=request.tenant)
    event.kols.remove(kol)
    ctx_key = _CARD_CTX_KEY[event_type]
    return render(request, _CARD_TEMPLATE_MAP[event_type],
                  {ctx_key: event, "kol_choices": _kol_choices(request)})
