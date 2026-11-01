from datetime import timedelta

import pytest
from django.contrib.auth.models import User

from contests.models import ContestParticipant, Submission
from contests.services import leaderboard

pytestmark = pytest.mark.django_db


def submit(user, contest, problem, verdict, minute):
    return Submission.objects.create(
        user=user, contest=contest, problem=problem, language="cpp20",
        source_code="unexecuted test fixture", status="DONE", verdict=verdict,
        submitted_at=contest.starts_at + timedelta(minutes=minute),
    )


def test_icpc_penalty(student, published, problem):
    submit(student, published, problem, "CE", 1)
    submit(student, published, problem, "SYSTEM_ERROR", 2)
    submit(student, published, problem, "WA", 3)
    submit(student, published, problem, "TLE", 4)
    submit(student, published, problem, "AC", 10)
    submit(student, published, problem, "WA", 11)
    submit(student, published, problem, "AC", 12)
    _, rows = leaderboard(published)
    assert rows[0]["solved"] == 1
    assert rows[0]["penalty"] == 50
    assert rows[0]["cells"][0]["attempts"] == 2


def test_unsolved_has_no_penalty(student, published, problem):
    submit(student, published, problem, "WA", 3)
    _, rows = leaderboard(published)
    assert rows[0]["solved"] == 0
    assert rows[0]["penalty"] == 0


def test_ordering_and_final_accept_time(student, published, problem):
    other = User.objects.create_user("other")
    ContestParticipant.objects.create(contest=published, user=other)
    submit(student, published, problem, "AC", 30)
    submit(other, published, problem, "WA", 1)
    submit(other, published, problem, "AC", 10)
    _, rows = leaderboard(published)
    assert [row["username"] for row in rows] == ["other", "student"]
    assert rows[0]["penalty"] == rows[1]["penalty"] == 30


def test_out_of_order_judging_and_rejudge(student, published, problem):
    accepted = submit(student, published, problem, "AC", 10)
    earlier = submit(student, published, problem, "WA", 2)
    _, rows = leaderboard(published)
    assert rows[0]["penalty"] == 30
    earlier.verdict = "AC"
    earlier.save()
    _, rows = leaderboard(published)
    assert rows[0]["penalty"] == 2
    accepted.verdict = "WA"
    accepted.save()
    _, rows = leaderboard(published)
    assert rows[0]["penalty"] == 2


def test_deterministic_zero_score_order(student, published):
    for username in ["zoe", "amy"]:
        user = User.objects.create_user(username)
        ContestParticipant.objects.create(contest=published, user=user)
    _, rows = leaderboard(published)
    assert [row["username"] for row in rows] == ["amy", "student", "zoe"]
