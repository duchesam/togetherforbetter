from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.db import models
from django.utils import timezone
from .uploads import cv_upload_path, validate_cv
import uuid

class Profile(models.Model):
    class Role(models.TextChoices):
        SEEKER = "seeker", _("Job seeker")
        EMPLOYER = "employer", _("Employer")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.SEEKER)
    full_name = models.CharField(max_length=150)
    location = models.CharField(max_length=100, blank=True)
    skills = models.CharField(max_length=300, blank=True)
    education = models.TextField(blank=True)
    bio = models.TextField(blank=True)
    preferred_language = models.CharField(max_length=5, choices=settings.LANGUAGES, default="en")
    email_notifications = models.BooleanField(default=True)
    email_verification_required = models.BooleanField(default=False)
    verified_email = models.EmailField(blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    verification_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    cv = models.FileField(
        upload_to=cv_upload_path, validators=[validate_cv], blank=True,
        help_text=_("Optional PDF, up to 5 MB. Shared with employers only when you apply. Do not include identity documents or sensitive personal details."),
    )
    def __str__(self):
        return self.full_name

    @property
    def is_email_verified(self):
        return bool(self.email_verified_at and self.verified_email and self.verified_email.casefold() == self.user.email.strip().casefold())

    @property
    def needs_email_verification(self):
        return self.email_verification_required and not self.is_email_verified

class Employer(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employer")
    name = models.CharField(max_length=180)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_demo = models.BooleanField(default=False)
    verified = models.BooleanField(default=False, help_text=_("Verify the organization independently before approving."))
    def __str__(self):
        return self.name

class Opportunity(models.Model):
    class Kind(models.TextChoices):
        INTERNSHIP = "internship", _("Internship")
        ENTRY = "entry", _("Entry-level job")
        VOLUNTEER = "volunteer", _("Volunteer")
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name="opportunities")
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    location = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    description = models.TextField()
    requirements = models.TextField()
    compensation = models.CharField(max_length=150, help_text=_("State pay, stipend, or unpaid clearly."))
    deadline = models.DateField()
    published = models.BooleanField(default=False, help_text=_("Publish only after reviewing this listing."))
    closed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
    @property
    def is_expired(self):
        return self.deadline < timezone.localdate()

    @property
    def is_open(self):
        return self.closed_at is None and self.published and self.employer.verified and self.deadline >= timezone.localdate()
    def __str__(self):
        return self.title

class Application(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Submitted")
        REVIEWING = "reviewing", _("Under review")
        SHORTLISTED = "shortlisted", _("Shortlisted")
        HIRED = "hired", _("Hired (employer reported)")
        DECLINED = "declined", _("Not selected")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications")
    cover_letter = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["opportunity", "applicant"], name="one_application_per_opportunity")]
    def __str__(self):
        return f"{self.applicant} — {self.opportunity}"


class OpportunityReport(models.Model):
    class Reason(models.TextChoices):
        FEE = "fee", _("Asked to pay a fee")
        MISLEADING = "misleading", _("Misleading or suspicious listing")
        HARASSMENT = "harassment", _("Harassment or discrimination")
        OTHER = "other", _("Another concern")

    class Status(models.TextChoices):
        OPEN = "open", _("Received")
        INVESTIGATING = "investigating", _("Under review")
        RESOLVED = "resolved", _("Resolved")
        DISMISSED = "dismissed", _("Closed without action")

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="opportunity_reports")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=16, choices=Reason.choices)
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    moderator_notes = models.TextField(blank=True, help_text=_("Internal notes. Never shown to the reporting user or employer."))
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_reports")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["reporter", "opportunity"], name="one_report_per_user_and_opportunity")]

    def __str__(self):
        return f"Report #{self.pk}: {self.opportunity}"


class RequestBucket(models.Model):
    key = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class Notification(models.Model):
    class Kind(models.TextChoices):
        APPLICATION = "application", _("New application received")
        STATUS = "status", _("Application status changed")
        INTERVIEW = "interview", _("Interview update")
        PLACEMENT = "placement", _("Placement response updated")

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status_code = models.CharField(max_length=16, choices=Application.Status.choices, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    interview = models.ForeignKey("Interview", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    placement_report = models.ForeignKey("PlacementReport", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")

    class Meta:
        ordering = ["-created_at", "-pk"]

    @property
    def status_label(self):
        return Application.Status(self.status_code).label if self.status_code else ""


class EmailDelivery(models.Model):
    class Kind(models.TextChoices):
        VERIFICATION = "verification", "Email verification"
        NOTIFICATION = "notification", "Account notification"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_deliveries")
    recipient_email = models.EmailField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    notification = models.OneToOneField(Notification, null=True, blank=True, on_delete=models.CASCADE, related_name="email_delivery")
    verification_nonce = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]


class PrivateFileCleanup(models.Model):
    name = models.CharField(max_length=500, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error_type = models.CharField(max_length=100, blank=True)


class Interview(models.Model):
    class Mode(models.TextChoices):
        IN_PERSON = "in_person", _("In person")
        VIDEO = "video", _("Video call")
        PHONE = "phone", _("Phone call")

    class Status(models.TextChoices):
        PENDING = "pending", _("Awaiting applicant response")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        RESCHEDULE = "reschedule", _("Another time requested")
        CANCELLED = "cancelled", _("Cancelled")
        REPLACED = "replaced", _("Replaced by a newer invitation")

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="interviews")
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(choices=[(15, "15"), (30, "30"), (45, "45"), (60, "60"), (90, "90"), (120, "120")], default=30)
    mode = models.CharField(max_length=12, choices=Mode.choices)
    location = models.CharField(max_length=240, blank=True)
    meeting_url = models.URLField(blank=True)
    details = models.TextField(max_length=1500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    response_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["application"], condition=models.Q(status__in=["pending", "accepted", "reschedule"]), name="one_active_interview_per_application")]

    @property
    def is_active(self):
        return self.status in [self.Status.PENDING, self.Status.ACCEPTED, self.Status.RESCHEDULE]

    def clean(self):
        from django.core.exceptions import ValidationError
        from urllib.parse import urlsplit
        errors = {}
        if self.scheduled_at and (timezone.is_naive(self.scheduled_at) or self.scheduled_at <= timezone.now()):
            errors["scheduled_at"] = _("Choose a future interview time.")
        if self.mode == self.Mode.IN_PERSON and not self.location.strip():
            errors["location"] = _("Enter the interview location.")
        if self.mode == self.Mode.PHONE and not self.details.strip():
            errors["details"] = _("Explain how the phone interview will take place.")
        if self.mode == self.Mode.VIDEO:
            try:
                url = urlsplit(self.meeting_url)
                valid = url.scheme == "https" and url.hostname and not url.username and not url.password
            except ValueError:
                valid = False
            if not valid:
                errors["meeting_url"] = _("Enter an HTTPS meeting link without embedded credentials.")
        elif self.meeting_url:
            errors["meeting_url"] = _("Meeting links are only used for video interviews.")
        if errors:
            raise ValidationError(errors)


class InterviewEvent(models.Model):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Interview.Status.choices)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class PlacementReport(models.Model):
    class Response(models.TextChoices):
        PENDING = "pending", _("Awaiting applicant confirmation")
        CONFIRMED = "confirmed", _("Applicant confirmed acceptance")
        DISPUTED = "disputed", _("Applicant did not confirm acceptance")

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="placement_reports")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reported_at = models.DateTimeField(default=timezone.now)
    response = models.CharField(max_length=12, choices=Response.choices, default=Response.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-reported_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["application"], condition=models.Q(superseded_at__isnull=True), name="one_current_placement_report"),
            models.CheckConstraint(condition=(models.Q(response="pending", responded_at__isnull=True) | models.Q(response__in=["confirmed", "disputed"], responded_at__isnull=False)), name="placement_response_has_timestamp"),
        ]


class PlacementResponseEvent(models.Model):
    report = models.ForeignKey(PlacementReport, on_delete=models.CASCADE, related_name="events")
    response = models.CharField(max_length=12, choices=PlacementReport.Response.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class OpportunityChange(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="changes")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=12, choices=[("edited", _("Edited")), ("closed", _("Closed")), ("reopened", _("Reopened for review"))])
    fields_changed = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class SavedOpportunity(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_opportunities")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="saves")
    title = models.CharField(max_length=180)
    employer_name = models.CharField(max_length=180)
    location = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["user", "opportunity"], name="one_saved_opportunity_per_user")]

    @property
    def is_available(self):
        return self.opportunity.is_open and (settings.DEBUG or not self.opportunity.employer.is_demo)
