from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contests.models import AuditLog, Contest
from contests.services import contest_digest
from judge.judging import judge_solution
from judge.sandbox import SandboxError, check_environment


class Command(BaseCommand):
    help = "Verify reference solutions on the Linux judge; does not publish."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            check_environment()
            actor = User.objects.get(username=options["actor"], is_active=True)
            if not actor.has_perm("contests.change_contest"):
                raise CommandError("Actor needs contest change permission.")
            contest = Contest.objects.get(slug=options["slug"], status="DRAFT")
            problems = list(contest.problems.prefetch_related("tests").order_by("id"))
            digest = contest_digest(contest, problems)
            if not problems:
                raise CommandError("Contest needs at least one problem.")
            for problem in problems:
                problem.full_clean()
                tests = list(problem.tests.all())
                if sum(test.is_sample for test in tests) < 1:
                    raise CommandError(f"{problem.code}: needs a sample test.")
                if sum(not test.is_sample for test in tests) < 2:
                    raise CommandError(f"{problem.code}: needs two hidden tests.")
                for test in tests:
                    test.full_clean()
                result = judge_solution(
                    problem, problem.reference_language, problem.reference_source,
                )
                if result["verdict"] != "AC":
                    raise CommandError(f"{problem.code}: reference {result['verdict']}")
            with transaction.atomic():
                contest = Contest.objects.select_for_update().get(pk=contest.pk)
                if contest.status != "DRAFT" or contest_digest(contest) != digest:
                    raise CommandError("Definitions changed during verification.")
                contest.verified_digest = digest
                contest.save(update_fields=["verified_digest"])
                AuditLog.objects.create(
                    actor=actor, action="Contest verified",
                    affected_object=f"contests.Contest:{contest.pk}",
                    summary="All reference solutions passed in Isolate",
                )
        except (
            ValidationError, SandboxError, Contest.DoesNotExist, User.DoesNotExist,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Verified. Publish through Django Admin."))
