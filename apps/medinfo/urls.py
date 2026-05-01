from django.urls import path
from . import views

app_name = "medinfo"

urlpatterns = [
    path("", views.enquiry_list, name="list"),
    path("<int:enquiry_pk>/", views.enquiry_detail, name="detail"),
    path("create/", views.create_enquiry, name="create"),
    path("<int:enquiry_pk>/update/", views.update_enquiry, name="update"),
    path("<int:enquiry_pk>/respond/", views.save_response, name="respond"),
    path("<int:enquiry_pk>/close/", views.close_enquiry, name="close"),
]
