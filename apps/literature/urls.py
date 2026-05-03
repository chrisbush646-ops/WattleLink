from django.urls import path
from . import views

app_name = "literature"

urlpatterns = [
    # Search & Ingest
    path("search/", views.search_ingest, name="search"),
    path("search/run/", views.run_search, name="run_search"),
    path("search/ingest/", views.ingest_paper, name="ingest_paper"),
    path("search/ingest-all-oa/", views.ingest_all_oa, name="ingest_all_oa"),
    path("search/flag-for-upload/", views.flag_for_upload, name="flag_for_upload"),
    path("search/upload/", views.upload_pdf, name="upload_pdf"),
    path("search/upload-from-search/", views.upload_from_search, name="upload_from_search"),
    path("search/save/", views.save_search, name="save_search"),
    path("search/saved/", views.saved_searches, name="saved_searches"),
    path("search/saved/<int:pk>/run/", views.run_saved_search, name="run_saved_search"),
    path("search/saved/<int:pk>/delete/", views.delete_saved_search, name="delete_saved_search"),
    path("search/ai-suggest/", views.ai_suggest, name="ai_suggest"),
    path("search/expand-synonyms/", views.expand_synonyms_view, name="expand_synonyms"),
    path("search/ai-suggest-refinements/", views.ai_suggest_refinements_view, name="ai_suggest_refinements"),
    path("search/refine/", views.refine_search, name="refine_search"),
    # Literature Database
    path("library/", views.library, name="library"),
    path("library/search.json", views.paper_search_json, name="paper_search_json"),
    path("library/<int:pk>/", views.paper_detail, name="paper_detail"),
    path("library/<int:pk>/pdf/", views.serve_pdf, name="serve_pdf"),
    path("library/<int:pk>/history/", views.paper_history, name="paper_history"),
    path("library/<int:pk>/remove/", views.remove_paper, name="remove"),
    path("library/awaiting-upload/", views.awaiting_upload, name="awaiting_upload"),
    path("library/<int:pk>/attach-pdf/", views.attach_pdf, name="attach_pdf"),
    # DOI verification
    path("library/<int:paper_pk>/doi/verify/", views.verify_doi_view, name="doi_verify"),
    path("library/<int:paper_pk>/doi/search/", views.search_doi_view, name="doi_search"),
    path("library/doi/verify-all/", views.verify_all_dois_view, name="doi_verify_all"),
    path("library/doi/find-missing/", views.find_missing_dois_view, name="doi_find_missing"),
]
