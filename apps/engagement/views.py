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

from django.utils import timezone

from .models import AdvisoryBoard, Conference, OtherEvent, RoundTable


def _split_by_date(qs, date_field="date"):
    today = timezone.localdate()
    upcoming = qs.filter(**{f"{date_field}__gte": today}).order_by(date_field)
    past = qs.filter(**{f"{date_field}__lt": today}).order_by(f"-{date_field}")
    return upcoming, past

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
    private = request.session.get("view_mode") == "personal"
    _user_filter = {"created_by": request.user} if private else {}
    q = request.GET.get("q", "").strip()
    conferences = Conference.objects.filter(**_user_filter).select_related("created_by").prefetch_related("kols", "papers")
    round_tables = RoundTable.objects.filter(**_user_filter).select_related("created_by").prefetch_related("kols")
    advisory_boards = AdvisoryBoard.objects.filter(**_user_filter).select_related("created_by").prefetch_related("kols")
    other_events = OtherEvent.objects.filter(**_user_filter).select_related("created_by").prefetch_related("kols")
    if q:
        conferences = conferences.filter(name__icontains=q)
        round_tables = round_tables.filter(name__icontains=q)
        advisory_boards = advisory_boards.filter(name__icontains=q)
        other_events = other_events.filter(name__icontains=q)

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

    upcoming_conferences, past_conferences = _split_by_date(conferences, "start_date")
    upcoming_round_tables, past_round_tables = _split_by_date(round_tables)
    upcoming_advisory_boards, past_advisory_boards = _split_by_date(advisory_boards)
    upcoming_other_events, past_other_events = _split_by_date(other_events)

    return render(request, "engagement/engagement_list.html", {
        "upcoming_conferences": upcoming_conferences,
        "past_conferences": past_conferences,
        "upcoming_round_tables": upcoming_round_tables,
        "past_round_tables": past_round_tables,
        "upcoming_advisory_boards": upcoming_advisory_boards,
        "past_advisory_boards": past_advisory_boards,
        "upcoming_other_events": upcoming_other_events,
        "past_other_events": past_other_events,
        "conf_status_choices": Conference.Status.choices,
        "conf_events_json": json.dumps(conf_events),
        "rt_events_json": json.dumps(rt_events),
        "ab_events_json": json.dumps(ab_events),
        "other_events_json": json.dumps(other_ev_events),
        "active_tab": active_tab,
        "tab_items": tab_items,
        "kol_choices": _kol_choices(request),
        "q": q,
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
            temperature=0,
            system=[{"type": "text", "text": (
                "You are a medical affairs assistant. Suggest relevant medical conferences "
                "for an Australian pharmaceutical MSL team. Return only valid JSON, no markdown."
            ), "cache_control": {"type": "ephemeral"}}],
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
    upcoming_conferences, past_conferences = _split_by_date(conferences, "start_date")
    return render(request, "engagement/partials/conference_list_inner.html", {
        "upcoming_conferences": upcoming_conferences,
        "past_conferences": past_conferences,
        "kol_choices": _kol_choices(request),
    })


@login_required
@require_POST
def update_conference(request, conf_pk):
    conf = get_object_or_404(Conference, pk=conf_pk, tenant=request.tenant)
    data = json.loads(request.body)
    conf.name = data.get("name", conf.name)
    conf.location = data.get("location", conf.location)
    conf.status = data.get("status", conf.status)
    conf.notes = data.get("notes", conf.notes)
    if data.get("start_date"):
        conf.start_date = data["start_date"]
    if "end_date" in data:
        conf.end_date = data["end_date"] or None
    conf.save()
    log_action(request, conf, AuditLog.Action.UPDATE, after={"name": conf.name, "status": conf.status})
    return render(request, "engagement/partials/conference_card.html",
                  {"conf": conf, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def update_round_table(request, rt_pk):
    rt = get_object_or_404(RoundTable, pk=rt_pk, tenant=request.tenant)
    data = json.loads(request.body)
    rt.name = data.get("name", rt.name)
    rt.location = data.get("location", rt.location)
    rt.notes = data.get("notes", rt.notes)
    if data.get("date"):
        rt.date = data["date"]
    themes_raw = data.get("themes_raw")
    if themes_raw is not None:
        rt.discussion_themes = [t.strip() for t in themes_raw.split(",") if t.strip()]
    rt.save()
    log_action(request, rt, AuditLog.Action.UPDATE, after={"name": rt.name})
    return render(request, "engagement/partials/round_table_card.html",
                  {"rt": rt, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def update_advisory_board(request, ab_pk):
    ab = get_object_or_404(AdvisoryBoard, pk=ab_pk, tenant=request.tenant)
    data = json.loads(request.body)
    ab.name = data.get("name", ab.name)
    ab.location = data.get("location", ab.location)
    ab.notes = data.get("notes", ab.notes)
    if data.get("date"):
        ab.date = data["date"]
    agenda_raw = data.get("agenda_raw")
    if agenda_raw is not None:
        ab.agenda_items = [t.strip() for t in agenda_raw.split(",") if t.strip()]
    ab.save()
    log_action(request, ab, AuditLog.Action.UPDATE, after={"name": ab.name})
    return render(request, "engagement/partials/advisory_board_card.html",
                  {"ab": ab, "kol_choices": _kol_choices(request)})


@login_required
@require_POST
def update_other_event(request, oe_pk):
    oe = get_object_or_404(OtherEvent, pk=oe_pk, tenant=request.tenant)
    data = json.loads(request.body)
    oe.name = data.get("name", oe.name)
    oe.location = data.get("location", oe.location)
    oe.event_type = data.get("event_type", oe.event_type)
    oe.notes = data.get("notes", oe.notes)
    if data.get("date"):
        oe.date = data["date"]
    oe.save()
    log_action(request, oe, AuditLog.Action.UPDATE, after={"name": oe.name})
    return render(request, "engagement/partials/other_event_card.html",
                  {"oe": oe, "kol_choices": _kol_choices(request)})


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
    upcoming_round_tables, past_round_tables = _split_by_date(round_tables)
    return render(request, "engagement/partials/round_table_list_inner.html", {
        "upcoming_round_tables": upcoming_round_tables,
        "past_round_tables": past_round_tables,
        "kol_choices": _kol_choices(request),
    })


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
    upcoming_advisory_boards, past_advisory_boards = _split_by_date(advisory_boards)
    return render(request, "engagement/partials/advisory_board_list_inner.html", {
        "upcoming_advisory_boards": upcoming_advisory_boards,
        "past_advisory_boards": past_advisory_boards,
        "kol_choices": _kol_choices(request),
    })


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
    upcoming_other_events, past_other_events = _split_by_date(other_events)
    return render(request, "engagement/partials/other_event_list_inner.html", {
        "upcoming_other_events": upcoming_other_events,
        "past_other_events": past_other_events,
        "kol_choices": _kol_choices(request),
    })


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
    log_action(request, event, AuditLog.Action.UPDATE,
               after={"added_kol_pk": kol.pk, "kol_name": kol.name})
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
    log_action(request, event, AuditLog.Action.UPDATE,
               before={"removed_kol_pk": kol.pk, "kol_name": kol.name})
    ctx_key = _CARD_CTX_KEY[event_type]
    return render(request, _CARD_TEMPLATE_MAP[event_type],
                  {ctx_key: event, "kol_choices": _kol_choices(request)})
