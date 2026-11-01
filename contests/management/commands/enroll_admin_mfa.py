from getpass import getpass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from contests.models import AuditLog


class Command(BaseCommand):
    help = "Enroll a staff TOTP device from a trusted administrator console."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        # This command is an operator bootstrap path, never an HTTP endpoint.
        # Do not capture its output in logs: the URI contains the TOTP secret.
        user = User.objects.filter(
            username=options["username"], is_active=True, is_staff=True,
        ).first()
        password = getpass("Account password: ")
        if user is None or not user.check_password(password):
            raise CommandError("An active staff account is required.")
        with transaction.atomic():
            device = TOTPDevice.objects.create(
                user=user, name="Administrator authenticator", confirmed=False,
            )
            self.stdout.write("Enter this URI in your authenticator, privately:")
            self.stdout.write(device.config_url)
            token = getpass("Current authenticator code: ")
            if not device.verify_token(token):
                raise CommandError("Invalid token; enrollment was rolled back.")
            device.confirmed = True
            device.save()
            AuditLog.objects.create(
                actor=user, action="Staff MFA enrolled",
                affected_object=f"auth.User:{user.pk}",
                summary="TOTP enrolled from the trusted console",
            )
        self.stdout.write(self.style.SUCCESS("Authenticator enrolled."))
