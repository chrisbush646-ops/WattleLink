from django.urls import path
from . import views

app_name = "literature"

urlpatterns = [
    # Search & Ingest
    path("search/", views.search_ingest, name="search"),
    path("search/run/", views.run_search, name="run_search"),
    path("search/ingest/", views.ingest_paper, name="ingest_paper"),
    path("search/ingest-all-oa/", views.ingest_all_oa, name="ingest_all_oa"),
    path("search/upload/", views.upload_pdf, name="upload_pdf"),
    path("search/save/", views.save_search, name="save_search"),
    path("search/saved/", views.saved_searches, name="saved_searches"),
    path("search/saved/<int:pk>/run/", views.run_saved_search, name="run_saved_search"),
    path("search/ai-suggest/", views.ai_suggest, name="ai_suggest"),
    # Literature Database
    path("library/", views.library, name="library"),
    path("library/search.json", views.paper_search_json, name="paper_search_json"),
    path("library/<int:pk>/", views.paper_detail, name="paper_detail"),
    path("library/<int:pk>/history/", views.paper_history, name="paper_history"),
    path("library/<int:pk>/remove/", views.remove_paper, name="remove"),
]
