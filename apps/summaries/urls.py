from django.urls import path
from . import views

app_name = "summaries"

urlpatterns = [
    path("", views.summaries_list, name="list"),
    path("<int:paper_pk>/", views.summary_panel, name="panel"),
    path("<int:paper_pk>/ai-summarise/", views.run_ai_summary, name="run_ai"),
    path("<int:paper_pk>/confirm/", views.confirm_summary, name="confirm"),
    path("generate-results/", views.generate_results_section, name="generate_results"),
]
