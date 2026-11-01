import logging
import threading
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone

from contests.models import Submission
from .judging import judge_solution

logger = logging.getLogger(__name__)


class LostClaim(Exception):
    pass


def claim_submission():
    with transaction.atomic():
        submission = Submission.objects.select_for_update(skip_locked=True).filter(
            Q(status="QUEUED") | Q(status="RUNNING", worker_lease_until__lte=Now()),
        ).order_by("submitted_at", "id").first()
        if submission is None:
            return None
        if submission.judge_attempts >= settings.JUDGE_MAX_ATTEMPTS:
            submission.status = "DONE"
            submission.verdict = "SYSTEM_ERROR"
            submission.finished_at = timezone.now()
            submission.worker_claim_token = None
            submission.worker_lease_until = None
        else:
            submission.status = "RUNNING"
            submission.verdict = "RUNNING"
            submission.worker_claim_token = uuid.uuid4()
            submission.worker_lease_until = timezone.now() + timedelta(
                seconds=settings.JUDGE_LEASE_SECONDS,
            )
            submission.started_at = timezone.now()
            submission.judge_attempts += 1
        submission.save()
        return submission


def owned_claim(submission):
    return Submission.objects.filter(
        pk=submission.pk, status="RUNNING",
        worker_claim_token=submission.worker_claim_token, worker_lease_until__gt=Now(),
    )


def renew_claim(submission):
    updated = owned_claim(submission).update(
        worker_lease_until=Now() + timedelta(seconds=settings.JUDGE_LEASE_SECONDS),
    )
    if not updated:
        raise LostClaim("Worker no longer owns this submission.")


def finish_submission(submission, result):
    return owned_claim(submission).update(
        **result, status="DONE", finished_at=Now(),
        worker_claim_token=None, worker_lease_until=None,
    )


def process_submission(submission):
    if submission.status != "RUNNING":
        return
    stopped = threading.Event()
    lost = threading.Event()

    def keep_lease():
        close_old_connections()
        try:
            while not stopped.wait(settings.JUDGE_LEASE_SECONDS / 3):
                renew_claim(submission)
        except Exception:
            lost.set()
            logger.exception("Lease renewal failed for submission %s", submission.pk)
        finally:
            close_old_connections()

    def heartbeat():
        if lost.is_set():
            raise LostClaim
        renew_claim(submission)

    thread = threading.Thread(target=keep_lease, daemon=True)
    thread.start()
    try:
        result = judge_solution(
            submission.problem, submission.language, submission.source_code, heartbeat,
        )
        finish_submission(submission, result)
    except LostClaim:
        logger.warning("Lost claim for submission %s", submission.pk)
    except Exception as error:
        logger.exception("Infrastructure failure for submission %s", submission.pk)
        fields = {
            "diagnostics": f"{type(error).__name__}: {str(error)[:2000]}",
            "worker_claim_token": None, "worker_lease_until": None,
        }
        if submission.judge_attempts < settings.JUDGE_MAX_ATTEMPTS:
            fields.update(status="QUEUED", verdict="QUEUED")
        else:
            fields.update(status="DONE", verdict="SYSTEM_ERROR", finished_at=Now())
        owned_claim(submission).update(**fields)
    finally:
        stopped.set()
        thread.join(timeout=10)
