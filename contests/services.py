import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models.functions import Now
from django.http import Http404
from django.utils import timezone

from .models import (
    LANGUAGES, AuditLog, Contest, ContestParticipant, Submission, validate_source,
)


def contest_digest(contest, problems=None):
    if problems is None:
        problems = contest.problems.prefetch_related("tests").order_by("id")
    definitions = []
    for problem in problems:
        definition = {
            field.attname: getattr(problem, field.attname)
            for field in problem._meta.fields
        }
        definition["tests"] = [
            {field.attname: getattr(test, field.attname) for field in test._meta.fields}
            for test in problem.tests.all()
        ]
        definitions.append(definition)
    payload = json.dumps(definitions, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def participant_contest(user, slug, require_started=False):
    try:
        contest = Contest.objects.get(
            slug=slug, status="PUBLISHED", contestparticipant__user=user,
        )
    except Contest.DoesNotExist:
        raise Http404 from None
    if require_started and timezone.now() < contest.starts_at:
        raise PermissionDenied("Problems are available when the contest starts.")
    return contest


def create_submission(user, contest, problem, language, source):
    validate_source(source)
    if not source.strip() or language not in dict(LANGUAGES):
        raise ValidationError("Select a supported language and enter source code.")
    with transaction.atomic():
        # One lock per account serializes rate checks across all contests.
        account = User.objects.select_for_update().filter(
            pk=user.pk, is_active=True,
        ).first()
        if account is None:
            raise PermissionDenied("An active account is required.")
        contest = Contest.objects.select_for_update(no_key=True).filter(
            pk=contest.pk, status="PUBLISHED",
        ).first()
        if contest is None:
            raise ValidationError("This contest is not available for submissions.")
        enrolled = ContestParticipant.objects.select_for_update().filter(
            user=user, contest=contest,
        ).exists()
        received_at = User.objects.filter(pk=user.pk).annotate(
            received=Now(),
        ).values_list("received", flat=True).get()
        if not enrolled:
            raise PermissionDenied("You are not enrolled in this contest.")
        if not contest.starts_at <= received_at < contest.ends_at:
            raise ValidationError("Submissions are accepted only during the contest.")
        if problem.contest_id != contest.pk:
            raise ValidationError("Problem does not belong to this contest.")
        submissions = Submission.objects.filter(user=user)
        cutoff = received_at - timedelta(seconds=settings.SUBMISSION_INTERVAL_SECONDS)
        if submissions.filter(submitted_at__gt=cutoff).exists():
            raise ValidationError("Wait 15 seconds between submissions.")
        hourly_count = submissions.filter(
            submitted_at__gt=received_at - timedelta(hours=1),
        ).count()
        if hourly_count >= settings.SUBMISSION_HOURLY_LIMIT:
            raise ValidationError("Hourly submission limit reached.")
        return Submission.objects.create(
            user=user, contest=contest, problem=problem, language=language,
            source_code=source, submitted_at=received_at,
        )


def leaderboard(contest):
    problems = list(contest.problems.all())
    rows = {}
    participants = ContestParticipant.objects.filter(
        contest=contest,
    ).select_related("user")
    for participant in participants:
        rows[participant.user_id] = {
            "username": participant.user.username, "user_id": participant.user_id,
            "solved": 0, "penalty": 0, "last_ac": contest.starts_at,
            "problems": {problem.pk: {"attempts": 0, "accepted": False}
                         for problem in problems},
        }
    submissions = Submission.objects.filter(
        contest=contest, status="DONE", submitted_at__gte=contest.starts_at,
        submitted_at__lt=contest.ends_at,
    ).order_by("submitted_at", "id").values(
        "user_id", "problem_id", "verdict", "submitted_at",
    )
    for submission in submissions:
        row = rows.get(submission["user_id"])
        if row is None:
            continue
        cell = row["problems"].get(submission["problem_id"])
        if cell is None or cell["accepted"]:
            continue
        verdict = submission["verdict"]
        if verdict in ("CE", "SYSTEM_ERROR"):
            continue
        if verdict != "AC":
            cell["attempts"] += 1
            continue
        cell["accepted"] = True
        elapsed = submission["submitted_at"] - contest.starts_at
        minutes = int(elapsed.total_seconds() // 60)
        row["solved"] += 1
        row["penalty"] += minutes + 20 * cell["attempts"]
        row["last_ac"] = submission["submitted_at"]
    results = list(rows.values())
    results.sort(key=lambda row: (
        -row["solved"], row["penalty"], row["last_ac"],
        row["username"], row["user_id"],
    ))
    for rank, row in enumerate(results, start=1):
        row["rank"] = rank
        row["cells"] = [row["problems"][problem.pk] for problem in problems]
    return problems, results


def rejudge_submissions(actor, submissions):
    if not actor.has_perm("contests.rejudge_submission"):
        raise PermissionDenied
    with transaction.atomic():
        # Serialize administrative rejudging with a contest correction pause.
        contest_ids = set(submissions.values_list("contest_id", flat=True))
        list(Contest.objects.select_for_update().filter(
            pk__in=contest_ids,
        ).order_by("pk"))
        for submission in submissions.select_for_update().order_by("pk"):
            Submission.objects.filter(pk=submission.pk).update(
                status="QUEUED", verdict="QUEUED", execution_time_ms=0,
                memory_used_kb=0, compiler_message="", diagnostics="",
                started_at=None, finished_at=None, worker_claim_token=None,
                worker_lease_until=None, judge_attempts=0,
            )
            AuditLog.objects.create(
                actor=actor, action="Submission rejudged",
                affected_object=f"contests.Submission:{submission.pk}",
                summary="Queued again; previous worker claim revoked",
            )
