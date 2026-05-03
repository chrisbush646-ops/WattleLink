import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_pubmed_search(self, saved_search_id: int):
    """Run a saved search against PubMed and ingest new results."""
    from .models import Paper, SavedSearch
    from .services.pubmed import PubMedClient
    from apps.accounts.managers import set_current_tenant

    try:
        search = SavedSearch.all_objects.select_related("tenant").get(pk=saved_search_id)
    except SavedSearch.DoesNotExist:
        logger.error("SavedSearch %d not found", saved_search_id)
        return

    set_current_tenant(search.tenant)
    client = PubMedClient()

    filters = search.filters or {}
    pmids = client.esearch(
        query=search.query,
        open_access_only=filters.get("open_access_only", False),
        study_type=filters.get("study_type", ""),
    )

    articles = client.efetch(pmids)
    created_count = 0

    for article in articles:
        if not article.get("pubmed_id"):
            continue
        _, created = Paper.all_objects.get_or_create(
            tenant=search.tenant,
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
                "source": (
                    Paper.Source.PUBMED_OA
                    if article.get("is_open_access")
                    else Paper.Source.MANUAL
                ),
                "status": Paper.Status.INGESTED,
            },
        )
        if created:
            created_count += 1
            if article.get("is_open_access"):
                fetch_pubmed_full_text.delay(article["pubmed_id"], search.tenant.id)

    search.last_run = timezone.now()
    search.result_count = len(articles)
    search.save(update_fields=["last_run", "result_count"])
    set_current_tenant(None)

    logger.info(
        "sync_pubmed_search: search=%d, results=%d, created=%d",
        saved_search_id,
        len(articles),
        created_count,
    )
    return {"results": len(articles), "created": created_count}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_pubmed_full_text(self, pubmed_id: str, tenant_id: int):
    """Attempt to fetch full text for an open-access paper via PMC."""
    from .models import Paper

    try:
        paper = Paper.all_objects.get(pubmed_id=pubmed_id, tenant_id=tenant_id)
    except Paper.DoesNotExist:
        return

    if paper.full_text and len(paper.full_text) >= 4_000:
        return

    # PMC full text fetch — text-mode XML is most reliable
    import requests
    PMC_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    if not paper.pmcid:
        return

    try:
        resp = requests.get(
            PMC_URL,
            params={"db": "pmc", "id": paper.pmcid, "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        texts = [el.text or "" for el in root.iter() if el.text]
        paper.full_text = " ".join(texts)[:500_000]
        paper.save(update_fields=["full_text"])
    except Exception as e:
        logger.warning("fetch_pubmed_full_text error for %s: %s", pubmed_id, e)
        raise self.retry(exc=e)


@shared_task
def verify_all_dois(tenant_id: int):
    """Verify all unverified DOIs for a tenant against CrossRef."""
    import time
    from .models import Paper
    from .services.doi import DOIVerifier
    from django.utils import timezone

    papers = Paper.all_objects.filter(
        tenant_id=tenant_id,
        doi_verified=False,
    ).exclude(doi="")

    verifier = DOIVerifier()
    verified = 0
    failed = 0

    for paper in papers:
        try:
            doi = verifier.clean_doi(paper.doi)
        except ValueError:
            failed += 1
            continue

        result = verifier.verify_doi_against_paper(doi, paper.title)
        paper.doi = doi
        paper.doi_verified = result["is_valid"]
        paper.doi_verification_details = result
        if result["is_valid"]:
            paper.doi_verified_at = timezone.now()
            verified += 1
        else:
            failed += 1
        paper.save(update_fields=[
            "doi", "doi_verified", "doi_verified_at", "doi_verification_details",
        ])
        time.sleep(1)  # polite rate limiting

    logger.info(
        "verify_all_dois: tenant=%d, verified=%d, failed=%d",
        tenant_id, verified, failed,
    )
    return {"verified": verified, "failed": failed}


@shared_task
def find_missing_dois(tenant_id: int):
    """Search CrossRef for DOIs on papers that have none."""
    import time
    from .models import Paper
    from .services.doi import DOIVerifier
    from django.utils import timezone

    papers = Paper.all_objects.filter(tenant_id=tenant_id, doi="")
    verifier = DOIVerifier()
    found = 0

    for paper in papers:
        if not paper.title:
            continue
        authors_str = (
            ", ".join(paper.authors) if isinstance(paper.authors, list) else (paper.authors or "")
        )
        year = str(paper.published_date.year) if paper.published_date else ""
        match = verifier.search_doi_by_metadata(paper.title, authors_str, paper.journal, year)

        if match.get("doi") and match.get("confidence") in ("HIGH", "MEDIUM"):
            paper.doi = match["doi"]
            paper.doi_verified = True
            paper.doi_source = Paper.DOISource.CROSSREF
            paper.doi_verified_at = timezone.now()
            paper.doi_verification_details = match
            paper.save(update_fields=[
                "doi", "doi_verified", "doi_verified_at", "doi_source",
                "doi_verification_details",
            ])
            found += 1
            logger.info("Found DOI %s for paper %d via CrossRef", match["doi"], paper.pk)

        time.sleep(1)

    logger.info("find_missing_dois: tenant=%d, found=%d", tenant_id, found)
    return {"found": found}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_uploaded_pdf(self, paper_id: int):
    """Extract text from an uploaded PDF and update the Paper record."""
    from .models import Paper
    from .services.pdf import extract_text

    try:
        paper = Paper.all_objects.select_related("tenant").get(pk=paper_id)
    except Paper.DoesNotExist:
        logger.error("Paper %d not found for PDF processing", paper_id)
        return

    if not paper.source_file:
        logger.error("Paper %d has no source_file", paper_id)
        return

    try:
        text = extract_text(paper.source_file.path)
        paper.full_text = text[:500_000]
        paper.status = Paper.Status.INGESTED
        paper.save(update_fields=["full_text", "status"])

        from apps.audit.helpers import log_task_action
        from apps.audit.models import AuditLog
        log_task_action(paper.tenant, paper, AuditLog.Action.INGEST,
                        after={"source": "PDF upload", "chars_extracted": len(text)})

        logger.info("PDF processed for paper %d, %d chars extracted", paper_id, len(text))
    except Exception as e:
        logger.error("PDF extraction failed for paper %d: %s", paper_id, e)
        raise self.retry(exc=e)
