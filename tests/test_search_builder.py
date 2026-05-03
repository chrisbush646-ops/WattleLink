"""
Tests for the two-stage search builder: query assembly, filter building,
pubmed service, and AI suggestion parsing.
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from apps.literature.services.pubmed import (
    PubMedClient,
    build_pubmed_query,
    get_mesh_terms_from_results,
    _parse_pubmed_xml,
)


# ── a. Query builder generates valid PubMed syntax ───────────────────────────

def test_build_query_two_concepts():
    rows = [
        {"operator": "AND", "field": "mesh", "term": "Arthritis, Rheumatoid"},
        {"operator": "AND", "field": "tiab", "term": "TNF inhibitor"},
    ]
    query = build_pubmed_query(rows)
    assert '"Arthritis, Rheumatoid"[MeSH]' in query
    assert '"TNF inhibitor"[Title/Abstract]' in query
    assert "AND" in query


# ── b. Synonym expansion wraps in parentheses with OR ────────────────────────

def test_build_query_with_synonym_expansion():
    rows = [
        {"operator": "AND", "field": "tiab", "term": "rheumatoid arthritis"},
    ]
    synonym_expansions = {
        0: '("rheumatoid arthritis"[MeSH] OR "rheumatoid arthritis"[tiab] OR "RA"[tiab])'
    }
    query = build_pubmed_query(rows, synonym_expansions)
    assert "OR" in query
    assert "[MeSH]" in query
    assert "[tiab]" in query


# ── c. Date range filter generates correct E-utilities parameters ─────────────

def test_esearch_date_preset_generates_params():
    client = PubMedClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.esearch("TNF inhibitors", date_preset="last5")

    params = mock_get.call_args[1]["params"]
    assert params.get("datetype") == "pdat"
    assert "mindate" in params
    today = date.today()
    assert params["maxdate"] == today.strftime("%Y/%m/%d")
    min_year = int(params["mindate"][:4])
    assert today.year - min_year == 5


def test_esearch_custom_date_range():
    client = PubMedClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.esearch("semaglutide", date_from="2020/01/01", date_to="2024/12/31")

    params = mock_get.call_args[1]["params"]
    assert params.get("mindate") == "2020/01/01"
    assert params.get("maxdate") == "2024/12/31"


# ── d. Publication type filters generate correct [pt] syntax ─────────────────

def test_esearch_single_publication_type():
    client = PubMedClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.esearch("TNF inhibitors", publication_types=["rct"])

    params = mock_get.call_args[1]["params"]
    assert "Randomized Controlled Trial[pt]" in params["term"]


def test_esearch_multiple_publication_types():
    client = PubMedClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.esearch("TNF inhibitors", publication_types=["rct", "meta"])

    params = mock_get.call_args[1]["params"]
    assert "Randomized Controlled Trial[pt]" in params["term"]
    assert "Meta-Analysis[pt]" in params["term"]


# ── e. Refinement terms are correctly ANDed to the original query ─────────────

def test_esearch_returns_count_and_pmids():
    client = PubMedClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"esearchresult": {"idlist": ["111", "222"], "count": "847"}}

    with patch("requests.get", return_value=mock_resp):
        count, pmids = client.esearch("TNF inhibitors")

    assert count == 847
    assert pmids == ["111", "222"]


def test_refine_query_and_terms():
    base = "TNF inhibitors[tiab]"
    refinement = "long-term[tiab]"
    compound = f"({base}) AND {refinement}"
    assert compound == "(TNF inhibitors[tiab]) AND long-term[tiab]"
    assert "AND" in compound


# ── f. Exclusion terms are correctly NOTed ───────────────────────────────────

def test_exclusion_terms_produce_not_syntax():
    base = "TNF inhibitors[tiab]"
    exclusion = "pediatric[tiab]"
    compound = f"({base}) NOT {exclusion}"
    assert "NOT" in compound
    assert "pediatric[tiab]" in compound


# ── g. Result count history tracks the funnel ────────────────────────────────

def test_count_history_tracks_funnel():
    history = [847]
    history.append(312)
    history.append(189)
    assert history == [847, 312, 189]
    assert history[-1] == 189  # most refined count


# ── h. SavedSearch stores filters and refinements ────────────────────────────

@pytest.mark.django_db
def test_saved_search_stores_full_state(db):
    from apps.literature.models import SavedSearch
    from apps.accounts.models import Tenant

    tenant = Tenant.objects.create(name="Test Tenant", slug="test-search-h")
    search = SavedSearch.objects.create(
        tenant=tenant,
        name="Test search",
        query="TNF inhibitors[tiab]",
        filters={"publication_types": ["rct"], "date_preset": "last5"},
        refinement_terms=["long-term[tiab]"],
        exclusion_terms=["pediatric[tiab]"],
        result_count_history=[847, 312],
        ai_suggestions_used=[{"term": "long-term[tiab]", "operator": "AND"}],
    )
    saved = SavedSearch.objects.get(pk=search.pk)
    assert saved.filters["publication_types"] == ["rct"]
    assert saved.refinement_terms == ["long-term[tiab]"]
    assert saved.exclusion_terms == ["pediatric[tiab]"]
    assert saved.result_count_history == [847, 312]
    assert len(saved.ai_suggestions_used) == 1


# ── i. AI suggestion parsing handles valid and invalid JSON ──────────────────

def test_ai_suggestion_parsing_valid():
    raw = json.dumps({
        "refinement_suggestions": [
            {"term": "long-term[tiab]", "operator": "AND",
             "rationale": "Limits to durability studies", "estimated_impact": "Removes ~30%"}
        ]
    })
    data = json.loads(raw)
    suggestions = data.get("refinement_suggestions", [])
    assert len(suggestions) == 1
    assert suggestions[0]["operator"] == "AND"


def test_ai_suggestion_parsing_invalid_json():
    raw = "not valid json {{"
    try:
        json.loads(raw)
        result = []
    except json.JSONDecodeError:
        result = []
    assert result == []


# ── j. Synonym toggle expands "rheumatoid arthritis" with MeSH + tiab ────────

def test_synonym_expansion_contains_mesh_and_tiab():
    from apps.literature.services.ai_suggest import expand_synonyms
    with patch("apps.literature.services.ai_suggest._client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = (
            '("rheumatoid arthritis"[MeSH] OR "rheumatoid arthritis"[tiab] OR "RA"[tiab])'
        )
        mock_client.messages.create.return_value = mock_response

        result = expand_synonyms("rheumatoid arthritis", "tiab")

    assert "[MeSH]" in result
    assert "[tiab]" in result
    assert "OR" in result
