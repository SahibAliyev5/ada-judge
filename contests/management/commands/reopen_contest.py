from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contests.models import AuditLog, Contest, Submission
from contests.services import rejudge_submissions


class Command(BaseCommand):
    help = "Audit an emergency correction pause after all judging has drained."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = User.objects.filter(username=options["actor"], is_active=True).first()
        if actor is None or not actor.has_perms([
            "contests.change_contest", "contests.rejudge_submission",
        ]):
            raise CommandError("Actor needs contest change and rejudge permissions.")
        reason = options["reason"].strip()
        if not reason or len(reason) > 200:
            raise CommandError("Give a non-sensitive reason of 1–200 characters.")
        contest = Contest.objects.select_for_update().filter(
            slug=options["slug"], status="PUBLISHED",
        ).first()
        if contest is None:
            raise CommandError("A published contest is required.")
        submissions = Submission.objects.filter(contest=contest)
        if submissions.filter(status__in=["RUNNING", "QUEUED"]).exists():
            raise CommandError("Stop incoming submissions and drain the judge first.")
        # This is the sole, audited exception to the published-definition freeze.
        # Draft contests cannot receive submissions or be claimed by workers.
        Contest.objects.filter(pk=contest.pk).update(status="DRAFT", verified_digest="")
        rejudge_submissions(actor, submissions)
        AuditLog.objects.create(
            actor=actor, action="Contest paused for correction",
            affected_object=f"contests.Contest:{contest.pk}", summary=reason,
        )
        self.stdout.write(
            "Contest is DRAFT. Correct definitions, verify on Linux, then publish. "
            "All prior submissions will be rejudged after publication.",
        )
