import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
    """
    Fetch full text for an open-access paper at ingest time.
    Tries PMC first; falls back to Unpaywall OA PDF if PMC yields nothing substantial.
    """
    from .services.pubmed import fetch_pmc_full_text, fetch_oa_pdf_via_unpaywall
    fetch_pmc_full_text(paper)
    paper.refresh_from_db(fields=["full_text"])
    if len(paper.full_text or "") < 4_000 and paper.doi:
        fetch_oa_pdf_via_unpaywall(paper)


def _apply_doi_verification(paper, raw_doi: str, doi_source: str) -> None:
    """
    Verify a DOI from an external source and persist the result on the paper.
    If raw_doi is empty, attempt to find one via CrossRef metadata search.
    Never blocks the caller — CrossRef failures are logged and marked unverified.
    """
    from django.utils import timezone as tz
    from .services.doi import DOIVerifier

    verifier = DOIVerifier()

    if raw_doi:
        try:
            doi = verifier.clean_doi(raw_doi)
        except ValueError:
            doi = raw_doi  # store as-is but unverified

        result = verifier.verify_doi(doi)
        paper.doi = doi
        paper.doi_verified = result["is_valid"]
        paper.doi_source = doi_source
        paper.doi_verification_details = result
        if result["is_valid"]:
            paper.doi_verified_at = tz.now()
    else:
        # No DOI from source — try CrossRef metadata search
        authors_str = (
            ", ".join(paper.authors) if isinstance(paper.authors, list) else (paper.authors or "")
        )
        year = str(paper.published_date.year) if paper.published_date else ""
        match = verifier.search_doi_by_metadata(paper.title, authors_str, paper.journal, year)
        if match.get("doi") and match.get("confidence") in ("HIGH", "MEDIUM"):
            paper.doi = match["doi"]
            paper.doi_verified = True
            paper.doi_source = Paper.DOISource.CROSSREF
            paper.doi_verified_at = tz.now()
            paper.doi_verification_details = match


# ── Search & Ingest ──────────────────────────────────────────────────────────

@login_required
def search_ingest(request):
    saved_searches = SavedSearch.objects.all()
    return render(request, "literature/search.html", {
        "saved_searches": saved_searches,
    })


def _build_filters_from_post(data) -> dict:
    """Extract structured filter params from POST data dict."""
    publication_types = data.getlist("publication_types") if hasattr(data, "getlist") else data.get("publication_types", [])
    return {
        "publication_types": publication_types,
        "language": "eng" if data.get("language_english") in ("true", "1", True) else "",
        "species": "humans" if data.get("species_humans") in ("true", "1", True) else "",
        "has_abstract": data.get("has_abstract") in ("true", "1", True),
        "full_text_only": data.get("full_text_only") in ("true", "1", True),
        "free_full_text_only": data.get("free_full_text_only") in ("true", "1", True),
        "age_group": data.get("age_group", ""),
        "sex": data.get("sex", ""),
        "date_preset": data.get("date_preset", ""),
        "date_from": data.get("date_from", "").strip(),
        "date_to": data.get("date_to", "").strip(),
    }


def _annotate_articles(articles, existing_pmids, new_pmids=None, query_rows=None):
    """Add already_ingested, is_new, and relevance_score to article dicts."""
    for a in articles:
        pmid = a.get("pubmed_id", "")
        a["already_ingested"] = pmid in existing_pmids
        a["is_new"] = pmid in new_pmids if new_pmids else False
        if query_rows:
            title_abs = (a.get("title", "") + " " + a.get("abstract", "")).lower()
            a["relevance_score"] = sum(
                1 for r in query_rows
                if r.get("operator", "AND") != "NOT"
                and (r.get("term") or "").lower() in title_abs
            )
        else:
            a["relevance_score"] = 0


@login_required
@require_POST
def run_search(request):
    """
    Stage 1 broad search. Accepts structured rows JSON or plain query string.
    Returns search results partial + Stage 2 context (mesh, journals, authors).
    """
    body_data = {}
    try:
        body_data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        pass

    rows = body_data.get("rows") or []
    synonym_expansions_raw = body_data.get("synonym_expansions") or {}
    synonym_expansions = {int(k): v for k, v in synonym_expansions_raw.items()}

    # Build query from rows if provided, else fall back to plain query string
    if rows:
        from .services.pubmed import build_pubmed_query
        query = build_pubmed_query(rows, synonym_expansions or None)
    else:
        query = (body_data.get("query") or request.POST.get("query", "")).strip()

    if not query:
        return render(request, "literature/partials/search_results.html", {
            "error": "Please enter a search query.",
        })

    # Filters — from JSON body or fallback POST
    if body_data.get("filters"):
        filters = body_data["filters"]
        publication_types = filters.get("publication_types", [])
    else:
        filters = _build_filters_from_post(request.POST)
        publication_types = filters.get("publication_types", [])

    # Legacy compat
    open_access_only = body_data.get("open_access_only") or request.POST.get("open_access_only") == "true"

    client = PubMedClient()
    total_count, pmids = client.esearch(
        query=query,
        open_access_only=open_access_only,
        publication_types=publication_types,
        language=filters.get("language", "eng"),
        species=filters.get("species", "humans"),
        has_abstract=filters.get("has_abstract", False),
        full_text_only=filters.get("full_text_only", False),
        free_full_text_only=filters.get("free_full_text_only", False),
        age_group=filters.get("age_group", ""),
        sex=filters.get("sex", ""),
        date_preset=filters.get("date_preset", ""),
        date_from=filters.get("date_from", ""),
        date_to=filters.get("date_to", ""),
    )
    articles = client.efetch(pmids)

    existing_pmids = set(
        Paper.objects.filter(pubmed_id__in=pmids).values_list("pubmed_id", flat=True)
    )
    _annotate_articles(articles, existing_pmids, query_rows=rows)

    # Stage 2 context — derive quick filter chips from sample
    from .services.pubmed import get_mesh_terms_from_results, get_top_journals_from_results
    mesh_chips = get_mesh_terms_from_results(pmids)
    journal_chips = get_top_journals_from_results(pmids)

    log_action(request, None, "search_executed", after={
        "query": query[:200], "total_count": total_count,
    })

    return render(request, "literature/partials/search_results.html", {
        "articles": articles,
        "query": query,
        "total": total_count,
        "displayed": len(articles),
        "mesh_chips": mesh_chips,
        "journal_chips": journal_chips,
    })


@login_required
@require_POST
def refine_search(request):
    """
    Stage 2: re-run a query with AND/NOT refinement terms applied.
    Returns updated count + results partial.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return render(request, "literature/partials/search_results.html", {"error": "Invalid request."})

    base_query = body.get("query", "").strip()
    refinement_terms = body.get("refinement_terms", [])
    exclusion_terms = body.get("exclusion_terms", [])
    filters = body.get("filters", {})

    if not base_query:
        return render(request, "literature/partials/search_results.html", {"error": "Query required."})

    # Build compound query
    compound = base_query
    for term in refinement_terms:
        if term.strip():
            compound = f"({compound}) AND {term.strip()}"
    for term in exclusion_terms:
        if term.strip():
            compound = f"({compound}) NOT {term.strip()}"

    client = PubMedClient()
    total_count, pmids = client.esearch(
        query=compound,
        publication_types=filters.get("publication_types", []),
        language=filters.get("language", "eng"),
        species=filters.get("species", "humans"),
        has_abstract=filters.get("has_abstract", False),
        date_preset=filters.get("date_preset", ""),
        date_from=filters.get("date_from", ""),
        date_to=filters.get("date_to", ""),
    )
    articles = client.efetch(pmids)

    existing_pmids = set(
        Paper.objects.filter(pubmed_id__in=pmids).values_list("pubmed_id", flat=True)
    )
    _annotate_articles(articles, existing_pmids)

    log_action(request, None, "refinements_applied", after={
        "base_query": base_query[:200],
        "refinement_terms": refinement_terms,
        "exclusion_terms": exclusion_terms,
        "total_count": total_count,
    })

    return render(request, "literature/partials/search_results.html", {
        "articles": articles,
        "query": compound,
        "total": total_count,
        "displayed": len(articles),
        "is_refined": True,
    })


@login_required
@require_POST
def expand_synonyms_view(request):
    """Expand a single search term with synonyms via AI."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    term = body.get("term", "").strip()
    field = body.get("field", "tiab")
    if not term:
        return JsonResponse({"error": "term required"}, status=400)

    from .services.ai_suggest import expand_synonyms
    expanded = expand_synonyms(term, field)
    return JsonResponse({"expanded": expanded})


@login_required
@require_POST
def ai_suggest_refinements_view(request):
    """Stage 2 AI: suggest refinement terms for a broad query."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    query = body.get("query", "").strip()
    result_count = body.get("result_count", 0)
    top_mesh = body.get("top_mesh", [])

    if not query:
        return JsonResponse({"error": "query required"}, status=400)

    from .services.ai_suggest import suggest_refinements
    suggestions = suggest_refinements(query, result_count, top_mesh)

    log_action(request, None, "ai_suggestion_accepted", after={
        "query": query[:200], "suggestion_count": len(suggestions),
    })

    return JsonResponse({"suggestions": suggestions})


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
        _apply_doi_verification(paper, article.get("doi", ""), Paper.DOISource.PUBMED)
        paper.save(update_fields=[
            "doi", "doi_verified", "doi_verified_at", "doi_source", "doi_verification_details",
        ])
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
            _apply_doi_verification(paper, article.get("doi", ""), Paper.DOISource.PUBMED)
            paper.save(update_fields=[
                "doi", "doi_verified", "doi_verified_at", "doi_source", "doi_verification_details",
            ])
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

    from .services.pdf import validate_upload
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

    doi_unverified_hint = None
    try:
        from .services.pdf import extract_text, extract_doi_from_pdf
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
                      "issue", "pages", "pmcid", "pubmed_id", "study_type"):
            if meta.get(field) is not None and meta.get(field) != "":
                setattr(paper, field, meta[field])
                update_fields.append(field)

        # DOI: extract from PDF metadata/text, verify against CrossRef
        raw_doi = extract_doi_from_pdf(paper.source_file.path)
        if raw_doi:
            _apply_doi_verification(paper, raw_doi, Paper.DOISource.PDF_METADATA)
            if not paper.doi_verified:
                doi_unverified_hint = raw_doi
        else:
            # No DOI found in PDF — try CrossRef metadata search after save
            _apply_doi_verification(paper, "", Paper.DOISource.UNSET)

        for field in ("doi", "doi_verified", "doi_verified_at", "doi_source",
                      "doi_verification_details"):
            if field not in update_fields:
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
        "doi_unverified_hint": doi_unverified_hint,
    })


# ── DOI verification views ────────────────────────────────────────────────────

@login_required
@require_POST
def verify_doi_view(request, paper_pk):
    """Verify (or update) the DOI on a paper against CrossRef. Returns doi_field partial."""
    from django.utils import timezone as tz
    from .services.doi import DOIVerifier

    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    verifier = DOIVerifier()

    raw_doi = request.POST.get("doi-input-" + str(paper_pk), "").strip() or paper.doi

    if raw_doi:
        try:
            doi = verifier.clean_doi(raw_doi)
        except ValueError:
            doi = raw_doi

        result = verifier.verify_doi_against_paper(doi, paper.title)
        paper.doi = doi
        paper.doi_verified = result["is_valid"]
        paper.doi_source = Paper.DOISource.USER_ENTRY
        paper.doi_verification_details = result
        if result["is_valid"]:
            paper.doi_verified_at = tz.now()
        paper.save(update_fields=[
            "doi", "doi_verified", "doi_verified_at", "doi_source",
            "doi_verification_details", "updated_at",
        ])

    return render(request, "literature/partials/doi_field.html", {"paper": paper})


@login_required
@require_POST
def search_doi_view(request, paper_pk):
    """Search CrossRef for a DOI using paper metadata. Returns doi_field partial."""
    from django.utils import timezone as tz
    from .services.doi import DOIVerifier

    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    verifier = DOIVerifier()

    authors_str = (
        ", ".join(paper.authors) if isinstance(paper.authors, list) else (paper.authors or "")
    )
    year = str(paper.published_date.year) if paper.published_date else ""
    match = verifier.search_doi_by_metadata(paper.title, authors_str, paper.journal, year)

    if match.get("doi") and match.get("confidence") in ("HIGH", "MEDIUM"):
        paper.doi = match["doi"]
        paper.doi_verified = True
        paper.doi_source = Paper.DOISource.CROSSREF
        paper.doi_verified_at = tz.now()
        paper.doi_verification_details = match
        paper.save(update_fields=[
            "doi", "doi_verified", "doi_verified_at", "doi_source",
            "doi_verification_details", "updated_at",
        ])

    return render(request, "literature/partials/doi_field.html", {"paper": paper})


@login_required
@require_POST
def verify_all_dois_view(request):
    """Trigger the verify_all_dois Celery task for the current tenant."""
    from .tasks import verify_all_dois
    verify_all_dois.delay(request.tenant.pk)
    return JsonResponse({"status": "queued", "message": "DOI verification queued."})


@login_required
@require_POST
def find_missing_dois_view(request):
    """Trigger the find_missing_dois Celery task for the current tenant."""
    from .tasks import find_missing_dois
    find_missing_dois.delay(request.tenant.pk)
    return JsonResponse({"status": "queued", "message": "Missing DOI search queued."})


@login_required
@require_POST
def save_search(request):
    data = json.loads(request.body)
    name = data.get("name", "").strip()
    query = data.get("query", "").strip()

    if not name or not query:
        return JsonResponse({"error": "name and query required"}, status=400)

    filters = data.get("filters", {})
    if not filters:
        filters = {
            "open_access_only": data.get("open_access_only", False),
            "study_type": data.get("study_type", ""),
        }

    refinement_terms = data.get("refinement_terms", [])
    exclusion_terms = data.get("exclusion_terms", [])
    count_history = data.get("result_count_history", [])
    ai_used = data.get("ai_suggestions_used", [])

    saved, created = SavedSearch.objects.update_or_create(
        tenant=request.tenant,
        name=name,
        defaults={
            "user": request.user,
            "query": query,
            "filters": filters,
            "refinement_terms": refinement_terms,
            "exclusion_terms": exclusion_terms,
            "result_count_history": count_history,
            "ai_suggestions_used": ai_used,
        },
    )

    log_action(request, saved, "search_saved", after={"name": name, "query": query[:200]})
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

    f = search.filters or {}
    open_access_only = f.get("open_access_only", False)

    client = PubMedClient()
    total_count, pmids = client.esearch(
        query=search.query,
        open_access_only=open_access_only,
        publication_types=f.get("publication_types", []),
        language=f.get("language", "eng"),
        species=f.get("species", "humans"),
        date_preset=f.get("date_preset", ""),
        date_from=f.get("date_from", ""),
        date_to=f.get("date_to", ""),
    )
    articles = client.efetch(pmids)

    current_pmids = [a["pubmed_id"] for a in articles if a.get("pubmed_id")]
    last_pmids = set(search.last_result_pmids or [])
    new_pmids = set(current_pmids) - last_pmids if last_pmids else set()

    existing_pmids = set(
        Paper.objects.filter(pubmed_id__in=current_pmids).values_list("pubmed_id", flat=True)
    )
    _annotate_articles(articles, existing_pmids, new_pmids=new_pmids)

    search.last_run = timezone.now()
    search.result_count = total_count
    search.last_result_pmids = current_pmids
    search.save(update_fields=["last_run", "result_count", "last_result_pmids"])

    return render(request, "literature/partials/search_results.html", {
        "articles": articles,
        "query": search.query,
        "total": total_count,
        "displayed": len(articles),
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
        result = suggest_pubmed_query(description)
        return JsonResponse(result)
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


# ── Awaiting Upload ────────────────────────────────────────────────────────────

@login_required
def awaiting_upload(request):
    papers = (
        Paper.objects
        .filter(
            # Failed extraction — file uploaded but text could not be read
            Q(status=Paper.Status.AWAITING_UPLOAD)
            |
            # Paywalled paper ingested from PubMed with no PDF and no PMC fetch path
            Q(source_file="", source=Paper.Source.MANUAL, pmcid="")
        )
        .exclude(status=Paper.Status.APPROVED)
        .order_by("-created_at")
    )
    return render(request, "literature/awaiting_upload.html", {"papers": papers})


@login_required
@require_POST
def attach_pdf(request, pk):
    paper = get_object_or_404(Paper, pk=pk, tenant=request.tenant)
    uploaded = request.FILES.get("pdf")

    if not uploaded:
        return render(request, "literature/partials/attach_pdf_result.html", {
            "paper": paper, "error": "No file selected."
        })

    from .services.pdf import validate_upload, extract_text
    try:
        validate_upload(uploaded)
    except ValueError as e:
        return render(request, "literature/partials/attach_pdf_result.html", {
            "paper": paper, "error": str(e)
        })

    paper.source_file = uploaded
    paper.status = Paper.Status.AWAITING_UPLOAD
    paper.save(update_fields=["source_file", "status"])
    log_action(request, paper, AuditLog.Action.UPDATE,
               after={"pdf_attached": uploaded.name, "size": uploaded.size})

    try:
        text = extract_text(paper.source_file.path)
        paper.full_text = text[:500_000]
        paper.status = Paper.Status.INGESTED

        from .services.metadata import extract_metadata_from_text
        meta = extract_metadata_from_text(text)

        update_fields = ["full_text", "status", "source_file"]
        for field in ("journal", "journal_short", "published_date", "volume",
                      "issue", "pages", "doi", "pmcid", "study_type"):
            if meta.get(field) and not getattr(paper, field, None):
                setattr(paper, field, meta[field])
                update_fields.append(field)

        paper.save(update_fields=list(dict.fromkeys(update_fields)))
        return render(request, "literature/partials/attach_pdf_result.html", {
            "paper": paper,
            "success": True,
            "char_count": len(text),
        })
    except Exception as exc:
        logger.error("PDF attach failed for paper %d: %s", paper.pk, exc)
        paper.status = Paper.Status.AWAITING_UPLOAD
        paper.save(update_fields=["status"])
        return render(request, "literature/partials/attach_pdf_result.html", {
            "paper": paper, "error": f"Text extraction failed: {exc}"
        })
