from unittest.mock import patch

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, override_settings

from contests.models import Contest, Problem

pytestmark = pytest.mark.django_db


def test_production_admin_requires_mfa(student):
    student.is_staff = True
    student.is_verified = lambda: False
    request = RequestFactory().get("/admin/")
    request.user = student
    with override_settings(REQUIRE_ADMIN_MFA=True):
        assert admin.site.has_permission(request) is False
        student.is_verified = lambda: True
        assert admin.site.has_permission(request) is True


def test_non_superuser_cannot_grant_roles(client):
    staff = User.objects.create_user("staff", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="change_user"))
    client.force_login(staff)
    assert client.post(f"/admin/auth/user/{staff.pk}/change/", {
        "is_superuser": "on",
    }).status_code == 403
    staff.refresh_from_db()
    assert not staff.is_superuser


def test_verification_and_stale_digest(contest, problem, student):
    student.user_permissions.add(Permission.objects.get(codename="change_contest"))
    with patch("contests.management.commands.verify_contest.check_environment"), patch(
        "contests.management.commands.verify_contest.judge_solution",
        return_value={"verdict": "AC"},
    ):
        call_command("verify_contest", contest.slug, actor=student.username)
    contest.refresh_from_db()
    assert contest.verified_digest
    problem.title = "Changed after verification"
    problem.save()
    contest.status = "PUBLISHED"
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        contest.save()


def test_verification_rejects_failed_reference(contest, problem, student):
    student.user_permissions.add(Permission.objects.get(codename="change_contest"))
    with patch("contests.management.commands.verify_contest.check_environment"), patch(
        "contests.management.commands.verify_contest.judge_solution",
        return_value={"verdict": "WA"},
    ), pytest.raises(CommandError):
        call_command("verify_contest", contest.slug, actor=student.username)
    contest.refresh_from_db()
    assert contest.verified_digest == ""


def test_example_is_unverified(student):
    student.user_permissions.add(Permission.objects.get(codename="add_contest"))
    call_command("seed_example", actor=student.username)
    contest = Contest.objects.get(slug="example-practice")
    assert contest.status == "DRAFT"
    assert contest.verified_digest == ""
    assert Problem.objects.filter(contest=contest).count() == 2


def test_staff_can_view_results_without_enrollment(client, published):
    staff = User.objects.create_user("result_staff", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_contest"))
    client.force_login(staff)
    from django.urls import reverse

    response = client.get(reverse("admin:contest_results", args=[published.pk]))
    assert response.status_code == 200
    assert "student" in response.content.decode()


def test_audited_correction_requires_reverification(published, problem, student):
    from contests.models import AuditLog, Submission
    from judge.worker import claim_submission

    student.user_permissions.add(*Permission.objects.filter(codename__in=[
        "change_contest", "rejudge_submission",
    ]))
    submission = Submission.objects.create(
        user=student, contest=published, problem=problem, status="DONE", verdict="AC",
        language="python3", source_code="unexecuted fixture",
    )
    call_command(
        "reopen_contest", published.slug, actor=student.username,
        reason="Correct an expected output after review",
    )
    published.refresh_from_db()
    submission.refresh_from_db()
    assert published.status == "DRAFT"
    assert not published.verified_digest
    assert submission.status == "QUEUED"
    assert claim_submission() is None
    test = problem.tests.first()
    test.expected_output = "corrected expected output"
    test.save()
    assert AuditLog.objects.filter(action="Contest paused for correction").exists()
    published.status = "PUBLISHED"
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        published.save()


def test_correction_refuses_queued_jobs(published, problem, student):
    from contests.models import Submission

    student.user_permissions.add(*Permission.objects.filter(codename__in=[
        "change_contest", "rejudge_submission",
    ]))
    Submission.objects.create(
        user=student, contest=published, problem=problem, language="python3",
        source_code="unexecuted fixture",
    )
    with pytest.raises(CommandError):
        call_command(
            "reopen_contest", published.slug, actor=student.username,
            reason="Reviewed correction",
        )
    published.refresh_from_db()
    assert published.status == "PUBLISHED"


def test_admin_cannot_save_over_worker_results(client, published, problem, student):
    from contests.models import Submission
    from django.urls import reverse

    administrator = User.objects.create_superuser("admin", password="test-password")
    submission = Submission.objects.create(
        user=student, contest=published, problem=problem, language="python3",
        source_code="unexecuted test fixture",
    )
    client.force_login(administrator)
    response = client.post(reverse(
        "admin:contests_submission_change", args=[submission.pk],
    ), {"verdict": "AC", "status": "DONE", "_save": "Save"})
    assert response.status_code == 403
    submission.refresh_from_db()
    assert submission.verdict == "QUEUED"
