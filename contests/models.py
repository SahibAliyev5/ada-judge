from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator, MinValueValidator, RegexValidator,
)
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

LANGUAGES = [("cpp20", "GNU C++20"), ("python3", "Python 3")]
VERDICTS = [
    (value, value) for value in [
        "QUEUED", "RUNNING", "AC", "WA", "TLE", "MLE", "RE", "CE",
        "OLE", "SYSTEM_ERROR",
    ]
]


def validate_source(value):
    if len(value.encode("utf-8")) > settings.MAX_SOURCE_BYTES:
        raise ValidationError("Source code exceeds the size limit.")


def validate_test_text(value):
    if len(value.encode("utf-8")) > settings.MAX_TEST_BYTES:
        raise ValidationError("Test data exceeds the size limit.")


class Contest(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=[("DRAFT", "Draft"), ("PUBLISHED", "Published")],
        default="DRAFT",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    verified_digest = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        ordering = ["-starts_at", "id"]
        constraints = [models.CheckConstraint(
            condition=Q(ends_at__gt=F("starts_at")), name="contest_positive_duration",
        )]

    def __str__(self):
        return self.title

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("The end must be after the start.")
        if self.status == "PUBLISHED":
            from .services import contest_digest

            if not self.pk or not self.verified_digest:
                raise ValidationError("Run verify_contest before publication.")
            if self.verified_digest != contest_digest(self):
                raise ValidationError("Definitions changed. Verify the contest again.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                previous = Contest.objects.select_for_update().get(pk=self.pk)
                if previous.status == "PUBLISHED":
                    raise ValidationError("Published contests are immutable.")
            self.full_clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            previous = Contest.objects.select_for_update().get(pk=self.pk)
            if previous.status == "PUBLISHED":
                raise ValidationError("Published contests cannot be deleted.")
            return super().delete(*args, **kwargs)


class ContestParticipant(models.Model):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    joined_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["contest", "user"], name="unique_participant",
        )]

    def __str__(self):
        return f"{self.contest}: {self.user}"


class FrozenDefinition(models.Model):
    """Serialize definition edits with publication and quota checks."""

    class Meta:
        abstract = True

    def clean(self):
        if self.get_contest_id() and Contest.objects.filter(
            pk=self.get_contest_id(), status="PUBLISHED",
        ).exists():
            raise ValidationError("Published problem definitions are frozen.")

    def get_contest_id(self):
        if isinstance(self, Problem):
            return self.contest_id
        return self.problem.contest_id if self.problem_id else None

    def save(self, *args, **kwargs):
        with transaction.atomic():
            contest = Contest.objects.select_for_update().get(
                pk=self.get_contest_id(),
            )
            if contest.status == "PUBLISHED":
                raise ValidationError("Published problem definitions are frozen.")
            if self.pk:
                old = type(self).objects.get(pk=self.pk)
                if old.get_contest_id() != self.get_contest_id():
                    raise ValidationError("Definitions cannot move between contests.")
            self.full_clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            contest = Contest.objects.select_for_update().get(
                pk=self.get_contest_id(),
            )
            if contest.status == "PUBLISHED":
                raise ValidationError("Published problem definitions are frozen.")
            return super().delete(*args, **kwargs)


class Problem(FrozenDefinition):
    contest = models.ForeignKey(
        Contest, on_delete=models.CASCADE, related_name="problems",
    )
    code = models.CharField(
        max_length=8, validators=[RegexValidator(r"^[A-Z][A-Z0-9]{0,7}$")],
    )
    title = models.CharField(max_length=200)
    statement = models.TextField()
    input_description = models.TextField()
    output_description = models.TextField()
    constraints_text = models.TextField()
    time_limit_ms = models.PositiveIntegerField(
        default=2000, validators=[MinValueValidator(100), MaxValueValidator(10000)],
    )
    memory_limit_mb = models.PositiveIntegerField(
        default=256, validators=[MinValueValidator(16), MaxValueValidator(512)],
    )
    comparison_mode = models.CharField(
        max_length=8, choices=[("tokens", "Tokens"), ("exact", "Exact")],
        default="tokens",
    )
    reference_language = models.CharField(max_length=10, choices=LANGUAGES)
    reference_source = models.TextField(validators=[validate_source])
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["contest", "code"], name="unique_code"),
            models.UniqueConstraint(
                fields=["contest", "display_order"], name="unique_problem_order",
            ),
            models.CheckConstraint(
                condition=Q(time_limit_ms__gte=100, time_limit_ms__lte=10000),
                name="valid_time_limit",
            ),
            models.CheckConstraint(
                condition=Q(memory_limit_mb__gte=16, memory_limit_mb__lte=512),
                name="valid_memory_limit",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"


class TestCase(FrozenDefinition):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="tests")
    input_text = models.TextField(blank=True, validators=[validate_test_text])
    expected_output = models.TextField(blank=True, validators=[validate_test_text])
    is_sample = models.BooleanField(default=False)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(
            fields=["problem", "position"], name="unique_test_order",
        )]

    def clean(self):
        super().clean()
        if not self.problem_id:
            return

        # PostgreSQL octet_length counts UTF-8 storage rather than characters.
        from django.db.models import BigIntegerField, Func, Sum

        size = Func(F("input_text"), function="octet_length")
        size += Func(F("expected_output"), function="octet_length")
        total = TestCase.objects.filter(
            problem__contest_id=self.problem.contest_id,
        ).exclude(pk=self.pk).aggregate(
            total=Sum(size, output_field=BigIntegerField()),
        )["total"] or 0
        total += len(self.input_text.encode()) + len(self.expected_output.encode())
        if total > settings.MAX_CONTEST_TEST_BYTES:
            raise ValidationError("Contest test storage quota exceeded.")

    def __str__(self):
        return f"{self.problem.code}: test {self.position}"


class Submission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    contest = models.ForeignKey(Contest, on_delete=models.PROTECT)
    problem = models.ForeignKey(Problem, on_delete=models.PROTECT)
    language = models.CharField(max_length=10, choices=LANGUAGES)
    source_code = models.TextField(validators=[validate_source])
    status = models.CharField(
        max_length=8, choices=[("QUEUED", "Queued"), ("RUNNING", "Running"),
                              ("DONE", "Done")], default="QUEUED",
    )
    verdict = models.CharField(max_length=12, choices=VERDICTS, default="QUEUED")
    execution_time_ms = models.PositiveIntegerField(default=0)
    memory_used_kb = models.PositiveIntegerField(default=0)
    compiler_message = models.TextField(blank=True)
    diagnostics = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=timezone.now, editable=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    worker_claim_token = models.UUIDField(null=True, blank=True, editable=False)
    worker_lease_until = models.DateTimeField(null=True, blank=True, editable=False)
    judge_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["submitted_at", "id"]
        permissions = [("rejudge_submission", "Can rejudge submissions")]
        indexes = [
            models.Index(fields=["status", "worker_lease_until", "id"]),
            models.Index(fields=["user", "-submitted_at"]),
            models.Index(fields=["contest", "verdict", "submitted_at"]),
        ]
        constraints = [models.CheckConstraint(
            condition=(
                Q(status="QUEUED", verdict="QUEUED")
                | Q(status="RUNNING", verdict="RUNNING")
                | Q(status="DONE", verdict__in=[
                    "AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "SYSTEM_ERROR",
                ])
            ), name="consistent_submission_state",
        )]

    def clean(self):
        if self.problem_id and self.problem.contest_id != self.contest_id:
            raise ValidationError("Problem does not belong to this contest.")


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
    )
    timestamp = models.DateTimeField(default=timezone.now, editable=False)
    action = models.CharField(max_length=80)
    affected_object = models.CharField(max_length=200)
    summary = models.CharField(max_length=300)

    class Meta:
        ordering = ["-timestamp", "-id"]
