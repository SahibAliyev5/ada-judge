from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from contests.models import ContestParticipant, TestCase as ProblemTest

pytestmark = pytest.mark.django_db


def test_database_is_postgresql():
    from django.db import connection

    assert connection.vendor == "postgresql"


def test_contest_requires_valid_times(contest):
    contest.ends_at = contest.starts_at
    with pytest.raises(ValidationError):
        contest.save()


def test_publication_requires_verification(contest):
    contest.status = "PUBLISHED"
    with pytest.raises(ValidationError):
        contest.save()


def test_duplicate_enrollment(published, student):
    with pytest.raises(IntegrityError), transaction.atomic():
        ContestParticipant.objects.create(contest=published, user=student)


def test_problem_visibility_and_escaping(client, published, student, problem):
    client.force_login(student)
    url = reverse("problem_detail", args=[published.slug, problem.code])
    response = client.get(url)
    text = response.content.decode()
    assert response.status_code == 200
    assert "3 5" in text
    assert "17 -4" not in text
    assert "reference_source" not in text
    assert "map(int" not in text
    assert "&lt;script&gt;" in text
    assert "<script>alert" not in text


def test_early_access_blocked(client, contest, problem, student):
    contest.starts_at = timezone.now() + timedelta(minutes=10)
    contest.ends_at = contest.starts_at + timedelta(hours=1)
    from contests.services import contest_digest

    contest.verified_digest = contest_digest(contest)
    contest.status = "PUBLISHED"
    contest.save()
    ContestParticipant.objects.create(contest=contest, user=student)
    client.force_login(student)
    url = reverse("problem_detail", args=[contest.slug, problem.code])
    assert client.get(url).status_code == 403
    response = client.get(reverse("contest_detail", args=[contest.slug]))
    assert problem.title not in response.content.decode()


def test_unenrolled_user_cannot_access(client, published, problem):
    outsider = User.objects.create_user("outsider")
    client.force_login(outsider)
    response = client.get(reverse("contest_detail", args=[published.slug]))
    assert response.status_code == 404
    assert client.get(reverse(
        "problem_detail", args=[published.slug, problem.code],
    )).status_code == 404


def test_student_cannot_use_admin(client, student):
    client.force_login(student)
    assert client.get("/admin/").status_code == 302
    assert client.get("/admin/contests/testcase/").status_code == 302


def test_published_definitions_frozen(published, problem):
    problem.title = "Changed"
    with pytest.raises(ValidationError):
        problem.save()
    test = problem.tests.first()
    test.input_text = "new data"
    with pytest.raises(ValidationError):
        test.save()
    with pytest.raises(ValidationError):
        test.delete()
    published.ends_at += timedelta(hours=1)
    with pytest.raises(ValidationError):
        published.save()


def test_test_limits(problem):
    with override_settings(MAX_TEST_BYTES=4):
        with pytest.raises(ValidationError):
            ProblemTest.objects.create(
                problem=problem, input_text="12345", position=99,
            )
    with override_settings(MAX_CONTEST_TEST_BYTES=1):
        with pytest.raises(ValidationError):
            ProblemTest.objects.create(problem=problem, input_text="1", position=99)


def test_csrf_protection():
    client = Client(enforce_csrf_checks=True)
    assert client.post("/accounts/login/", {}).status_code == 403


def test_login_rate_limit(client, student):
    for _ in range(5):
        client.post("/accounts/login/", {
            "username": student.username, "password": "bad",
        })
    response = client.post("/accounts/login/", {
        "username": student.username, "password": "student-test-password",
    })
    assert response.status_code == 429
