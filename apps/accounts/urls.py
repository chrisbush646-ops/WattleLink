from django.urls import path
from . import views

app_name = "accounts_app"

urlpatterns = [
    path("set-view-mode/", views.set_view_mode, name="set_view_mode"),
    path("profile/", views.profile, name="profile"),
    path("platform-admin/", views.admin_dashboard, name="admin_dashboard"),
    path("platform-admin/<int:pk>/edit/", views.admin_edit_user, name="admin_edit_user"),
    path("platform-admin/<int:pk>/delete/", views.admin_delete_user, name="admin_delete_user"),
    path("team/", views.team_view, name="team"),
    path("consent/", views.consent_view, name="consent"),
]
