import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import SafetySignal, SignalMention
from .services.extraction import extract_safety_signals

logger = logging.getLogger(__name__)


@login_required
def signal_list(request):
    q = request.GET.get("q", "").strip()
    qs = SafetySignal.objects.select_related("created_by").prefetch_related("mentions")
    if request.session.get("view_mode") == "personal":
        qs = qs.filter(created_by=request.user)
    if q:
        from django.db.models import Q as _Q
        qs = qs.filter(
            _Q(event_name__icontains=q) |
            _Q(description__icontains=q)
        )
    signals = _sorted_signals(qs)
    active_count = sum(1 for s in signals if s.status == SafetySignal.Status.ACTIVE)
    monitoring_count = sum(1 for s in signals if s.status == SafetySignal.Status.MONITORING)

    scanned_count = Paper.objects.filter(safety_scanned_at__isnull=False).count()
    unscanned_count = Paper.objects.filter(
        safety_scanned_at__isnull=True,
    ).exclude(full_text="").count()

    return render(request, "safety/signal_list.html", {
        "signals": signals,
        "active_count": active_count,
        "monitoring_count": monitoring_count,
        "scanned_count": scanned_count,
        "unscanned_count": unscanned_count,
        "severity_choices": SafetySignal.Severity.choices,
        "status_choices": SafetySignal.Status.choices,
        "q": q,
    })


@login_required
def signal_stats(request):
    """Lightweight partial returning just the stat counts — used by the auto-refresh mechanism."""
    signals = SafetySignal.objects.all()
    total = signals.count()
    active_count = signals.filter(status=SafetySignal.Status.ACTIVE).count()
    monitoring_count = signals.filter(status=SafetySignal.Status.MONITORING).count()
    scanned_count = Paper.objects.filter(safety_scanned_at__isnull=False).count()
    unscanned_count = Paper.objects.filter(safety_scanned_at__isnull=True).exclude(full_text="").count()
    return render(request, "safety/partials/signal_stats.html", {
        "total": total,
        "active_count": active_count,
        "monitoring_count": monitoring_count,
        "scanned_count": scanned_count,
        "unscanned_count": unscanned_count,
    })


@login_required
def signal_detail(request, signal_pk):
    signal = get_object_or_404(SafetySignal, pk=signal_pk, tenant=request.tenant)
    mentions = signal.mentions.select_related("paper", "added_by")
    papers_without_mention = Paper.objects.exclude(
        pk__in=mentions.values_list("paper_id", flat=True)
    )
    return render(request, "safety/signal_detail.html", {
        "signal": signal,
        "mentions": mentions,
        "papers_without_mention": papers_without_mention,
        "severity_choices": SafetySignal.Severity.choices,
        "status_choices": SafetySignal.Status.choices,
    })


@login_required
@require_POST
def create_signal(request):
    data = json.loads(request.body)
    event_name = data.get("event_name", "").strip()
    if not event_name:
        return render(request, "safety/partials/signal_form_error.html", {
            "error": "Event name is required."
        })

    signal = SafetySignal.objects.create(
        tenant=request.tenant,
        event_name=event_name,
        severity=data.get("severity", SafetySignal.Severity.MODERATE),
        status=SafetySignal.Status.ACTIVE,
        description=data.get("description", ""),
        prepared_response=data.get("prepared_response", ""),
        created_by=request.user,
    )
    log_action(request, signal, AuditLog.Action.CREATE, after={"event_name": signal.event_name})

    signals = list(SafetySignal.objects.prefetch_related("mentions"))
    return render(request, "safety/partials/signal_list_inner.html", {"signals": signals})


@login_required
@require_POST
def update_signal(request, signal_pk):
    signal = get_object_or_404(SafetySignal, pk=signal_pk, tenant=request.tenant)
    data = json.loads(request.body)

    before = {"status": signal.status, "severity": signal.severity}
    signal.severity = data.get("severity", signal.severity)
    signal.status = data.get("status", signal.status)
    signal.description = data.get("description", signal.description)
    signal.prepared_response = data.get("prepared_response", signal.prepared_response)
    signal.save()

    log_action(request, signal, AuditLog.Action.UPDATE,
               before=before,
               after={"status": signal.status, "severity": signal.severity})

    return render(request, "safety/partials/signal_card.html", {"signal": signal})


@login_required
@require_POST
def add_mention(request, signal_pk):
    signal = get_object_or_404(SafetySignal, pk=signal_pk, tenant=request.tenant)
    data = json.loads(request.body)

    paper_pk = data.get("paper_pk")
    if not paper_pk:
        return render(request, "safety/partials/mention_row_error.html",
                      {"error": "Paper is required."})

    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    mention, created = SignalMention.objects.get_or_create(
        signal=signal,
        paper=paper,
        defaults={
            "incidence_treatment": data.get("incidence_treatment", ""),
            "incidence_control": data.get("incidence_control", ""),
            "passage": data.get("passage", ""),
            "page_ref": data.get("page_ref", ""),
            "added_by": request.user,
        },
    )

    if not created:
        mention.incidence_treatment = data.get("incidence_treatment", mention.incidence_treatment)
        mention.incidence_control = data.get("incidence_control", mention.incidence_control)
        mention.passage = data.get("passage", mention.passage)
        mention.page_ref = data.get("page_ref", mention.page_ref)
        mention.save()

    log_action(request, signal, AuditLog.Action.UPDATE,
               after={"added_paper_pk": paper.pk, "paper_title": paper.title[:120]})

    mentions = signal.mentions.select_related("paper", "added_by")
    return render(request, "safety/partials/mentions_table.html", {
        "signal": signal,
        "mentions": mentions,
    })


@login_required
@require_POST
def remove_mention(request, mention_pk):
    mention = get_object_or_404(
        SignalMention, pk=mention_pk, signal__tenant=request.tenant
    )
    signal = mention.signal
    paper_pk = mention.paper_id
    log_action(request, signal, AuditLog.Action.UPDATE,
               before={"removed_paper_pk": paper_pk})
    mention.delete()
    mentions = signal.mentions.select_related("paper", "added_by")
    return render(request, "safety/partials/mentions_table.html", {
        "signal": signal,
        "mentions": mentions,
    })


_SEVERITY_ORDER = {"CRITICAL": 0, "SERIOUS": 1, "MODERATE": 2, "MILD": 3}


def _sorted_signals(qs):
    return sorted(qs, key=lambda s: (
        0 if s.status == "ACTIVE" else (1 if s.status == "MONITORING" else 2),
        _SEVERITY_ORDER.get(s.severity, 9),
    ))


_SCAN_BATCH = 20


@login_required
@require_POST
def scan_for_signals(request):
    papers = list(
        Paper.objects.filter(
            safety_scanned_at__isnull=True,
        ).exclude(full_text="")[:_SCAN_BATCH]
    )

    papers_scanned = 0
    new_signals = 0
    new_mentions = 0
    errors = []

    for paper in papers:
        try:
            aes = extract_safety_signals(paper)
            for ae in aes:
                event_name = (ae.get("event_name") or "").strip()
                if not event_name:
                    continue

                severity = ae.get("severity", SafetySignal.Severity.MODERATE)
                if severity not in SafetySignal.Severity.values:
                    severity = SafetySignal.Severity.MODERATE

                existing = SafetySignal.objects.filter(
                    event_name__iexact=event_name,
                ).first()

                if existing:
                    signal = existing
                else:
                    signal = SafetySignal.objects.create(
                        tenant=request.tenant,
                        event_name=event_name,
                        severity=severity,
                        description=ae.get("description", ""),
                        status=SafetySignal.Status.ACTIVE,
                        created_by=request.user,
                    )
                    log_action(
                        request, signal, AuditLog.Action.CREATE,
                        after={"event_name": signal.event_name, "source": "ai_scan"},
                    )
                    new_signals += 1

                _, created = SignalMention.objects.get_or_create(
                    signal=signal,
                    paper=paper,
                    defaults={
                        "incidence_treatment": ae.get("incidence_treatment", ""),
                        "incidence_control": ae.get("incidence_control", ""),
                        "passage": ae.get("passage", ""),
                        "page_ref": ae.get("page_ref", ""),
                        "added_by": request.user,
                    },
                )
                if created:
                    new_mentions += 1

            paper.safety_scanned_at = timezone.now()
            paper.save(update_fields=["safety_scanned_at"])
            papers_scanned += 1

        except Exception as exc:
            logger.error("Error scanning paper %s for safety signals: %s", paper.pk, exc)
            errors.append(f"Paper '{paper.title[:60]}': {exc}")

    signals = _sorted_signals(
        SafetySignal.objects.prefetch_related("mentions")
    )
    html = render_to_string(
        "safety/partials/signal_list_inner.html",
        {"signals": signals},
        request=request,
    )

    unscanned_remaining = Paper.objects.filter(
        safety_scanned_at__isnull=True,
    ).exclude(full_text="").count()

    return JsonResponse({
        "html": html,
        "papers_scanned": papers_scanned,
        "new_signals": new_signals,
        "new_mentions": new_mentions,
        "has_more": unscanned_remaining > 0,
        "unscanned_remaining": unscanned_remaining,
        "errors": errors,
    })
