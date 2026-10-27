"""Private, paginated application tracking for job seekers."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Application, Interview, Profile


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
    upcoming = Interview.objects.filter(application_id=OuterRef("pk"), scheduled_at__gt=timezone.now(), status__in=["pending", "accepted", "reschedule"], application__status__in=["submitted", "reviewing", "shortlisted"]).order_by("scheduled_at", "pk")
    applications = applications.select_related("opportunity__employer").annotate(
        interview_at=Subquery(upcoming.values("scheduled_at")[:1]),
        interview_status=Subquery(upcoming.values("status")[:1]),
    )
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
