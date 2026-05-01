import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.exceptions import ValidationError
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog

from .models import Paper, SavedSearch
from .services.pubmed import PubMedClient

logger = logging.getLogger(__name__)


def _fetch_full_text_sync(paper):
    """Fetch full PMC text for an open-access paper synchronously."""
    if not paper.pmcid or paper.full_text:
        return
    import requests
    import xml.etree.ElementTree as ET
    PMC_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    try:
        resp = requests.get(
            PMC_URL,
            params={"db": "pmc", "id": paper.pmcid, "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        texts = [el.text or "" for el in root.iter() if el.text]
        full_text = " ".join(texts)[:500_000]
        if full_text.strip():
            paper.full_text = full_text
            paper.save(update_fields=["full_text"])
            logger.info("Fetched PMC full text for paper %s (%d chars)", paper.pk, len(full_text))
    except Exception as e:
        logger.warning("PMC full text fetch failed for paper %s: %s", paper.pk, e)


# ── Search & Ingest ──────────────────────────────────────────────────────────

@login_required
def search_ingest(request):
    saved_searches = SavedSearch.objects.all()
    return render(request, "literature/search.html", {
        "saved_searches": saved_searches,
    })


@login_required
@require_POST
def run_search(request):
    query = request.POST.get("query", "").strip()
    open_access_only = request.POST.get("open_access_only") == "true"
    study_type = request.POST.get("study_type", "")

    if not query:
        return render(request, "literature/partials/search_results.html", {
            "error": "Please enter a search query.",
        })

    year_from = request.POST.get("year_from", "").strip()
    year_to = request.POST.get("year_to", "").strip()

    client = PubMedClient()
    pmids = client.esearch(
        query=query,
        open_access_only=open_access_only,
        study_type=study_type,
        year_from=year_from,
        year_to=year_to,
    )
    articles = client.efetch(pmids)

    # Mark which PMIDs are already in the database for this tenant
    existing_pmids = set(
        Paper.objects.filter(pubmed_id__in=pmids).values_list("pubmed_id", flat=True)
    )
    for a in articles:
        a["already_ingested"] = a.get("pubmed_id") in existing_pmids

    return render(request, "literature/partials/search_results.html", {
        "articles": articles,
        "query": query,
        "total": len(articles),
    })


@login_required
@require_POST
def ingest_paper(request):
    data = json.loads(request.body)
    pubmed_id = data.get("pubmed_id", "")

    if not pubmed_id:
        return JsonResponse({"error": "pubmed_id required"}, status=400)

    client = PubMedClient()
    articles = client.efetch([pubmed_id])
    if not articles:
        return JsonResponse({"error": "Could not fetch article from PubMed"}, status=400)

    article = articles[0]
    paper, created = Paper.all_objects.get_or_create(
        tenant=request.tenant,
        pubmed_id=pubmed_id,
        defaults={
            "title": article.get("title", ""),
            "authors": article.get("authors", []),
            "journal": article.get("journal", ""),
            "journal_short": article.get("journal_short", ""),
            "published_date": article.get("published_date"),
            "volume": article.get("volume", ""),
            "issue": article.get("issue", ""),
            "pages": article.get("pages", ""),
            "doi": article.get("doi", ""),
            "pmcid": article.get("pmcid", ""),
            "study_type": article.get("study_type", ""),
            "full_text": article.get("abstract", ""),
            "source": (
                Paper.Source.PUBMED_OA if article.get("is_open_access")
                else Paper.Source.MANUAL
            ),
            "status": Paper.Status.INGESTED,
        },
    )

    if created:
        log_action(request, paper, AuditLog.Action.CREATE, after={"pubmed_id": pubmed_id})
        if article.get("is_open_access") and article.get("pmcid"):
            _fetch_full_text_sync(paper)

    return render(request, "literature/partials/ingested_row.html", {
        "paper": paper,
        "created": created,
    })


@login_required
@require_POST
def ingest_all_oa(request):
    data = json.loads(request.body)
    pmids = data.get("pmids", [])
    if not pmids:
        return JsonResponse({"ingested": 0})

    client = PubMedClient()
    articles = client.efetch(pmids)
    ingested = 0

    for article in articles:
        if not article.get("is_open_access") or not article.get("pubmed_id"):
            continue
        paper, created = Paper.all_objects.get_or_create(
            tenant=request.tenant,
            pubmed_id=article["pubmed_id"],
            defaults={
                "title": article.get("title", ""),
                "authors": article.get("authors", []),
                "journal": article.get("journal", ""),
                "journal_short": article.get("journal_short", ""),
                "published_date": article.get("published_date"),
                "volume": article.get("volume", ""),
                "issue": article.get("issue", ""),
                "pages": article.get("pages", ""),
                "doi": article.get("doi", ""),
                "pmcid": article.get("pmcid", ""),
                "study_type": article.get("study_type", ""),
                "full_text": article.get("abstract", ""),
                "source": Paper.Source.PUBMED_OA,
                "status": Paper.Status.INGESTED,
            },
        )
        if created:
            ingested += 1
            _fetch_full_text_sync(paper)

    return JsonResponse({"ingested": ingested})


@login_required
@require_POST
def upload_pdf(request):
    uploaded = request.FILES.get("pdf")
    if not uploaded:
        return render(request, "literature/partials/upload_status.html", {
            "error": "No file received."
        })

    from .services.pdf import validate_upload, extract_text
    try:
        validate_upload(uploaded)
    except ValueError as e:
        return render(request, "literature/partials/upload_status.html", {
            "error": str(e)
        })

    fallback_title = request.POST.get("title") or uploaded.name.replace(".pdf", "")
    paper = Paper.objects.create(
        tenant=request.tenant,
        title=fallback_title,
        authors=[],
        journal="",
        source=Paper.Source.PDF_UPLOAD,
        status=Paper.Status.AWAITING_UPLOAD,
        source_file=uploaded,
    )
    log_action(request, paper, AuditLog.Action.CREATE,
               after={"filename": uploaded.name, "size": uploaded.size})

    try:
        text = extract_text(paper.source_file.path)
        paper.full_text = text[:500_000]
        paper.status = Paper.Status.INGESTED

        # Extract bibliographic metadata from the PDF text and populate fields
        from .services.metadata import extract_metadata_from_text
        meta = extract_metadata_from_text(text)

        update_fields = ["full_text", "status"]
        if meta.get("title"):
            paper.title = meta["title"]
            update_fields.append("title")
        if meta.get("authors"):
            paper.authors = meta["authors"]
            update_fields.append("authors")
        for field in ("journal", "journal_short", "published_date", "volume",
                      "issue", "pages", "doi", "pmcid", "pubmed_id", "study_type"):
            if meta.get(field):
                setattr(paper, field, meta[field])
                update_fields.append(field)

        paper.save(update_fields=list(dict.fromkeys(update_fields)))  # dedupe
        message = f"PDF uploaded and metadata extracted ({len(text):,} characters)."
    except Exception as exc:
        logger.error("PDF processing failed for paper %d: %s", paper.id, exc)
        paper.save(update_fields=["full_text", "status"])
        message = f"PDF uploaded but processing failed: {exc}"

    return render(request, "literature/partials/upload_status.html", {
        "paper": paper,
        "message": message,
    })


@login_required
@require_POST
def save_search(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    query = data.get("query", "").strip()

    if not name or not query:
        return JsonResponse({"error": "name and query required"}, status=400)

    saved, created = SavedSearch.objects.update_or_create(
        tenant=request.tenant,
        name=name,
        defaults={
            "user": request.user,
            "query": query,
            "filters": {
                "open_access_only": data.get("open_access_only", False),
                "study_type": data.get("study_type", ""),
            },
        },
    )
    return JsonResponse({"id": saved.id, "created": created, "name": saved.name})


@login_required
def saved_searches(request):
    searches = SavedSearch.objects.all()
    return render(request, "literature/partials/saved_searches.html", {
        "searches": searches,
    })


@login_required
@require_POST
def run_saved_search(request, pk):
    search = get_object_or_404(SavedSearch, pk=pk, tenant=request.tenant)

    open_access_only = search.filters.get("open_access_only", False)
    study_type = search.filters.get("study_type", "")

    client = PubMedClient()
    pmids = client.esearch(
        query=search.query,
        open_access_only=open_access_only,
        study_type=study_type,
    )
    articles = client.efetch(pmids)

    current_pmids = [a["pubmed_id"] for a in articles if a.get("pubmed_id")]
    last_pmids = set(search.last_result_pmids or [])
    new_pmids = set(current_pmids) - last_pmids if last_pmids else set()

    existing_pmids = set(
        Paper.objects.filter(pubmed_id__in=current_pmids).values_list("pubmed_id", flat=True)
    )
    for a in articles:
        a["already_ingested"] = a.get("pubmed_id") in existing_pmids
        a["is_new"] = a.get("pubmed_id") in new_pmids

    search.last_run = timezone.now()
    search.result_count = len(articles)
    search.last_result_pmids = current_pmids
    search.save(update_fields=["last_run", "result_count", "last_result_pmids"])

    return render(request, "literature/partials/search_results.html", {
        "articles": articles,
        "query": search.query,
        "total": len(articles),
        "new_count": len(new_pmids),
        "search_name": search.name,
    })


@login_required
@require_POST
def ai_suggest(request):
    data = json.loads(request.body)
    description = data.get("description", "").strip()
    if not description:
        return JsonResponse({"error": "description required"}, status=400)

    try:
        from .services.ai_suggest import suggest_pubmed_query
        rows = suggest_pubmed_query(description)
        if not rows:
            return JsonResponse({"error": "No query could be generated"}, status=500)
        return JsonResponse({"rows": rows})
    except Exception as e:
        logger.error("AI suggest failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)


# ── Literature Database ───────────────────────────────────────────────────────

@login_required
def library(request):
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "").strip()

    qs = Paper.objects.select_related("tenant")

    if status_filter == "APPROVED":
        from apps.claims.models import CoreClaim
        approved_paper_ids = (
            CoreClaim.objects
            .filter(tenant=request.tenant, status=CoreClaim.Status.APPROVED)
            .values_list("paper_id", flat=True)
            .distinct()
        )
        qs = qs.filter(id__in=approved_paper_ids)
    elif status_filter:
        qs = qs.filter(status=status_filter)

    if search_query:
        vector = SearchVector("title", weight="A") + SearchVector("full_text", weight="B")
        query = SearchQuery(search_query)
        qs = qs.annotate(rank=SearchRank(vector, query)).filter(rank__gt=0.01).order_by("-rank")

    if request.htmx:
        return render(request, "literature/partials/paper_table.html", {
            "papers": qs,
            "status_filter": status_filter,
            "search_query": search_query,
        })

    filter_choices = [
        (Paper.Status.INGESTED, "Ingested"),
        (Paper.Status.ASSESSED, "Assessed"),
        (Paper.Status.SUMMARISED, "Summarised"),
        (Paper.Status.CLAIMS_GENERATED, "Claims Generated"),
        (Paper.Status.APPROVED, "Approved"),
    ]

    return render(request, "literature/library.html", {
        "papers": qs,
        "status_filter": status_filter,
        "search_query": search_query,
        "paper_count": qs.count(),
        "filter_choices": filter_choices,
    })


@login_required
@require_POST
def remove_paper(request, pk):
    paper = get_object_or_404(Paper, pk=pk, tenant=request.tenant)
    log_action(request, paper, AuditLog.Action.DELETE, before={"title": paper.title, "status": paper.status})
    paper.soft_delete()
    from django.http import HttpResponse
    response = HttpResponse("")
    response["HX-Refresh"] = "true"
    return response


@login_required
def paper_history(request, pk):
    """HTMX — return audit trail for a paper and all its related objects."""
    paper = get_object_or_404(Paper, pk=pk, tenant=request.tenant)
    from apps.audit.models import AuditLog

    claim_ids = []
    try:
        from apps.claims.models import CoreClaim
        claim_ids = list(CoreClaim.all_objects.filter(paper=paper).values_list("pk", flat=True))
    except Exception:
        pass

    assessment_ids = []
    try:
        from apps.assessment.models import GradeAssessment, RobAssessment
        grade_ids = list(GradeAssessment.all_objects.filter(paper=paper).values_list("pk", flat=True))
        rob_ids = list(RobAssessment.all_objects.filter(paper=paper).values_list("pk", flat=True))
        assessment_ids = grade_ids + rob_ids
    except Exception:
        pass

    export_ids = []
    try:
        from apps.export.models import ExportPackage
        export_ids = list(ExportPackage.objects.filter(paper=paper).values_list("pk", flat=True))
    except Exception:
        pass

    events = AuditLog.objects.filter(
        tenant=request.tenant,
    ).filter(
        models.Q(entity_type="Paper", entity_id=paper.pk) |
        models.Q(entity_type="CoreClaim", entity_id__in=claim_ids) |
        models.Q(entity_type="GradeAssessment", entity_id__in=assessment_ids) |
        models.Q(entity_type="RobAssessment", entity_id__in=assessment_ids) |
        models.Q(entity_type="ExportPackage", entity_id__in=export_ids)
    ).select_related("user").order_by("-created_at")[:60]

    return render(request, "literature/partials/paper_history.html", {
        "paper": paper,
        "events": events,
    })


@login_required
def paper_search_json(request):
    """Lightweight JSON search for paper picker (used in manual claim modal)."""
    q = request.GET.get("q", "").strip()
    qs = Paper.objects.filter(tenant=request.tenant)
    if q:
        qs = qs.filter(
            models.Q(title__icontains=q) |
            models.Q(journal__icontains=q) |
            models.Q(journal_short__icontains=q)
        )
    papers = [
        {
            "pk": p.pk,
            "title": p.title,
            "journal": p.journal_short or p.journal,
            "year": p.published_date.year if p.published_date else "",
        }
        for p in qs.order_by("-updated_at")[:20]
    ]
    return JsonResponse({"papers": papers})


@login_required
def paper_detail(request, pk):
    paper = get_object_or_404(Paper, pk=pk, tenant=request.tenant)

    claims = []
    try:
        from apps.claims.models import CoreClaim
        claims = CoreClaim.objects.filter(paper=paper).order_by("-status")
    except Exception:
        pass

    return render(request, "literature/partials/paper_detail.html", {
        "paper": paper,
        "claims": claims,
        "pipeline_stages": [
            ("Ingest", Paper.Status.INGESTED),
            ("Assess", Paper.Status.ASSESSED),
            ("Summarise", Paper.Status.SUMMARISED),
            ("Claims", Paper.Status.CLAIMS_GENERATED),
            ("Approved", Paper.Status.APPROVED),
        ],
    })
