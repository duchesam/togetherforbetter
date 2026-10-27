"""Private, paginated application tracking for job seekers."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Application, Employer, Interview, Opportunity, Profile


class TrackerFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=100, label=_("Search your applications"))
    status = forms.ChoiceField(required=False, choices=[("", _("All statuses")), *Application.Status.choices], label=_("Application status"))
    upcoming = forms.BooleanField(required=False, label=_("Only applications with upcoming interviews"))


@login_required
@require_GET
@never_cache
def application_tracker(request):
    if not Profile.objects.filter(user=request.user, role=Profile.Role.SEEKER).exists():
        raise PermissionDenied
    applications = Application.objects.filter(applicant=request.user)
    counts = dict(applications.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    form = TrackerFilterForm(request.GET)
    context = {"form": form, "total": sum(counts.values()), "counts": [(label, counts.get(value, 0)) for value, label in Application.Status.choices]}
    if not form.is_valid():
        return render(request, "opportunities/application_tracker.html", context, status=400)
    applications = with_upcoming_interview(applications)
    query = form.cleaned_data["q"]
    status = form.cleaned_data["status"]
    if query:
        applications = applications.filter(Q(opportunity__title__icontains=query) | Q(opportunity__employer__name__icontains=query))
    if status:
        applications = applications.filter(status=status)
    if form.cleaned_data["upcoming"]:
        applications = applications.filter(interview_at__isnull=False).order_by("interview_at", "pk")
    else:
        applications = applications.order_by("-created_at", "-pk")
    page = Paginator(applications, 12).get_page(request.GET.get("page"))
    for application in page:
        application.interview_label = Interview.Status(application.interview_status).label if application.interview_status else ""
    params = request.GET.copy()
    params.pop("page", None)
    context.update(page=page, filters=params.urlencode())
    return render(request, "opportunities/application_tracker.html", context)


def with_upcoming_interview(applications):
    upcoming = Interview.objects.filter(application_id=OuterRef("pk"), scheduled_at__gt=timezone.now(), status__in=["pending", "accepted", "reschedule"], application__status__in=["submitted", "reviewing", "shortlisted"]).order_by("scheduled_at", "pk")
    return applications.select_related("opportunity__employer").annotate(
        interview_at=Subquery(upcoming.values("scheduled_at")[:1]),
        interview_status=Subquery(upcoming.values("status")[:1]),
    )


class ApplicantFilterForm(TrackerFilterForm):
    q = forms.CharField(required=False, max_length=100, label=_("Search applicants or listing titles"))
    listing = forms.ModelChoiceField(required=False, queryset=Opportunity.objects.none(), empty_label=_("All your listings"), label=_("Listing"))

    def __init__(self, *args, employer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["listing"].queryset = employer.opportunities.order_by("title", "pk")


@login_required
@require_GET
@never_cache
def employer_applicants(request):
    if not Profile.objects.filter(user=request.user, role=Profile.Role.EMPLOYER).exists():
        raise PermissionDenied
    employer = get_object_or_404(Employer, user=request.user)
    applications = Application.objects.filter(opportunity__employer=employer)
    counts = dict(applications.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    form = ApplicantFilterForm(request.GET, employer=employer)
    context = {"form": form, "employer_workspace": True, "employer": employer, "total": sum(counts.values()), "counts": [(label, counts.get(value, 0)) for value, label in Application.Status.choices]}
    if not form.is_valid():
        return render(request, "opportunities/application_tracker.html", context, status=400)
    applications = with_upcoming_interview(applications).select_related("applicant__profile")
    query = form.cleaned_data["q"]
    if query:
        applications = applications.filter(Q(applicant__profile__full_name__icontains=query) | Q(applicant__username__icontains=query) | Q(opportunity__title__icontains=query))
    if form.cleaned_data["status"]:
        applications = applications.filter(status=form.cleaned_data["status"])
    if form.cleaned_data["listing"]:
        applications = applications.filter(opportunity=form.cleaned_data["listing"])
    if form.cleaned_data["upcoming"]:
        applications = applications.filter(interview_at__isnull=False).order_by("interview_at", "pk")
    else:
        applications = applications.order_by("-created_at", "-pk")
    page = Paginator(applications, 12).get_page(request.GET.get("page"))
    for application in page:
        application.interview_label = Interview.Status(application.interview_status).label if application.interview_status else ""
    params = request.GET.copy()
    params.pop("page", None)
    context.update(page=page, filters=params.urlencode())
    return render(request, "opportunities/application_tracker.html", context)
