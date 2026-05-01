import json
import logging
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.literature.models import Paper

from .models import Enquiry

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    'what', 'is', 'the', 'a', 'an', 'of', 'for', 'in', 'to', 'and', 'or',
    'with', 'how', 'does', 'do', 'can', 'are', 'this', 'that', 'it', 'be',
    'at', 'by', 'from', 'has', 'have', 'was', 'were', 'when', 'why', 'which',
    'i', 'my', 'your', 'its', 'if', 'on', 'about', 'would', 'should', 'use',
    'used', 'using', 'patient', 'patients', 'drug', 'medication', 'treatment',
    'dose', 'dosing', 'not', 'there', 'any', 'more', 'than', 'dose',
}


def _analyse_enquiry_trends(enquiries_qs):
    now = timezone.now()
    recent_cutoff = now - timedelta(days=30)
    prev_cutoff = now - timedelta(days=60)

    rows = list(enquiries_qs.values('keywords', 'question', 'created_at'))

    def extract_terms(row):
        if row['keywords']:
            return [k.lower().strip() for k in row['keywords'] if k.strip()]
        words = row['question'].lower().split()
        return [
            w.strip('?.,!();:\'"')
            for w in words
            if len(w) > 3 and w.strip('?.,!();:\'"').lower() not in _STOP_WORDS
        ]

    all_terms, recent_terms, prev_terms = [], [], []
    for row in rows:
        terms = extract_terms(row)
        all_terms.extend(terms)
        if row['created_at'] >= recent_cutoff:
            recent_terms.extend(terms)
        elif row['created_at'] >= prev_cutoff:
            prev_terms.extend(terms)

    top_topics = Counter(all_terms).most_common(8)

    recent_count = Counter(recent_terms)
    prev_count = Counter(prev_terms)
    trending = []
    for term, recent_n in recent_count.most_common(20):
        prev_n = prev_count.get(term, 0)
        if recent_n >= 2 and (prev_n == 0 or recent_n > prev_n * 1.15):
            pct_change = int(((recent_n - prev_n) / max(prev_n, 1)) * 100)
            trending.append({'term': term, 'count': recent_n, 'pct_change': pct_change, 'is_new': prev_n == 0})
    trending.sort(key=lambda x: (-x['count'], -x['pct_change']))

    return top_topics, trending[:6]


@login_required
def enquiry_list(request):
    enquiries = Enquiry.objects.select_related("created_by", "assigned_to")
    status_filter = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status_filter:
        enquiries = enquiries.filter(status=status_filter)
    if q:
        enquiries = enquiries.filter(question__icontains=q)
    counts = {
        "open": Enquiry.objects.filter(status=Enquiry.Status.OPEN).count(),
        "draft": Enquiry.objects.filter(status=Enquiry.Status.DRAFT).count(),
        "responded": Enquiry.objects.filter(status=Enquiry.Status.RESPONDED).count(),
    }
    all_enquiries = Enquiry.objects.all()
    top_topics, trending = _analyse_enquiry_trends(all_enquiries)
    max_topic_count = top_topics[0][1] if top_topics else 1
    return render(request, "medinfo/enquiry_list.html", {
        "enquiries": enquiries,
        "status_filter": status_filter,
        "status_choices": Enquiry.Status.choices,
        "source_choices": Enquiry.Source.choices,
        "counts": counts,
        "top_topics": top_topics,
        "trending": trending,
        "max_topic_count": max_topic_count,
        "q": q,
    })


@login_required
def enquiry_detail(request, enquiry_pk):
    enquiry = get_object_or_404(Enquiry, pk=enquiry_pk, tenant=request.tenant)
    papers = Paper.objects.all()
    return render(request, "medinfo/enquiry_detail.html", {
        "enquiry": enquiry,
        "papers": papers,
        "source_choices": Enquiry.Source.choices,
        "status_choices": Enquiry.Status.choices,
    })


@login_required
@require_POST
def create_enquiry(request):
    data = json.loads(request.body)
    question = data.get("question", "").strip()
    if not question:
        return render(request, "medinfo/partials/enquiry_form_error.html",
                      {"error": "Question is required."})
    enquiry = Enquiry.objects.create(
        tenant=request.tenant,
        question=question,
        source=data.get("source", Enquiry.Source.HCP),
        created_by=request.user,
    )
    log_action(request, enquiry, AuditLog.Action.CREATE, after={"question": enquiry.question[:80]})
    enquiries = Enquiry.objects.select_related("created_by", "assigned_to")
    return render(request, "medinfo/partials/enquiry_list_inner.html", {"enquiries": enquiries})


@login_required
@require_POST
def save_response(request, enquiry_pk):
    enquiry = get_object_or_404(Enquiry, pk=enquiry_pk, tenant=request.tenant)
    data = json.loads(request.body)
    enquiry.response = data.get("response", enquiry.response)
    enquiry.citations = data.get("citations", enquiry.citations)
    action = data.get("action", "draft")
    if action == "respond":
        enquiry.status = Enquiry.Status.RESPONDED
        enquiry.responded_by = request.user
        enquiry.responded_at = timezone.now()
    else:
        enquiry.status = Enquiry.Status.DRAFT
    enquiry.save()
    log_action(request, enquiry, AuditLog.Action.UPDATE, after={"status": enquiry.status})
    return render(request, "medinfo/partials/enquiry_card.html", {"enquiry": enquiry, "source_choices": Enquiry.Source.choices})


@login_required
@require_POST
def update_enquiry(request, enquiry_pk):
    enquiry = get_object_or_404(Enquiry, pk=enquiry_pk, tenant=request.tenant)
    data = json.loads(request.body)
    question = data.get("question", "").strip()
    if question:
        enquiry.question = question
    enquiry.source = data.get("source", enquiry.source)
    enquiry.save(update_fields=["question", "source", "updated_at"])
    log_action(request, enquiry, AuditLog.Action.UPDATE, after={"question": enquiry.question[:80], "source": enquiry.source})
    return render(request, "medinfo/partials/enquiry_card.html", {"enquiry": enquiry, "source_choices": Enquiry.Source.choices})


@login_required
@require_POST
def close_enquiry(request, enquiry_pk):
    enquiry = get_object_or_404(Enquiry, pk=enquiry_pk, tenant=request.tenant)
    enquiry.status = Enquiry.Status.CLOSED
    enquiry.save(update_fields=["status", "updated_at"])
    log_action(request, enquiry, AuditLog.Action.UPDATE, after={"status": enquiry.status})
    return render(request, "medinfo/partials/enquiry_card.html", {"enquiry": enquiry, "source_choices": Enquiry.Source.choices})
