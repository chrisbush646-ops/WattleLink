from django.urls import path
from . import views

app_name = "engagement"

urlpatterns = [
    path("", views.engagement_list, name="list"),
    path("conferences/suggest/", views.suggest_conferences, name="suggest_conferences"),
    path("conference/create/", views.create_conference, name="create_conference"),
    path("conference/<int:conf_pk>/update/", views.update_conference, name="update_conference"),
    path("roundtable/create/", views.create_round_table, name="create_round_table"),
    path("roundtable/<int:rt_pk>/update/", views.update_round_table, name="update_round_table"),
    path("advisory-board/create/", views.create_advisory_board, name="create_advisory_board"),
    path("advisory-board/<int:ab_pk>/update/", views.update_advisory_board, name="update_advisory_board"),
    path("other-event/create/", views.create_other_event, name="create_other_event"),
    path("other-event/<int:oe_pk>/update/", views.update_other_event, name="update_other_event"),
    path("event/<str:event_type>/<int:event_pk>/kol/add/", views.add_kol_to_event, name="add_kol_to_event"),
    path("event/<str:event_type>/<int:event_pk>/kol/<int:kol_pk>/remove/", views.remove_kol_from_event, name="remove_kol_from_event"),
]
