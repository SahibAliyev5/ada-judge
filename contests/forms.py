from django import forms
from django.conf import settings

from .models import LANGUAGES, validate_source


class SubmissionForm(forms.Form):
    problem = forms.ModelChoiceField(queryset=None)
    language = forms.ChoiceField(choices=LANGUAGES)
    source_code = forms.CharField(
        strip=False, validators=[validate_source],
        widget=forms.Textarea(attrs={
            "spellcheck": "false", "autocomplete": "off", "aria-label": "Source code",
        }), max_length=settings.MAX_SOURCE_BYTES,
    )

    def __init__(self, *args, contest, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["problem"].queryset = contest.problems.all()
