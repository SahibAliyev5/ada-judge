from django.urls import path

from . import views

urlpatterns = [
    path("contests/<slug:slug>/submit/", views.submit_solution, name="submit_solution"),
    path("contests/<slug:slug>/submissions/", views.submission_history,
         name="submission_history"),
    path("contests/<slug:slug>/submissions/<int:pk>/", views.submission_detail,
         name="submission_detail"),
    path("contests/<slug:slug>/leaderboard/", views.contest_leaderboard,
         name="leaderboard"),
    path("", views.contest_list, name="contest_list"),
    path("contests/<slug:slug>/", views.contest_detail, name="contest_detail"),
    path("contests/<slug:slug>/problems/<str:code>/", views.problem_detail,
         name="problem_detail"),
]
