from django.urls import path

from . import views

urlpatterns = [
    path("", views.contest_list, name="contest_list"),
    path("contests/<slug:slug>/", views.contest_detail, name="contest_detail"),
    path("contests/<slug:slug>/problems/<str:code>/", views.problem_detail,
         name="problem_detail"),
]
