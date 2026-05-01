from django.urls import path
from . import views

app_name = "kol"

urlpatterns = [
    path("", views.kol_list, name="list"),
    path("directory/", views.kol_directory, name="directory"),
    path("<int:kol_pk>/", views.kol_detail, name="detail"),
    path("create/", views.create_kol, name="create"),
    path("<int:kol_pk>/update/", views.update_kol, name="update"),
    path("<int:kol_pk>/delete/", views.delete_kol, name="delete"),
    path("<int:kol_pk>/link-paper/", views.link_paper, name="link_paper"),
    path("<int:kol_pk>/suggest-papers/", views.suggest_papers_for_kol, name="suggest_papers"),
    path("<int:kol_pk>/talking-points/generate/", views.generate_talking_points, name="generate_talking_points"),
    path("<int:kol_pk>/talking-points/save/", views.save_talking_point, name="save_talking_point"),
    path("talking-points/<int:tp_pk>/delete/", views.delete_talking_point, name="delete_talking_point"),
    path("link/<int:link_pk>/remove/", views.unlink_paper, name="unlink_paper"),
    path("discover/<int:paper_pk>/", views.discover_from_paper, name="discover"),
    # Candidate workflow
    path("suggest/", views.suggest_kols, name="suggest"),
    path("candidates/", views.candidate_list, name="candidates"),
    path("candidates/<int:candidate_pk>/accept/", views.accept_candidate, name="accept_candidate"),
    path("candidates/<int:candidate_pk>/reject/", views.reject_candidate, name="reject_candidate"),
    path("candidates/<int:candidate_pk>/hold/", views.hold_candidate, name="hold_candidate"),
    path("candidates/<int:candidate_pk>/verify-status/", views.candidate_verify_status, name="candidate_verify_status"),
]
