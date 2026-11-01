import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone

from .models import Contest


def contest_digest(contest):
    definitions = []
    for problem in contest.problems.order_by("id"):
        definition = {
            field.attname: getattr(problem, field.attname)
            for field in problem._meta.fields
        }
        definition["tests"] = list(problem.tests.values())
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
