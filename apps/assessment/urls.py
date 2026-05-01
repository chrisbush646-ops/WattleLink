from django.urls import path
from . import views

app_name = "assessment"

urlpatterns = [
    path("", views.assessment_list, name="list"),
    path("<int:paper_pk>/", views.assessment_panel, name="panel"),
    path("<int:paper_pk>/ai-assess/", views.run_ai_assessment, name="run_ai"),
    path("<int:paper_pk>/confirm/", views.confirm_assessment, name="confirm"),
]
