from django.urls import path
from . import views

app_name = "export"

urlpatterns = [
    path("", views.export_list, name="list"),
    path("<int:paper_pk>/", views.export_panel, name="panel"),
    path("<int:paper_pk>/create/", views.create_export, name="create"),
    path("package/<int:package_pk>/download/", views.download_export, name="download"),
    path("package/<int:package_pk>/poll/", views.poll_export, name="poll"),
]
