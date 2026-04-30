import logging
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EFETCH_BATCH = 200

STUDY_TYPE_FILTERS = {
    "rct": "Randomized Controlled Trial[pt]",
    "meta": "Meta-Analysis[pt]",
    "sr": "Systematic Review[pt]",
    "obs": "Observational Study[pt]",
}


class PubMedClient:
    def __init__(self):
        self.api_key: Optional[str] = getattr(settings, "PUBMED_API_KEY", "") or None
        # NCBI allows 3 req/s without key, 10/s with key
        self._min_interval = 0.11 if self.api_key else 0.34
        self._last_request: float = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _base_params(self) -> dict:
        p = {}
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def esearch(
        self,
        query: str,
        max_results: int = 200,
        open_access_only: bool = False,
        study_type: str = "",
        year_from: str = "",
        year_to: str = "",
    ) -> list[str]:
        """Return a list of PubMed IDs matching the query."""
        full_query = query
        if open_access_only:
            full_query = f"({full_query}) AND free full text[filter]"
        if study_type and study_type in STUDY_TYPE_FILTERS:
            full_query = f"({full_query}) AND {STUDY_TYPE_FILTERS[study_type]}"

        params = {
            **self._base_params(),
            "db": "pubmed",
            "term": full_query,
            "retmax": max_results,
            "retmode": "json",
            "usehistory": "n",
        }

        if year_from or year_to:
            params["datetype"] = "pdat"
            if year_from:
                params["mindate"] = f"{year_from}/01/01"
            if year_to:
                params["maxdate"] = f"{year_to}/12/31"

        self._throttle()
        try:
            resp = requests.get(ESEARCH_URL, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("PubMed esearch error: %s", e)
            return []

        data = resp.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        logger.info("PubMed esearch: %d results for query: %s", len(pmids), query[:80])
        return pmids

    def efetch(self, pmids: list[str]) -> list[dict]:
        """Fetch article metadata for a list of PMIDs. Returns list of dicts."""
        if not pmids:
            return []

        articles = []
        for i in range(0, len(pmids), EFETCH_BATCH):
            batch = pmids[i : i + EFETCH_BATCH]
            articles.extend(self._fetch_batch(batch))
        return articles

    def _fetch_batch(self, pmids: list[str]) -> list[dict]:
        params = {
            **self._base_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }

        self._throttle()
        try:
            resp = requests.get(EFETCH_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("PubMed efetch error: %s", e)
            return []

        return _parse_pubmed_xml(resp.text)


def _text(el, path: str, default: str = "") -> str:
    node = el.find(path)
    return (node.text or "").strip() if node is not None else default


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error("PubMed XML parse error: %s", e)
        return []

    articles = []
    for article_el in root.findall(".//PubmedArticle"):
        try:
            articles.append(_parse_article(article_el))
        except Exception as e:
            logger.warning("Failed to parse PubMed article: %s", e)
    return articles


def _parse_article(el) -> dict:
    medline = el.find("MedlineCitation")
    article = medline.find("Article")
    journal = article.find("Journal")
    journal_issue = journal.find("JournalIssue") if journal is not None else None

    # Authors
    authors = []
    author_list = article.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            last = _text(author, "LastName")
            initials = _text(author, "Initials")
            collective = _text(author, "CollectiveName")
            if last:
                authors.append(f"{last} {initials}".strip())
            elif collective:
                authors.append(collective)
    if not authors:
        authors = ["Unknown"]

    # Published date
    pub_date_el = (
        journal_issue.find("PubDate") if journal_issue is not None else None
    )
    published_date = None
    if pub_date_el is not None:
        year = _text(pub_date_el, "Year")
        month = _text(pub_date_el, "Month") or "Jan"
        day = _text(pub_date_el, "Day") or "1"
        try:
            from datetime import datetime
            published_date = datetime.strptime(f"{year} {month} {day}", "%Y %b %d").date()
        except ValueError:
            try:
                published_date = date(int(year), 1, 1) if year else None
            except (ValueError, TypeError):
                published_date = None

    # Journal fields
    journal_title = _text(journal, "Title") if journal is not None else ""
    journal_short = _text(journal, "ISOAbbreviation") if journal is not None else ""
    volume = _text(journal_issue, "Volume") if journal_issue is not None else ""
    issue = _text(journal_issue, "Issue") if journal_issue is not None else ""

    # Pages
    pagination = article.find("Pagination")
    pages = _text(pagination, "MedlinePgn") if pagination is not None else ""

    # DOI
    doi = ""
    for loc_id in article.findall(".//ELocationID"):
        if loc_id.get("EIdType") == "doi":
            doi = (loc_id.text or "").strip()
            break

    # PMID and PMCID
    pmid = _text(medline, "PMID")
    pmcid = ""
    for art_id in el.findall(".//ArticleId"):
        if art_id.get("IdType") == "pmc":
            pmcid = (art_id.text or "").strip()
            break

    # Abstract
    abstract_el = article.find("Abstract")
    abstract_parts = []
    if abstract_el is not None:
        for text_el in abstract_el.findall("AbstractText"):
            label = text_el.get("Label", "")
            text = (text_el.text or "").strip()
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = "\n\n".join(abstract_parts)

    # Study type from publication types
    study_type = _infer_study_type(article)

    return {
        "title": _text(article, "ArticleTitle"),
        "authors": authors,
        "journal": journal_title,
        "journal_short": journal_short,
        "published_date": published_date,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "pubmed_id": pmid,
        "pmcid": pmcid,
        "study_type": study_type,
        "is_open_access": bool(pmcid) and _is_pmc_oa(pmcid),
        "abstract": abstract,
    }


def _is_pmc_oa(pmcid: str) -> bool:
    """Return True only if the paper is in the PMC Open Access file set (has a downloadable PDF)."""
    if not pmcid:
        return False
    pmcid_norm = pmcid.upper() if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
    try:
        resp = requests.get(
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid_norm}",
            timeout=10,
            headers={"User-Agent": "WattleLink/1.0 (medical-affairs-platform)"},
        )
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            # Any <link> element means the paper is in the OA file set
            return any(True for _ in root.iter("link"))
    except Exception as exc:
        logger.warning("PMC OA check failed for %s: %s", pmcid_norm, exc)
    return False


def _infer_study_type(article_el) -> str:
    pub_types = [
        pt.text or ""
        for pt in article_el.findall(".//PublicationType")
    ]
    pub_types_lower = [pt.lower() for pt in pub_types]
    if any("randomized controlled" in pt or "randomised controlled" in pt for pt in pub_types_lower):
        return "RCT"
    if "meta-analysis" in pub_types_lower:
        return "Meta-analysis"
    if "systematic review" in pub_types_lower:
        return "Systematic review"
    if any("observational" in pt for pt in pub_types_lower):
        return "Observational"
    return "Other"
