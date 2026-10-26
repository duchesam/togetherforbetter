from django.utils.translation import gettext_lazy as _
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import Profile, Employer, Opportunity, Application, OpportunityReport, EmailDelivery, Interview, InterviewEvent, PlacementReport, PlacementResponseEvent
from .notifications import application_received, application_status_changed
admin.site.site_header = _("Together for Better · Community administration")
admin.site.site_title = _("Together for Better")
@admin.register(Employer)
class EmployerAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "website", "verified"]
    list_filter = ["verified"]
    search_fields = ["name", "user__email"]
@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ["title", "employer", "kind", "deadline", "published"]
    list_filter = ["published", "kind", "employer__verified"]
    search_fields = ["title", "employer__name"]
@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["applicant", "opportunity", "status", "created_at"]
    list_filter = ["status", "opportunity__kind"]
    search_fields = ["applicant__username", "opportunity__title"]
    readonly_fields = ["created_at", "updated_at"]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (["applicant", "opportunity", "cover_letter"] if obj else [])

    def save_model(self, request, obj, form, change):
        previous = Application.objects.select_for_update().filter(pk=obj.pk).values_list("status", flat=True).first() if obj.pk else None
        super().save_model(request, obj, form, change)
        if not change:
            application_received(obj)
            if obj.status == "hired":
                application_status_changed(obj, request.user)
        elif previous != obj.status:
            application_status_changed(obj, request.user)
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["full_name", "user", "role"]
    search_fields = ["full_name", "user__email"]
    exclude = ["cv"]
    readonly_fields = ["private_cv", "verified_email", "email_verified_at"]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (["user"] if obj else [])

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
        elif form.changed_data:
            obj.save(update_fields=form.changed_data)

    @admin.display(description=_("Private CV"))
    def private_cv(self, obj):
        if obj and obj.cv:
            return format_html('<a href="{}">Download CV (PDF)</a>', reverse("download_cv", args=[obj.pk]))
        return _("No CV uploaded")


@admin.register(OpportunityReport)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "reason", "status", "created_at", "reviewed_by"]
    list_filter = ["status", "reason"]
    search_fields = ["opportunity__title", "details"]
    readonly_fields = ["reporter", "opportunity", "reason", "details", "created_at", "reviewed_by", "reviewed_at"]
    actions = ["hide_reported_listings"]

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data or "moderator_notes" in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Hide reported listings and begin review"), permissions=["change"])
    def hide_reported_listings(self, request, queryset):
        if not request.user.has_perm("opportunities.change_opportunity"):
            raise PermissionDenied
        from django.db import transaction
        with transaction.atomic():
            for report in queryset.select_related("opportunity"):
                job = report.opportunity
                if job.published:
                    job.published = False
                    job.save(update_fields=["published"])
                    self.log_change(request, job, "Listing hidden during report review.")
                report.status = OpportunityReport.Status.INVESTIGATING
                report.reviewed_by = request.user
                report.reviewed_at = timezone.now()
                report.save(update_fields=["status", "reviewed_by", "reviewed_at"])
                self.log_change(request, report, "Reported listing hidden and review started.")
        self.message_user(request, _("Selected listings are hidden and reports are under review."))


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "recipient", "attempts", "created_at", "sent_at", "failed_at", "cancelled_at", "last_error_type"]
    list_filter = ["kind", "sent_at", "failed_at", "cancelled_at"]
    fields = ["kind", "recipient", "attempts", "available_at", "sent_at", "failed_at", "cancelled_at", "last_error_type", "created_at"]
    readonly_fields = fields
    actions = ["retry_failed"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description=_("Retry failed account emails"), permissions=["change"])
    def retry_failed(self, request, queryset):
        from django.db import transaction
        with transaction.atomic():
            for delivery in queryset.filter(failed_at__isnull=False, sent_at__isnull=True, cancelled_at__isnull=True):
                delivery.failed_at = None
                delivery.attempts = 0
                delivery.available_at = timezone.now()
                delivery.claimed_at = None
                delivery.claim_token = None
                delivery.last_error_type = ""
                delivery.save(update_fields=["failed_at", "attempts", "available_at", "claimed_at", "claim_token", "last_error_type"])
                self.log_change(request, delivery, "Failed account email returned to the delivery queue.")
        self.message_user(request, _("Failed account emails were returned to the delivery queue."))


class ReadOnlyHiringAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class InterviewEventInline(admin.TabularInline):
    model = InterviewEvent
    extra = 0
    can_delete = False
    readonly_fields = ["actor", "status", "note", "created_at"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PlacementResponseInline(InterviewEventInline):
    model = PlacementResponseEvent
    readonly_fields = ["response", "created_at"]


@admin.register(Interview)
class InterviewAdmin(ReadOnlyHiringAdmin):
    list_display = ["application", "scheduled_at", "mode", "status"]
    list_filter = ["status", "mode"]
    inlines = [InterviewEventInline]


@admin.register(PlacementReport)
class PlacementAdmin(ReadOnlyHiringAdmin):
    list_display = ["application", "response", "reported_at", "responded_at", "superseded_at"]
    list_filter = ["response", "superseded_at"]
    inlines = [PlacementResponseInline]
