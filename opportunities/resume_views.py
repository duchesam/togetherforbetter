from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET

from .models import Profile, ResumeDraft
from .resumes import ResumeAIError, generate_resume, resume_pdf

FIELDS = ['full_name', 'email', 'phone', 'location', 'target_role', 'language', 'summary', 'education', 'experience', 'skills']


class ResumeForm(forms.ModelForm):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    consent = forms.BooleanField(required=False, label=gettext_lazy("I agree to send the resume text below to OpenAI for AI drafting. Contact fields and uploaded CV files are excluded."))

    class Meta:
        model = ResumeDraft
        fields = FIELDS
        labels = {"full_name": gettext_lazy("Full name"), "email": gettext_lazy("Email"), "phone": gettext_lazy("Phone (optional)"), "location": gettext_lazy("Location"), "target_role": gettext_lazy("Target role"), "language": gettext_lazy("Resume language"), "summary": gettext_lazy("Professional summary"), "education": gettext_lazy("Education"), "experience": gettext_lazy("Experience and projects"), "skills": gettext_lazy("Skills")}
        widgets = {field: forms.Textarea(attrs={"rows": 4}) for field in ["summary", "education", "experience", "skills"]}


def seeker_profile(request):
    profile = get_object_or_404(Profile, user=request.user)
    if profile.role != Profile.Role.SEEKER:
        raise PermissionDenied
    return profile


class ResumeConflict(Exception):
    pass


@transaction.atomic
def save_draft(user, data, expected_version):
    # Serialize creation and edits without holding locks across the AI request.
    get_object_or_404(get_user_model().objects.select_for_update(), pk=user.pk)
    current = ResumeDraft.objects.select_for_update().filter(user=user).first()
    if (current.version if current else 0) != expected_version:
        raise ResumeConflict
    current = current or ResumeDraft(user=user, version=0)
    for field in FIELDS:
        setattr(current, field, data[field])
    current.version += 1
    current.full_clean()
    current.save()
    return current


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def resume_builder(request, generate=False):
    profile = seeker_profile(request)
    if generate and request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    draft = ResumeDraft.objects.filter(user=request.user).first()
    initial = {"expected_version": draft.version if draft else 0}
    if not draft:
        initial.update(full_name=profile.full_name, email=request.user.email, location=profile.location, education=profile.education[:4000], skills=profile.skills, summary=profile.bio[:2000], language=profile.preferred_language)
    form = ResumeForm(request.POST if request.method == "POST" else None, instance=draft, initial=initial)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = {field: form.cleaned_data[field] for field in FIELDS}
        if generate and not form.cleaned_data["consent"]:
            form.add_error("consent", _("Consent is required before sending text for AI drafting."))
        else:
            try:
                if (draft.version if draft else 0) != form.cleaned_data["expected_version"]:
                    raise ResumeConflict
                if generate:
                    data.update(generate_resume(data))
                save_draft(request.user, data, form.cleaned_data["expected_version"])
            except ResumeAIError as error:
                form.add_error(None, str(error))
            except ResumeConflict:
                form.add_error(None, _("Your saved resume changed in another tab. Copy your edits, reload, and try again."))
                status = 409
            else:
                messages.success(request, _("AI draft saved. Review every statement before using it.") if generate else _("Resume draft saved privately."))
                return redirect("resume_builder")
    return render(request, "opportunities/resume_builder.html", {"form": form, "draft": draft, "ai_available": bool(settings.OPENAI_API_KEY)}, status=status)


@login_required
@never_cache
@require_GET
def resume_download(request):
    seeker_profile(request)
    draft = get_object_or_404(ResumeDraft, user=request.user)
    response = HttpResponse(resume_pdf(draft), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="my-resume.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
