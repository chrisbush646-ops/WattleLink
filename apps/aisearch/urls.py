from django.urls import path
from . import views

app_name = "aisearch"

urlpatterns = [
    path("", views.search_home, name="home"),
    path("new/", views.new_chat, name="new_chat"),
    path("ask/", views.ask, name="ask"),
    path("<int:session_pk>/", views.session_detail, name="session"),
    path("<int:session_pk>/ask/", views.ask, name="ask_in_session"),
    path("<int:session_pk>/delete/", views.delete_session, name="delete_session"),
]
