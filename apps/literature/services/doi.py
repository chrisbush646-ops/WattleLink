import logging
import re
from difflib import SequenceMatcher
from urllib.parse import quote

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CROSSREF_BASE = "https://api.crossref.org"
_HEADERS = {
    "User-Agent": "WattleLink/1.0 (mailto:hello@wattlelink.com.au)",
}
_CACHE_TTL = 86_400  # 24 hours
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/.+$")


class DOIVerifier:

    def clean_doi(self, raw_doi: str) -> str:
        doi = raw_doi.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "DOI:", "doi:"):
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):]
                break
        doi = doi.strip()
        if not _DOI_PATTERN.match(doi):
            raise ValueError(f"Invalid DOI format: {raw_doi!r}")
        return doi

    def verify_doi(self, doi: str) -> dict:
        cache_key = f"doi_verify:{doi}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        result = {
            "is_valid": False,
            "resolved_url": "",
            "crossref_title": "",
            "crossref_authors": [],
            "crossref_journal": "",
            "crossref_published_date": "",
            "match_confidence": "NO_MATCH",
            "mismatch_fields": [],
        }

        try:
            url = f"{_CROSSREF_BASE}/works/{quote(doi, safe='/')}"
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code == 404:
                result["is_valid"] = False
                cache.set(cache_key, result, _CACHE_TTL)
                return result
            if resp.status_code != 200:
                logger.warning("CrossRef returned %s for DOI %s", resp.status_code, doi)
                return result  # unverified, don't cache failures

            data = resp.json().get("message", {})
            titles = data.get("title", [])
            crossref_title = titles[0] if titles else ""

            container = data.get("container-title", [])
            journal = container[0] if container else ""

            authors = []
            for a in data.get("author", []):
                family = a.get("family", "")
                given = a.get("given", "")
                if family:
                    authors.append(f"{family} {given[0]}" if given else family)

            pub_date = ""
            date_parts = data.get("published", {}).get("date-parts", [[]])
            if date_parts and date_parts[0]:
                parts = date_parts[0]
                pub_date = str(parts[0])
                if len(parts) > 1:
                    pub_date += f"-{parts[1]:02d}"
                if len(parts) > 2:
                    pub_date += f"-{parts[2]:02d}"

            result.update({
                "is_valid": True,
                "resolved_url": f"https://doi.org/{doi}",
                "crossref_title": crossref_title,
                "crossref_authors": authors,
                "crossref_journal": journal,
                "crossref_published_date": pub_date,
                "match_confidence": "HIGH",
                "mismatch_fields": [],
            })

        except requests.RequestException as exc:
            logger.warning("CrossRef network error for DOI %s: %s", doi, exc)
            return result  # unverified, don't cache network failures
        except Exception as exc:
            logger.error("DOI verification error for %s: %s", doi, exc)
            return result

        cache.set(cache_key, result, _CACHE_TTL)
        return result

    def verify_doi_against_paper(self, doi: str, paper_title: str) -> dict:
        result = self.verify_doi(doi)
        if not result["is_valid"]:
            return result

        crossref_title = result["crossref_title"]
        if crossref_title and paper_title:
            ratio = SequenceMatcher(
                None,
                crossref_title.lower(),
                paper_title.lower(),
            ).ratio()
            if ratio < 0.85:
                result["match_confidence"] = "LOW"
                result["mismatch_fields"].append("title")

        return result

    def search_doi_by_metadata(
        self,
        title: str,
        authors: str,
        journal: str = "",
        year: str = "",
    ) -> dict:
        cache_key = f"doi_search:{title[:80]}:{authors[:40]}:{year}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        empty = {"doi": None, "confidence": "LOW", "crossref_title": "", "score": 0.0}

        try:
            params = {
                "query.title": title,
                "rows": 3,
                "select": "DOI,title,score",
            }
            if authors:
                first_author = authors.split(",")[0].split(" ")[0].strip()
                if first_author:
                    params["query.author"] = first_author
            if year:
                params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"

            resp = requests.get(
                f"{_CROSSREF_BASE}/works",
                params=params,
                headers=_HEADERS,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("CrossRef search returned %s", resp.status_code)
                return empty

            items = resp.json().get("message", {}).get("items", [])
            if not items:
                cache.set(cache_key, empty, _CACHE_TTL)
                return empty

            best = items[0]
            score = best.get("score", 0.0)
            crossref_titles = best.get("title", [])
            crossref_title = crossref_titles[0] if crossref_titles else ""

            if score < 80:
                result = {"doi": None, "confidence": "LOW", "crossref_title": crossref_title, "score": score}
                cache.set(cache_key, result, _CACHE_TTL)
                return result

            similarity = SequenceMatcher(
                None,
                crossref_title.lower(),
                title.lower(),
            ).ratio()

            if similarity < 0.85:
                result = {"doi": None, "confidence": "LOW", "crossref_title": crossref_title, "score": score}
                cache.set(cache_key, result, _CACHE_TTL)
                return result

            confidence = "HIGH" if score >= 100 else "MEDIUM"
            result = {
                "doi": best.get("DOI", ""),
                "confidence": confidence,
                "crossref_title": crossref_title,
                "score": score,
            }
            cache.set(cache_key, result, _CACHE_TTL)
            return result

        except requests.RequestException as exc:
            logger.warning("CrossRef metadata search failed: %s", exc)
            return empty
        except Exception as exc:
            logger.error("DOI metadata search error: %s", exc)
            return empty

    def resolve_doi(self, doi: str) -> str:
        try:
            resp = requests.get(
                f"https://doi.org/{doi}",
                headers=_HEADERS,
                timeout=10,
                allow_redirects=True,
            )
            return resp.url
        except requests.RequestException as exc:
            logger.warning("DOI resolve failed for %s: %s", doi, exc)
            return f"https://doi.org/{doi}"
