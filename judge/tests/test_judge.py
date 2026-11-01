import signal
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from contests.models import Submission
from judge.judging import compiler_diagnostics, judge_solution, outputs_match
from judge.sandbox import SandboxError, check_environment, verdict_from_metadata
from judge.worker import (
    LostClaim, claim_submission, finish_submission, process_submission, renew_claim,
)


@pytest.mark.parametrize("actual,expected,mode,matches", [
    (b" 8\n", b"8", "tokens", True),
    (b"", b"8", "tokens", False),
    (b"8 extra", b"8", "tokens", False),
    (b"8\r\n", b"8\n", "exact", True),
    (b"8 \n", b"8\n", "exact", False),
])
def test_comparison(actual, expected, mode, matches):
    assert outputs_match(actual, expected, mode) is matches


@pytest.mark.parametrize("fields,verdict", [
    ({}, "AC"), ({"status": "TO"}, "TLE"),
    ({"status": "SG", "exitsig": "9", "cg-oom-killed": "1"}, "MLE"),
    ({"status": "RE", "exitcode": "1"}, "RE"),
    ({"status": "SG", "exitsig": str(signal.SIGXFSZ)}, "OLE"),
])
def test_resource_verdicts(fields, verdict):
    assert verdict_from_metadata(fields) == verdict


def test_unknown_status_fails_closed():
    with pytest.raises(SandboxError):
        verdict_from_metadata({"status": "XX"})


def test_disabled_worker_fails_closed():
    with override_settings(JUDGE_ENABLED=False), pytest.raises(SandboxError):
        check_environment()


def test_compiler_paths_removed():
    assert "/box/" not in compiler_diagnostics(b"/box/main.cpp:3: syntax error")


@pytest.fixture
def queued(student, published, problem):
    return Submission.objects.create(
        user=student, contest=published, problem=problem,
        language="python3", source_code="print(8)",
    )


@pytest.mark.django_db
def test_stale_worker_cannot_commit(queued):
    first = claim_submission()
    Submission.objects.filter(pk=queued.pk).update(
        worker_lease_until=timezone.now() - timedelta(seconds=1),
    )
    second = claim_submission()
    assert first.worker_claim_token != second.worker_claim_token
    assert finish_submission(first, {"verdict": "WA"}) == 0
    with pytest.raises(LostClaim):
        renew_claim(first)
    assert finish_submission(second, {"verdict": "AC"}) == 1
    queued.refresh_from_db()
    assert queued.verdict == "AC"


@pytest.mark.django_db
def test_worker_claim_is_exclusive(queued):
    assert claim_submission().pk == queued.pk
    assert claim_submission() is None


@pytest.mark.django_db
def test_crashed_worker_retry_exhaustion(queued):
    for _ in range(3):
        assert claim_submission().status == "RUNNING"
        Submission.objects.filter(pk=queued.pk).update(
            worker_lease_until=timezone.now() - timedelta(seconds=1),
        )
    assert claim_submission().verdict == "SYSTEM_ERROR"


@pytest.mark.django_db
def test_infrastructure_failure_retries_then_errors(queued):
    with patch("judge.worker.judge_solution", side_effect=SandboxError("unavailable")):
        for _ in range(3):
            process_submission(claim_submission())
    queued.refresh_from_db()
    assert queued.verdict == "SYSTEM_ERROR"
    assert "SandboxError" in queued.diagnostics


@pytest.mark.django_db
def test_every_test_gets_a_new_execute_call(problem):
    results = [
        {"verdict": "AC", "output": output, "time_ms": 1, "memory_kb": 64}
        for output in (b"8\n", b"13\n", b"-781\n")
    ]
    with patch("judge.judging.execute", side_effect=results) as execute:
        result = judge_solution(problem, "python3", "print(8)")
    assert result["verdict"] == "AC"
    assert execute.call_count == 3


@pytest.mark.django_db
def test_compiler_failure_is_ce(problem):
    with patch("judge.judging.execute", return_value={
        "verdict": "RE", "errors": b"/box/main.cpp: syntax error",
    }):
        result = judge_solution(problem, "cpp20", "invalid")
    assert result["verdict"] == "CE"
    assert "/box" not in result["compiler_message"]


def test_missing_accounting_is_infrastructure_error(tmp_path):
    from judge.sandbox import parse_metadata

    path = tmp_path / "metadata"
    path.write_text("time:0.01\nexitcode:0\n")
    with pytest.raises(SandboxError):
        parse_metadata(path)


def test_output_symlinks_are_not_followed(tmp_path):
    from judge.sandbox import read_file

    secret = tmp_path / "secret"
    secret.write_text("confidential")
    link = tmp_path / "output"
    link.symlink_to(secret)
    with pytest.raises(SandboxError):
        read_file(link, 1024)


@pytest.mark.django_db(transaction=True)
def test_locked_job_is_skipped(queued):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, transaction

    second = Submission.objects.create(
        user=queued.user, contest=queued.contest, problem=queued.problem,
        language="python3", source_code="print(8)",
    )
    locked = Event()
    release = Event()

    def lock_first_job():
        close_old_connections()
        try:
            with transaction.atomic():
                Submission.objects.select_for_update().get(pk=queued.pk)
                locked.set()
                assert release.wait(timeout=10)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lock_first_job)
        try:
            assert locked.wait(timeout=10)
            assert claim_submission().pk == second.pk
        finally:
            release.set()
        future.result(timeout=10)
    queued.refresh_from_db()
    assert queued.status == "QUEUED"


def test_runtime_self_check_refuses_bad_results():
    from judge.judging import check_runtime

    with patch("judge.judging.judge_solution", return_value={"verdict": "WA"}):
        with pytest.raises(SandboxError):
            check_runtime()
