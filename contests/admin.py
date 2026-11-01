from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import (
    AuditLog, Contest, ContestParticipant, Problem, Submission, TestCase,
)


class FrozenAdmin(admin.ModelAdmin):
    actions = None

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        if obj is None:
            return allowed
        contest_id = obj.pk if isinstance(obj, Contest) else obj.get_contest_id()
        return allowed and not Contest.objects.filter(
            pk=contest_id, status="PUBLISHED",
        ).exists()

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        action = "Definition changed"
        if isinstance(obj, Contest) and obj.status == "PUBLISHED":
            action = "Contest published"
        AuditLog.objects.create(
            actor=request.user, action=action,
            affected_object=f"{obj._meta.label}:{obj.pk}",
            summary="Fields: " + ", ".join(form.changed_data)[:250],
        )

    def delete_model(self, request, obj):
        AuditLog.objects.create(
            actor=request.user, action="Definition deleted",
            affected_object=f"{obj._meta.label}:{obj.pk}", summary="Deleted in admin",
        )
        super().delete_model(request, obj)


@admin.register(Contest)
class ContestAdmin(FrozenAdmin):
    list_display = ["title", "starts_at", "ends_at", "status", "results_link"]
    list_filter = ["status"]
    prepopulated_fields = {"slug": ["title"]}
    readonly_fields = ["created_by", "verified_digest"]

    @admin.display(description="Results")
    def results_link(self, obj):
        url = reverse("admin:contest_results", args=[obj.pk])
        return format_html('<a href="{}">Standings</a>', url)

    def get_urls(self):
        return [path(
            "<int:contest_id>/results/", self.admin_site.admin_view(self.results),
            name="contest_results",
        )] + super().get_urls()

    def results(self, request, contest_id):
        from .services import leaderboard

        contest = get_object_or_404(Contest, pk=contest_id)
        if not self.has_view_permission(request, contest):
            raise PermissionDenied
        problems, rows = leaderboard(contest)
        context = {
            **self.admin_site.each_context(request), "title": contest.title,
            "problems": problems, "rows": rows,
        }
        return TemplateResponse(request, "admin/contest_results.html", context)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Problem)
class ProblemAdmin(FrozenAdmin):
    list_display = ["code", "title", "contest"]
    list_filter = ["contest"]


@admin.register(TestCase)
class TestCaseAdmin(FrozenAdmin):
    list_display = ["problem", "position", "is_sample"]
    list_filter = ["problem__contest", "is_sample"]


@admin.register(ContestParticipant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ["contest", "user", "joined_at"]
    list_filter = ["contest"]
    autocomplete_fields = ["user"]
    readonly_fields = ["joined_at"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "contest", "problem", "verdict", "submitted_at"]
    list_filter = ["contest", "verdict"]
    readonly_fields = [field.name for field in Submission._meta.fields]
    actions = ["rejudge"]

    @admin.action(description="Rejudge selected submissions", permissions=["rejudge"])
    def rejudge(self, request, queryset):
        from .services import rejudge_submissions

        rejudge_submissions(request.user, queryset)
        self.message_user(request, "Selected submissions queued for rejudging.")

    def has_rejudge_permission(self, request):
        return request.user.has_perm("contests.rejudge_submission")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "actor", "action", "affected_object"]
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Account permissions and MFA devices are controlled only by superusers.
class SuperuserChanges:
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class AuditedUserAdmin(SuperuserChanges, UserAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if {"is_staff", "is_superuser", "groups", "user_permissions"} & set(
            form.changed_data,
        ):
            AuditLog.objects.create(
                actor=request.user, action="User permissions changed",
                affected_object=f"auth.User:{obj.pk}",
                summary="Administrative permissions updated",
            )


class RestrictedGroupAdmin(SuperuserChanges, GroupAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(
            actor=request.user, action="Group permissions changed",
            affected_object=f"auth.Group:{obj.pk}", summary="Group saved in admin",
        )


class RestrictedDeviceAdmin(SuperuserChanges, TOTPDeviceAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(
            actor=request.user, action="Staff MFA device changed",
            affected_object=f"otp_totp.TOTPDevice:{obj.pk}",
            summary="MFA device saved in admin",
        )


admin.site.unregister(User)
admin.site.register(User, AuditedUserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, RestrictedGroupAdmin)
admin.site.unregister(TOTPDevice)
admin.site.register(TOTPDevice, RestrictedDeviceAdmin)

admin.site.site_header = "University Contest Administration"
