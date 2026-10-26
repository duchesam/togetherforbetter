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
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
    @property
    def is_open(self):
        return self.published and self.employer.verified and self.deadline >= timezone.localdate()
    def __str__(self):
        return self.title

class Application(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Submitted")
        REVIEWING = "reviewing", _("Under review")
        SHORTLISTED = "shortlisted", _("Shortlisted")
        HIRED = "hired", _("Placement confirmed")
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

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status_code = models.CharField(max_length=16, choices=Application.Status.choices, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

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
