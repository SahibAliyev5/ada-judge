"""Optional PostgreSQL grant tests; use only an isolated CREATEROLE test account."""
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import ProgrammingError, connection, transaction
from psycopg import sql

from contests.models import Submission
from judge.worker import claim_submission, finish_submission, renew_claim

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_ROLE_TESTS") != "1",
        reason="Requires CREATEROLE on a disposable PostgreSQL test cluster.",
    ),
]


@pytest.fixture
def roles(db):
    suffix = uuid.uuid4().hex[:12]
    worker = f"worker_test_{suffix}"
    verifier = f"verifier_test_{suffix}"
    grants = Path(settings.BASE_DIR, "deployment/database-grants.sql").read_text()
    grants = grants.replace("contest_worker", worker)
    grants = grants.replace("contest_verifier", verifier)
    grants = grants.replace("contest_web", f"web_test_{suffix}")
    grants = grants.replace("contest_backup", f"backup_test_{suffix}")
    database = connection.ops.quote_name(connection.settings_dict["NAME"])
    grants = grants.replace("DATABASE contest", f"DATABASE {database}")
    with connection.cursor() as cursor:
        cursor.execute(grants)
    return worker, verifier


def assume_role(role):
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))


def test_worker_grants(roles, student, published, problem):
    submission = Submission.objects.create(
        user=student, contest=published, problem=problem,
        language="python3", source_code="unexecuted test fixture",
    )
    assume_role(roles[0])
    claimed = claim_submission()
    assert claimed.pk == submission.pk
    renew_claim(claimed)
    assert finish_submission(claimed, {"verdict": "SYSTEM_ERROR"}) == 1
    for statement in [
        "UPDATE auth_user SET is_superuser = true",
        "UPDATE contests_problem SET title = 'tampered'",
        "UPDATE contests_submission SET source_code = 'tampered'",
        "UPDATE contests_submission SET submitted_at = now()",
    ]:
        with pytest.raises(ProgrammingError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


def test_verifier_grants(roles, student, contest, problem):
    student.user_permissions.add(Permission.objects.get(codename="change_contest"))
    assume_role(roles[1])
    with patch("contests.management.commands.verify_contest.check_environment"), patch(
        "contests.management.commands.verify_contest.judge_solution",
        return_value={"verdict": "AC"},
    ):
        call_command("verify_contest", contest.slug, actor=student.username)
    contest.refresh_from_db()
    assert contest.verified_digest
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
