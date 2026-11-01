from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from contests.models import Contest, ContestParticipant, Problem, TestCase
from contests.services import contest_digest


@pytest.fixture
def student(db):
    return User.objects.create_user("student", password="student-test-password")


@pytest.fixture
def contest(student):
    now = timezone.now()
    return Contest.objects.create(
        title="Practice", slug="practice", starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1), created_by=student,
    )


@pytest.fixture
def problem(contest):
    problem = Problem.objects.create(
        contest=contest, code="A", title="Two Numbers",
        statement="Add two numbers. <script>alert(1)</script>",
        input_description="Two integers", output_description="Their sum",
        constraints_text="-1000 <= a, b <= 1000", reference_language="python3",
        reference_source="a, b = map(int, input().split())\nprint(a + b)\n",
    )
    for position, data in enumerate([
        ("3 5\n", "8\n"), ("17 -4\n", "13\n"), ("-800 19\n", "-781\n"),
    ]):
        TestCase.objects.create(
            problem=problem, input_text=data[0], expected_output=data[1],
            is_sample=position == 0, position=position,
        )
    return problem


@pytest.fixture
def published(contest, problem, student):
    # Fixture only: production verification is performed by the Linux judge.
    contest.verified_digest = contest_digest(contest)
    contest.status = "PUBLISHED"
    contest.save()
    ContestParticipant.objects.create(contest=contest, user=student)
    return contest
