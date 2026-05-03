import json
from unittest.mock import MagicMock, patch

import pytest

from apps.literature.services.pubmed import (
    PubMedClient,
    _infer_study_type,
    _parse_pubmed_xml,
)


SAMPLE_ESEARCH_JSON = {
    "esearchresult": {
        "idlist": ["38123456", "38123457", "38123458"],
        "count": "3",
    }
}

SAMPLE_EFETCH_XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2019//EN"
  "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_190101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">38123456</PMID>
      <Article PubModel="Print">
        <Journal>
          <ISSN IssnType="Electronic">1533-4406</ISSN>
          <JournalIssue CitedMedium="Internet">
            <Volume>390</Volume>
            <Issue>9</Issue>
            <PubDate>
              <Year>2024</Year>
              <Month>Mar</Month>
              <Day>7</Day>
            </PubDate>
          </JournalIssue>
          <Title>New England Journal of Medicine</Title>
          <ISOAbbreviation>N Engl J Med</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Long-term safety of TNF inhibitors in RA.</ArticleTitle>
        <Pagination>
          <MedlinePgn>801-812</MedlinePgn>
        </Pagination>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Hughes</LastName>
            <ForeName>William</ForeName>
            <Initials>W</Initials>
          </Author>
          <Author ValidYN="Y">
            <LastName>Park</LastName>
            <ForeName>Helen</ForeName>
            <Initials>H</Initials>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
          <PublicationType UI="D016449">Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
        <ELocationID EIdType="doi" ValidYN="Y">10.1056/NEJMoa2401234</ELocationID>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38123456</ArticleId>
        <ArticleId IdType="pmc">PMC1234567</ArticleId>
        <ArticleId IdType="doi">10.1056/NEJMoa2401234</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


class TestPubMedClientEsearch:
    def test_returns_pmid_list(self):
        client = PubMedClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_ESEARCH_JSON

        with patch("requests.get", return_value=mock_resp) as mock_get:
            count, pmids = client.esearch("TNF inhibitors AND RA")

        assert pmids == ["38123456", "38123457", "38123458"]
        assert count == 3
        mock_get.assert_called_once()

    def test_open_access_filter_appended(self):
        client = PubMedClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": []}}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            client.esearch("TNF inhibitors", open_access_only=True)

        call_params = mock_get.call_args[1]["params"]
        assert "free full text[filter]" in call_params["term"]

    def test_study_type_filter_appended(self):
        client = PubMedClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": []}}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            client.esearch("TNF inhibitors", study_type="rct")

        call_params = mock_get.call_args[1]["params"]
        assert "Randomized Controlled Trial[pt]" in call_params["term"]

    def test_unknown_study_type_not_appended(self):
        client = PubMedClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            # Pass empty language/species to isolate study type behaviour
            client.esearch("TNF inhibitors", study_type="unknown", language="", species="")

        call_params = mock_get.call_args[1]["params"]
        assert call_params["term"] == "TNF inhibitors"

    def test_network_error_returns_empty(self):
        import requests as req_module

        client = PubMedClient()

        with patch("requests.get", side_effect=req_module.ConnectionError("timeout")):
            count, pmids = client.esearch("TNF inhibitors")

        assert count == 0
        assert pmids == []


class TestPubMedClientEfetch:
    def test_empty_list_returns_empty(self):
        client = PubMedClient()
        assert client.efetch([]) == []

    def test_parses_article_fields(self):
        client = PubMedClient()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_EFETCH_XML

        with patch("requests.get", return_value=mock_resp):
            articles = client.efetch(["38123456"])

        assert len(articles) == 1
        a = articles[0]
        assert a["title"] == "Long-term safety of TNF inhibitors in RA."
        assert "Hughes W" in a["authors"]
        assert "Park H" in a["authors"]
        assert a["journal"] == "New England Journal of Medicine"
        assert a["journal_short"] == "N Engl J Med"
        assert a["volume"] == "390"
        assert a["issue"] == "9"
        assert a["pages"] == "801-812"
        assert a["doi"] == "10.1056/NEJMoa2401234"
        assert a["pubmed_id"] == "38123456"
        assert a["pmcid"] == "PMC1234567"
        assert a["is_open_access"] is True

    def test_open_access_false_when_no_pmcid(self):
        xml = SAMPLE_EFETCH_XML.replace(
            '<ArticleId IdType="pmc">PMC1234567</ArticleId>', ""
        )
        articles = _parse_pubmed_xml(xml)
        assert articles[0]["is_open_access"] is False
        assert articles[0]["pmcid"] == ""

    def test_network_error_returns_empty(self):
        import requests as req_module

        client = PubMedClient()

        with patch("requests.get", side_effect=req_module.ConnectionError("err")):
            articles = client.efetch(["38123456"])

        assert articles == []

    def test_malformed_xml_returns_empty(self):
        articles = _parse_pubmed_xml("<not valid xml<><")
        assert articles == []


class TestInferStudyType:
    def _make_article_el(self, pub_types):
        import xml.etree.ElementTree as ET

        xml = "<Article><PublicationTypeList>"
        for pt in pub_types:
            xml += f"<PublicationType>{pt}</PublicationType>"
        xml += "</PublicationTypeList></Article>"
        return ET.fromstring(xml)

    def test_rct(self):
        el = self._make_article_el(["Randomized Controlled Trial", "Journal Article"])
        assert _infer_study_type(el) == "RCT"

    def test_meta_analysis(self):
        el = self._make_article_el(["Meta-Analysis", "Journal Article"])
        assert _infer_study_type(el) == "Meta-analysis"

    def test_systematic_review(self):
        el = self._make_article_el(["Systematic Review", "Journal Article"])
        assert _infer_study_type(el) == "Systematic review"

    def test_observational(self):
        el = self._make_article_el(["Observational Study", "Journal Article"])
        assert _infer_study_type(el) == "Observational"

    def test_unknown_defaults_to_other(self):
        el = self._make_article_el(["Journal Article"])
        assert _infer_study_type(el) == "Other"

    def test_rct_takes_priority_over_meta(self):
        el = self._make_article_el(["Randomized Controlled Trial", "Meta-Analysis"])
        assert _infer_study_type(el) == "RCT"

    def test_published_date_year_only(self):
        import xml.etree.ElementTree as ET

        xml = """<PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation>
              <PMID>999</PMID>
              <Article>
                <Journal>
                  <JournalIssue>
                    <PubDate><Year>2023</Year></PubDate>
                  </JournalIssue>
                  <Title>Some Journal</Title>
                  <ISOAbbreviation>SJ</ISOAbbreviation>
                </Journal>
                <ArticleTitle>Test</ArticleTitle>
                <AuthorList/>
                <PublicationTypeList/>
              </Article>
            </MedlineCitation>
            <PubmedData><ArticleIdList/></PubmedData>
          </PubmedArticle>
        </PubmedArticleSet>"""
        articles = _parse_pubmed_xml(xml)
        assert len(articles) == 1
        # Year-only date parses to Jan 1 of that year
        import datetime
        assert articles[0]["published_date"] == datetime.date(2023, 1, 1)
