from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from contests.models import AuditLog, Contest, Submission
from contests.services import create_submission, rejudge_submissions

pytestmark = pytest.mark.django_db


def test_submission_is_queued(student, published, problem):
    submission = create_submission(student, published, problem, "python3", "print(8)")
    assert submission.status == "QUEUED"
    assert submission.verdict == "QUEUED"
    assert submission.submitted_at >= published.starts_at
    assert submission.worker_claim_token is None


def test_submission_deadline(student, published, problem):
    Contest.objects.filter(pk=published.pk).update(ends_at=timezone.now())
    with pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "print(8)")


def test_submission_before_start(student, published, problem):
    Contest.objects.filter(pk=published.pk).update(
        starts_at=timezone.now() + timedelta(minutes=1),
    )
    with pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "print(8)")


def test_source_and_language_validation(student, published, problem):
    with override_settings(MAX_SOURCE_BYTES=4), pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "ééé")
    with pytest.raises(ValidationError):
        create_submission(student, published, problem, "shell", "echo 8")


def test_wrong_problem_rejected(student, published, problem):
    problem.contest_id = 999999
    with pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "print(8)")


def test_rate_limits(student, published, problem):
    create_submission(student, published, problem, "python3", "print(8)")
    with pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "print(8)")
    Submission.objects.update(submitted_at=timezone.now() - timedelta(minutes=1))
    with override_settings(SUBMISSION_HOURLY_LIMIT=1), pytest.raises(ValidationError):
        create_submission(student, published, problem, "python3", "print(8)")


def test_private_sources(client, student, published, problem):
    submission = create_submission(student, published, problem, "python3", "private_source")
    outsider = User.objects.create_user("outsider")
    from contests.models import ContestParticipant

    ContestParticipant.objects.create(contest=published, user=outsider)
    client.force_login(outsider)
    url = reverse("submission_detail", args=[published.slug, submission.pk])
    assert client.get(url).status_code == 404
    client.force_login(student)
    response = client.get(url)
    assert "private_source" in response.content.decode()
    submission.diagnostics = "hidden test: secret"
    submission.save()
    assert "hidden test: secret" not in client.get(url).content.decode()


def test_submit_endpoint_and_csrf(student, published, problem):
    url = reverse("submit_solution", args=[published.slug])
    client = Client(enforce_csrf_checks=True)
    assert client.get(url).status_code == 302
    client.force_login(student)
    assert client.post(url, {}).status_code == 403
    client.get(url)
    response = client.post(url, {
        "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        "problem": problem.pk, "language": "python3", "source_code": "print(8)",
    })
    assert response.status_code == 302
    assert Submission.objects.get().status == "QUEUED"


def test_rejudge_requires_permission_and_revokes_claim(student, published, problem):
    submission = create_submission(student, published, problem, "python3", "print(8)")
    from judge.worker import claim_submission, finish_submission

    stale = claim_submission()
    queryset = Submission.objects.filter(pk=submission.pk)
    with pytest.raises(PermissionDenied):
        rejudge_submissions(student, queryset)
    student.user_permissions.add(Permission.objects.get(codename="rejudge_submission"))
    student = User.objects.get(pk=student.pk)
    rejudge_submissions(student, queryset)
    assert finish_submission(stale, {"verdict": "AC"}) == 0
    assert queryset.get().status == "QUEUED"
    assert AuditLog.objects.filter(action="Submission rejudged", actor=student).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_submission_limits(student, published, problem):
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            create_submission(student, published, problem, "python3", "print(8)")
            return "created"
        except ValidationError:
            return "limited"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(results) == ["created", "limited"]
    assert Submission.objects.count() == 1
