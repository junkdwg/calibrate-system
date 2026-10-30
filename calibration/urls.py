from django.urls import path

from . import views

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("", views.dashboard, name="dashboard"),
    path("records/", views.record_list, name="record_list"),
    path("records/new/", views.record_create, name="record_create"),
    path("records/<int:pk>/", views.record_detail, name="record_detail"),
    path("records/<int:pk>/edit/", views.record_edit, name="record_edit"),
    path("records/<int:pk>/action/<str:action>/", views.record_action, name="record_action"),
    path("records/<int:pk>/download/<str:fmt>/", views.record_download, name="record_download"),
]
