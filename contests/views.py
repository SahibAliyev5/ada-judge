from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import SubmissionForm
from .models import Contest, Submission
from .services import create_submission, leaderboard, participant_contest


@login_required
def contest_list(request):
    contests = Contest.objects.filter(
        status="PUBLISHED", contestparticipant__user=request.user,
    )
    return render(request, "contests/list.html", {"contests": contests})


@login_required
def contest_detail(request, slug):
    contest = participant_contest(request.user, slug)
    return render(request, "contests/detail.html", {
        "contest": contest, "started": timezone.now() >= contest.starts_at,
    })


@login_required
def problem_detail(request, slug, code):
    contest = participant_contest(request.user, slug, require_started=True)
    problem = get_object_or_404(contest.problems, code=code)
    return render(request, "contests/problem.html", {
        "contest": contest, "problem": problem,
        "samples": problem.tests.filter(is_sample=True),
        "python_time_limit_ms": int(
            problem.time_limit_ms * settings.JUDGE_PYTHON_TIME_MULTIPLIER,
        ),
    })


@login_required
def submit_solution(request, slug):
    contest = participant_contest(request.user, slug, require_started=True)
    form = SubmissionForm(request.POST or None, contest=contest)
    if request.method == "POST" and form.is_valid():
        try:
            submission = create_submission(
                request.user, contest, form.cleaned_data["problem"],
                form.cleaned_data["language"], form.cleaned_data["source_code"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect("submission_detail", slug=slug, pk=submission.pk)
    return render(request, "contests/submit.html", {"contest": contest, "form": form})


@login_required
def submission_history(request, slug):
    contest = participant_contest(request.user, slug)
    submissions = Submission.objects.filter(
        contest=contest, user=request.user,
    ).select_related("problem").defer("source_code", "diagnostics").order_by("-id")
    page = Paginator(submissions, 50).get_page(request.GET.get("page"))
    return render(request, "contests/history.html", {"contest": contest, "page": page})


@login_required
def submission_detail(request, slug, pk):
    contest = participant_contest(request.user, slug)
    submission = get_object_or_404(
        Submission.objects.defer("diagnostics"),
        pk=pk, contest=contest, user=request.user,
    )
    return render(request, "contests/submission.html", {
        "contest": contest, "submission": submission,
    })


@login_required
def contest_leaderboard(request, slug):
    contest = participant_contest(request.user, slug, require_started=True)
    problems, rows = leaderboard(contest)
    template = "contests/leaderboard.html"
    if request.GET.get("partial") == "1":
        template = "contests/standings_table.html"
    response = render(request, template, {
        "contest": contest, "problems": problems, "rows": rows,
    })
    response["Cache-Control"] = "private, no-store"
    return response
