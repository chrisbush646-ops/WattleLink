from django.urls import path
from . import views

app_name = "safety"

urlpatterns = [
    path("", views.signal_list, name="list"),
    path("<int:signal_pk>/", views.signal_detail, name="detail"),
    path("create/", views.create_signal, name="create"),
    path("scan/", views.scan_for_signals, name="scan"),
    path("<int:signal_pk>/update/", views.update_signal, name="update"),
    path("<int:signal_pk>/mention/", views.add_mention, name="add_mention"),
    path("mention/<int:mention_pk>/remove/", views.remove_mention, name="remove_mention"),
]
