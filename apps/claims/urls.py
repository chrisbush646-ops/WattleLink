from django.urls import path
from . import views

app_name = "claims"

urlpatterns = [
    path("", views.claims_list, name="list"),
    path("<int:paper_pk>/", views.claims_panel, name="panel"),
    path("<int:paper_pk>/create/", views.create_claim, name="create"),
    path("<int:paper_pk>/extract/", views.run_extraction, name="run_extraction"),
    path("<int:claim_pk>/approve/", views.approve_claim, name="approve"),
    path("<int:claim_pk>/reject/", views.reject_claim, name="reject"),
    path("<int:claim_pk>/edit/", views.edit_claim, name="edit"),
    path("<int:claim_pk>/fidelity/", views.update_fidelity, name="fidelity"),
    path("<int:claim_pk>/validate-mlr/", views.run_mlr_validation, name="validate_mlr"),
    path("<int:paper_pk>/suggest/", views.suggest_claims, name="suggest"),
]
