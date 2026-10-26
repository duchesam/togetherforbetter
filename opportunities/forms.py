from django.utils.translation import gettext_lazy as _
from django import forms
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.db import transaction
from django.utils.crypto import constant_time_compare
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Profile, Employer, Opportunity, Application, OpportunityReport, Interview, PlacementReport
import uuid

class SignupForm(UserCreationForm):
    full_name = forms.CharField(max_length=150, label=_("Full name"))
    email = forms.EmailField(label=_("Email"))
    role = forms.ChoiceField(choices=Profile.Role.choices, label=_("Account type"))
    organization_name = forms.CharField(label=_("Organization name"), max_length=180, required=False, help_text=_("Required for employers. Our team reviews organizations before listings go live."))
    class Meta:
        model = User
        fields = ["full_name", "username", "email", "role", "organization_name", "password1", "password2"]
    def clean(self):
        data = super().clean()
        if data.get("role") == "employer" and not data.get("organization_name"):
            self.add_error("organization_name", _("Enter your organization’s name."))
        return data

class LocalizedModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.label:
                field.label = _(field.label)


class ProfileForm(LocalizedModelForm):
    remove_cv = forms.BooleanField(required=False, label=_("Remove my current CV"))

    class Meta:
        model = Profile
        fields = ["full_name", "location", "skills", "education", "bio", "cv"]
        widgets = {
            "education": forms.Textarea(attrs={"rows": 3}),
            "bio": forms.Textarea(attrs={"rows": 4}),
            "cv": forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.role != Profile.Role.SEEKER:
            self.fields.pop("cv")
            self.fields.pop("remove_cv")
        elif not self.instance.cv:
            self.fields.pop("remove_cv")

    def clean(self):
        data = super().clean()
        if data.get("remove_cv") and "cv" in self.files:
            self.add_error("cv", _("Choose either a replacement CV or removal, not both."))
        return data

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.cleaned_data.get("remove_cv"):
            profile.cv = ""
        if commit:
            changed = [name for name in self.changed_data if name in self.Meta.fields]
            if self.cleaned_data.get("remove_cv") and "cv" not in changed:
                changed.append("cv")
            if not profile.pk:
                profile.save()
            elif changed:
                profile.save(update_fields=changed)
            self.save_m2m()
        return profile

class EmployerForm(LocalizedModelForm):
    class Meta:
        model = Employer
        fields = ["name", "website", "description"]

class OpportunityForm(LocalizedModelForm):
    deadline = forms.DateField(
        label=_("Deadline (Gregorian calendar)"),
        help_text=_("Use the Gregorian calendar (GC). Deadlines close at the end of the day in Ethiopia."),
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )

    class Meta:
        model = Opportunity
        fields = ["title", "kind", "location", "category", "description", "requirements", "compensation", "deadline"]
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"}), "description": forms.Textarea(attrs={"rows": 5}), "requirements": forms.Textarea(attrs={"rows": 4})}
    def clean_deadline(self):
        value = self.cleaned_data["deadline"]
        if value < timezone.localdate():
            raise forms.ValidationError(_("Choose today or a future date."))
        return value

class ApplicationForm(LocalizedModelForm):
    class Meta:
        model = Application
        fields = ["cover_letter"]
        labels = {"cover_letter": _("Tell the employer why you’re a good fit")}
        widgets = {"cover_letter": forms.Textarea(attrs={"rows": 6, "placeholder": _("Share your interests, relevant skills, and what you hope to contribute.")})}

class StatusForm(LocalizedModelForm):
    class Meta:
        model = Application
        fields = ["status"]


class ReportForm(LocalizedModelForm):
    class Meta:
        model = OpportunityReport
        fields = ["reason", "details"]
        labels = {"reason": _("What is the concern?"), "details": _("Tell us what happened")}
        help_texts = {"details": _("Do not include passwords, bank details, or identity documents. Your report is visible only to you and authorized moderators.")}
        widgets = {"details": forms.Textarea(attrs={"rows": 5})}


class AccountPreferencesForm(LocalizedModelForm):
    class Meta:
        model = Profile
        fields = ["preferred_language", "email_notifications"]
        labels = {"preferred_language": _("Preferred language"), "email_notifications": _("Email me about applications and status changes")}
        help_texts = {"email_notifications": _("Application emails are sent only to a verified email address. In-app notifications remain available when email is turned off.")}

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save(update_fields=self.Meta.fields)
            self.save_m2m()
        return profile


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label=_("Current password"), strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    confirm = forms.BooleanField(label=_("I understand that deleting my account is permanent."))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        value = self.cleaned_data["password"]
        if not self.user.check_password(value):
            raise forms.ValidationError(_("Your password was incorrect. Your account has not been deleted."))
        return value


class LockedSetPasswordForm(SetPasswordForm):
    """Do not recreate a user deleted concurrently with password recovery."""
    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        with transaction.atomic():
            current = User.objects.select_for_update().filter(pk=self.user.pk, is_active=True).first()
            if (not current or not constant_time_compare(current.password, self.user.password)
                    or current.email != self.user.email or current.last_login != self.user.last_login):
                raise forms.ValidationError(_("This account or reset link is no longer available. Request a new reset link."))
            current.set_password(self.cleaned_data["new_password1"])
            current.save(update_fields=["password"])
            self.user = current
        return current


class InterviewForm(LocalizedModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    scheduled_at = forms.DateTimeField(
        label=_("Interview date and time"),
        help_text=_("Gregorian date and 24-hour clock, Addis Ababa time (UTC+3)."),
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )

    class Meta:
        model = Interview
        fields = ["scheduled_at", "duration_minutes", "mode", "location", "meeting_url", "details"]
        labels = {"duration_minutes": _("Duration in minutes"), "mode": _("Interview format"), "location": _("Interview location"), "meeting_url": _("HTTPS video meeting link"), "details": _("Interview instructions")}
        widgets = {"details": forms.Textarea(attrs={"rows": 4})}

    def _post_clean(self):
        # The same key can be resubmitted; the service checks its payload and owner.
        self.instance.request_key = self.cleaned_data.get("request_key", uuid.uuid4())
        super()._post_clean()

    def validate_unique(self):
        # Idempotency and cross-application key reuse are checked under an app lock.
        pass


class InterviewResponseForm(forms.Form):
    status = forms.ChoiceField(label=_("Your interview response"), choices=[("", _("Choose a response")), ("accepted", _("Accept interview")), ("declined", _("Decline interview")), ("reschedule", _("Request another time"))])
    note = forms.CharField(label=_("Message to the employer"), max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        data = super().clean()
        if data.get("status") == "reschedule" and not data.get("note", "").strip():
            self.add_error("note", _("Suggest another time in your message."))
        return data


class PlacementResponseForm(forms.Form):
    response = forms.ChoiceField(label=_("Your placement response"), widget=forms.RadioSelect, choices=[(PlacementReport.Response.CONFIRMED, _("I accepted this role")), (PlacementReport.Response.DISPUTED, _("I did not accept this role"))])
