import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import SafetySignal, SignalMention

logger = logging.getLogger(__name__)


@login_required
def signal_list(request):
    signals = SafetySignal.objects.prefetch_related("mentions").order_by(
        "status", "-created_at"
    )
    severity_order = {"CRITICAL": 0, "SERIOUS": 1, "MODERATE": 2, "MILD": 3}
    signals = sorted(signals, key=lambda s: (
        0 if s.status == "ACTIVE" else (1 if s.status == "MONITORING" else 2),
        severity_order.get(s.severity, 9),
    ))
    active_count = sum(1 for s in signals if s.status == SafetySignal.Status.ACTIVE)
    monitoring_count = sum(1 for s in signals if s.status == SafetySignal.Status.MONITORING)
    return render(request, "safety/signal_list.html", {
        "signals": signals,
        "active_count": active_count,
        "monitoring_count": monitoring_count,
        "severity_choices": SafetySignal.Severity.choices,
        "status_choices": SafetySignal.Status.choices,
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
    mention.delete()
    mentions = signal.mentions.select_related("paper", "added_by")
    return render(request, "safety/partials/mentions_table.html", {
        "signal": signal,
        "mentions": mentions,
    })
