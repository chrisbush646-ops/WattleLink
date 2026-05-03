import logging
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, timedelta
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EFETCH_BATCH = 200

STUDY_TYPE_FILTERS = {
    "rct":          "Randomized Controlled Trial[pt]",
    "meta":         "Meta-Analysis[pt]",
    "sr":           "Systematic Review[pt]",
    "obs":          "Observational Study[pt]",
    "case_report":  "Case Reports[pt]",
    "clinical_trial": "Clinical Trial[pt]",
    "review":       "Review[pt]",
    "guideline":    "Practice Guideline[pt]",
}

AGE_GROUP_FILTERS = {
    "child":    "Child[mh]",
    "adolescent": "Adolescent[mh]",
    "adult":    "Adult[mh]",
    "aged":     "Aged[mh]",
    "aged80":   "Aged, 80 and over[mh]",
}

SEX_FILTERS = {
    "male":   "Male[mh]",
    "female": "Female[mh]",
}

DATE_PRESETS = {
    "last1":  1,
    "last2":  2,
    "last5":  5,
    "last10": 10,
}


def _date_range_from_preset(preset: str) -> tuple[str, str]:
    """Return (mindate, maxdate) strings for a preset key."""
    years = DATE_PRESETS.get(preset, 5)
    today = date.today()
    min_date = date(today.year - years, today.month, today.day)
    return min_date.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")


def build_pubmed_query(rows: list[dict], synonym_expansions: dict = None) -> str:
    """
    Assemble a PubMed query string from structured row dicts.
    rows: [{operator, field, term, synonyms_enabled, ...}]
    synonym_expansions: {row_index: expanded_string} — substituted when present
    """
    FIELD_TAGS = {
        "tiab": "[Title/Abstract]",
        "ti":   "[Title]",
        "mesh": "[MeSH]",
        "au":   "[Author]",
        "ta":   "[Journal]",
        "affl": "[Affiliation]",
        "all":  "",
    }
    parts = []
    for i, row in enumerate(rows):
        term = (row.get("term") or "").strip()
        if not term:
            continue
        field = row.get("field", "tiab")
        operator = row.get("operator", "AND") if i > 0 else None

        if synonym_expansions and i in synonym_expansions:
            expr = synonym_expansions[i]
        else:
            tag = FIELD_TAGS.get(field, "")
            # Only quote multi-word terms that are plain phrases, not boolean expressions
            is_compound = any(op in term.upper() for op in (" OR ", " AND ", " NOT "))
            quoted = term if is_compound else (f'"{term}"' if " " in term else term)
            expr = f"{quoted}{tag}" if not is_compound else f"({term})"

        if operator:
            parts.append(f"{operator} ({expr})" if len(expr) > 40 else f"{operator} {expr}")
        else:
            parts.append(f"({expr})" if len(expr) > 40 else expr)

    return " ".join(parts)


class PubMedClient:
    def __init__(self):
        self.api_key: Optional[str] = getattr(settings, "PUBMED_API_KEY", "") or None
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
        # Legacy compat
        open_access_only: bool = False,
        study_type: str = "",
        year_from: str = "",
        year_to: str = "",
        # New structured filters
        publication_types: list = None,
        language: str = "eng",
        species: str = "humans",
        has_abstract: bool = False,
        full_text_only: bool = False,
        free_full_text_only: bool = False,
        age_group: str = "",
        sex: str = "",
        date_preset: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> tuple[int, list[str]]:
        """
        Search PubMed. Returns (total_count, pmids_list).
        Accepts both legacy params (study_type str, year_from/year_to) and
        the new structured filter set.
        """
        full_query = query

        # Open access
        if open_access_only:
            full_query = f"({full_query}) AND free full text[filter]"
        if free_full_text_only and not open_access_only:
            full_query = f"({full_query}) AND free full text[filter]"
        elif full_text_only:
            full_query = f"({full_query}) AND full text[filter]"

        # Study / publication types — new list takes priority over legacy string
        pub_types = publication_types or ([study_type] if study_type else [])
        for pt in pub_types:
            if pt in STUDY_TYPE_FILTERS:
                full_query = f"({full_query}) AND {STUDY_TYPE_FILTERS[pt]}"

        # Language
        if language and language.lower() not in ("", "all"):
            full_query = f"({full_query}) AND {language}[la]"

        # Species
        if species and species.lower() not in ("", "all"):
            full_query = f"({full_query}) AND {species}[mh]"

        # Has abstract
        if has_abstract:
            full_query = f"({full_query}) AND hasabstract"

        # Age group
        if age_group and age_group in AGE_GROUP_FILTERS:
            full_query = f"({full_query}) AND {AGE_GROUP_FILTERS[age_group]}"

        # Sex
        if sex and sex in SEX_FILTERS:
            full_query = f"({full_query}) AND {SEX_FILTERS[sex]}"

        params = {
            **self._base_params(),
            "db": "pubmed",
            "term": full_query,
            "retmax": max_results,
            "retmode": "json",
            "usehistory": "n",
        }

        # Date range: structured params take priority over legacy year strings
        min_date = max_date = ""
        if date_preset and date_preset in DATE_PRESETS:
            min_date, max_date = _date_range_from_preset(date_preset)
        elif date_from or date_to:
            min_date = date_from
            max_date = date_to
        elif year_from or year_to:
            min_date = f"{year_from}/01/01" if year_from else ""
            max_date = f"{year_to}/12/31" if year_to else ""

        if min_date or max_date:
            params["datetype"] = "pdat"
            if min_date:
                params["mindate"] = min_date
            if max_date:
                params["maxdate"] = max_date

        self._throttle()
        try:
            resp = requests.get(ESEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("PubMed esearch error: %s", e)
            return 0, []

        data = resp.json()
        result = data.get("esearchresult", {})
        pmids = result.get("idlist", [])
        total_count = int(result.get("count", len(pmids)))
        logger.info("PubMed esearch: %d total results for query: %s", total_count, query[:80])
        return total_count, pmids

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

    # MeSH terms
    mesh_terms = []
    mesh_list = medline.find("MeshHeadingList")
    if mesh_list is not None:
        for heading in mesh_list.findall("MeshHeading"):
            descriptor = heading.find("DescriptorName")
            if descriptor is not None and descriptor.text:
                mesh_terms.append(descriptor.text.strip())

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
        "is_open_access": bool(pmcid),
        "abstract": abstract,
        "mesh_terms": mesh_terms,
    }


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


def get_mesh_terms_from_results(pmids: list[str], sample: int = 100) -> list[dict]:
    """Return top 10 MeSH terms from a sample of results, sorted by frequency."""
    if not pmids:
        return []
    client = PubMedClient()
    articles = client.efetch(pmids[:sample])
    counter = Counter()
    for a in articles:
        for term in a.get("mesh_terms", []):
            counter[term] += 1
    return [{"term": t, "count": c} for t, c in counter.most_common(10)]


def get_top_journals_from_results(pmids: list[str], sample: int = 100) -> list[dict]:
    """Return top 8 journals from a sample of results, sorted by frequency."""
    if not pmids:
        return []
    client = PubMedClient()
    articles = client.efetch(pmids[:sample])
    counter = Counter()
    for a in articles:
        j = a.get("journal_short") or a.get("journal", "")
        if j:
            counter[j] += 1
    return [{"term": j, "count": c} for j, c in counter.most_common(8)]


def get_top_authors_from_results(pmids: list[str], sample: int = 100) -> list[dict]:
    """Return top 8 first authors from a sample of results, sorted by frequency."""
    if not pmids:
        return []
    client = PubMedClient()
    articles = client.efetch(pmids[:sample])
    counter = Counter()
    for a in articles:
        authors = a.get("authors", [])
        if authors:
            counter[authors[0]] += 1
    return [{"term": a, "count": c} for a, c in counter.most_common(8)]


PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_ABSTRACT_THRESHOLD = 4_000


def fetch_pmc_full_text(paper) -> bool:
    """
    Fetch full text from PubMed Central and save it on the paper.
    Returns True if new text was stored, False otherwise.
    """
    if not paper.pmcid:
        return False
    if paper.full_text and len(paper.full_text) >= _ABSTRACT_THRESHOLD:
        return False
    try:
        resp = requests.get(
            PMC_EFETCH_URL,
            params={"db": "pmc", "id": paper.pmcid, "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        texts = [el.text or "" for el in root.iter() if el.text]
        full_text = " ".join(texts)[:500_000]
        if full_text.strip() and len(full_text) > len(paper.full_text or ""):
            paper.full_text = full_text
            paper.save(update_fields=["full_text"])
            logger.info("Fetched PMC full text for paper %s (%d chars)", paper.pk, len(full_text))
            return True
    except Exception as e:
        logger.warning("PMC full text fetch failed for paper %s: %s", paper.pk, e)
    return False
