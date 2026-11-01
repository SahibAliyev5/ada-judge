from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

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
    list_display = ["title", "starts_at", "ends_at", "status"]
    list_filter = ["status"]
    prepopulated_fields = {"slug": ["title"]}
    readonly_fields = ["created_by", "verified_digest"]

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
    actions = None

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


class AuditedUserAdmin(UserAdmin):
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


admin.site.unregister(User)
admin.site.register(User, AuditedUserAdmin)
admin.site.site_header = "University Contest Administration"
