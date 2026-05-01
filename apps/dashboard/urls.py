from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home_page, name="home"),
    path("contact/", views.contact, name="contact"),
    path("dashboard/", views.dashboard, name="index"),
    path("commercial/", views.commercial, name="commercial"),
]
