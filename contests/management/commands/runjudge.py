import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from judge.sandbox import SandboxError, check_environment
from judge.worker import claim_submission, process_submission


class Command(BaseCommand):
    help = "Run the PostgreSQL judge worker on a dedicated Linux VM."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        try:
            check_environment()
        except SandboxError as error:
            raise CommandError(str(error)) from error
        try:
            while True:
                close_old_connections()
                submission = claim_submission()
                if submission:
                    process_submission(submission)
                if options["once"]:
                    return
                if submission is None:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Judge stopped; leases recover unfinished work.")
