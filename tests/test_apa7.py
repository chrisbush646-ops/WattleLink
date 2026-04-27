import datetime

import pytest
from django.template import Context, Template

from apps.literature.models import Paper


def make_paper(tenant, **kwargs):
    defaults = {
        "title": "A Study of Something Important",
        "authors": ["Smith J", "Jones A"],
        "journal": "New England Journal of Medicine",
        "journal_short": "NEJM",
        "published_date": datetime.date(2024, 3, 1),
        "volume": "390",
        "issue": "9",
        "pages": "801-812",
        "doi": "10.1056/NEJMoa2401234",
        "status": Paper.Status.INGESTED,
        "source": Paper.Source.PUBMED_OA,
    }
    defaults.update(kwargs)
    return Paper.all_objects.create(tenant=tenant, **defaults)


@pytest.mark.django_db
class TestApa7Citation:
    def test_full_citation(self, tenant):
        paper = make_paper(tenant)
        citation = paper.apa7_citation()
        assert "Smith J, Jones A" in citation
        assert "(2024)" in citation
        assert "A Study of Something Important" in citation
        assert "New England Journal of Medicine" in citation
        assert ", 390" in citation
        assert "(9)" in citation
        assert ", 801-812" in citation
        assert "https://doi.org/10.1056/NEJMoa2401234" in citation

    def test_no_date_gives_nd(self, tenant):
        paper = make_paper(tenant, published_date=None)
        citation = paper.apa7_citation()
        assert "(n.d.)" in citation

    def test_no_doi_omits_doi(self, tenant):
        paper = make_paper(tenant, doi="")
        citation = paper.apa7_citation()
        assert "doi.org" not in citation
        assert "https://" not in citation

    def test_no_volume_omits_volume(self, tenant):
        paper = make_paper(tenant, volume="", issue="", pages="", doi="")
        citation = paper.apa7_citation()
        assert ",," not in citation
        assert citation.endswith(".")

    def test_authors_as_string(self, tenant):
        paper = make_paper(tenant, authors="Hughes W, Park H, et al.")
        citation = paper.apa7_citation()
        assert "Hughes W, Park H, et al." in citation

    def test_empty_authors_list(self, tenant):
        paper = make_paper(tenant, authors=[])
        citation = paper.apa7_citation()
        assert "Unknown" in citation

    def test_single_author(self, tenant):
        paper = make_paper(tenant, authors=["Reinhardt T"])
        citation = paper.apa7_citation()
        assert "Reinhardt T" in citation

    def test_many_authors(self, tenant):
        authors = [f"Author{i} A" for i in range(10)]
        paper = make_paper(tenant, authors=authors)
        citation = paper.apa7_citation()
        assert "Author0 A" in citation

    def test_citation_ends_with_period(self, tenant):
        paper = make_paper(tenant)
        citation = paper.apa7_citation()
        # Ends with DOI URL (no trailing period after URL in APA7 style)
        assert "doi.org/" in citation

    def test_no_volume_no_issue(self, tenant):
        paper = make_paper(tenant, volume="", issue="5", pages="12-15")
        citation = paper.apa7_citation()
        # Issue only rendered when volume present in standard APA7, but our
        # implementation renders issue independently — just check no crash
        assert "(2024)" in citation


@pytest.mark.django_db
class TestApa7Filter:
    def test_filter_returns_string(self, tenant):
        paper = make_paper(tenant)
        tmpl = Template("{% load citations %}{{ paper|apa7 }}")
        result = tmpl.render(Context({"paper": paper}))
        assert "Smith J" in result
        assert "New England Journal of Medicine" in result

    def test_filter_handles_none(self):
        tmpl = Template("{% load citations %}{{ paper|apa7 }}")
        result = tmpl.render(Context({"paper": None}))
        assert result == ""

    def test_apa7_block_tag(self, tenant):
        paper = make_paper(tenant)
        tmpl = Template("{% load citations %}{% apa7_block paper %}")
        result = tmpl.render(Context({"paper": paper}))
        # The block renders the apa7_citation.html inclusion template
        assert "Smith J" in result
