from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Contest
from .services import participant_contest


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
    })
