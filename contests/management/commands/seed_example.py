from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from contests.models import AuditLog, Contest, Problem, TestCase


class Command(BaseCommand):
    help = "Create an unpublished example contest; verification is still required."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--starts-in-minutes", type=int, default=60)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = User.objects.filter(username=options["actor"], is_active=True).first()
        if actor is None or not actor.has_perm("contests.add_contest"):
            raise CommandError("Actor needs contest creation permission.")
        if Contest.objects.filter(slug="example-practice").exists():
            raise CommandError("The example contest already exists; no changes made.")
        starts_at = timezone.now() + timedelta(minutes=options["starts_in_minutes"])
        contest = Contest.objects.create(
            title="University Practice Contest", slug="example-practice",
            description="Two introductory problems for a supervised rehearsal.",
            starts_at=starts_at, ends_at=starts_at + timedelta(hours=2),
            created_by=actor,
        )
        problem = Problem.objects.create(
            contest=contest, code="A", title="Two Numbers", display_order=0,
            statement="Given two integers, print their sum.",
            input_description="Two space-separated integers a and b.",
            output_description="Print a + b followed by a newline.",
            constraints_text="-1,000,000 <= a, b <= 1,000,000",
            reference_language="cpp20", reference_source=(
                "#include <iostream>\nint main() {\n"
                "    long long first, second;\n"
                "    std::cin >> first >> second;\n"
                "    std::cout << first + second << '\\n';\n}\n"
            ),
        )
        self.add_tests(problem, [
            ("3 5\n", "8\n"), ("-1000000 999999\n", "-1\n"), ("0 0\n", "0\n"),
        ])
        problem = Problem.objects.create(
            contest=contest, code="B", title="Largest Number", display_order=1,
            statement="Find the largest number in a nonempty list of integers.",
            input_description="n on the first line, then n space-separated integers.",
            output_description="Print the largest integer followed by a newline.",
            constraints_text="1 <= n <= 1000; each value is between -10^9 and 10^9.",
            reference_language="python3", reference_source=(
                "count = int(input())\nvalues = list(map(int, input().split()))\n"
                "print(max(values))\n"
            ),
        )
        self.add_tests(problem, [
            ("4\n2 8 1 5\n", "8\n"), ("3\n-8 -2 -100\n", "-2\n"),
            ("1\n1000000000\n", "1000000000\n"),
        ])
        AuditLog.objects.create(
            actor=actor, action="Example contest created",
            affected_object=f"contests.Contest:{contest.pk}",
            summary="Two draft problems; sandbox verification required",
        )
        self.stdout.write("Example created as DRAFT. Run verify_contest on Linux.")

    def add_tests(self, problem, cases):
        for position, (input_text, expected_output) in enumerate(cases):
            TestCase.objects.create(
                problem=problem, input_text=input_text, expected_output=expected_output,
                is_sample=position == 0, position=position,
            )
