from datetime import timedelta, timezone as utc_timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import InterviewForm, InterviewResponseForm, PlacementResponseForm, WithdrawalForm
from .hiring import HiringConflict, invite_to_interview, respond_to_interview, cancel_interview, respond_to_placement, withdraw_application
from .models import Application, Interview, PlacementReport


def conflict(request, application_id, error):
    return render(request, "opportunities/hiring_conflict.html", {"application_id": application_id, "reason": str(error)}, status=409)


@login_required
@never_cache
def interview_invite(request, pk):
    application = get_object_or_404(Application.objects.select_related("opportunity__employer"), pk=pk)
    if application.opportunity.employer.user_id != request.user.pk:
        raise PermissionDenied
    form = InterviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invite_to_interview(pk, request.user, form.cleaned_data)
        except HiringConflict as error:
            return conflict(request, pk, error)
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, _("Interview invitation recorded. The applicant has been notified."))
            return redirect("application", pk=pk)
    return render(request, "opportunities/form.html", {"form": form, "title": _("Invite to an interview"), "subtitle": _("Use Gregorian dates and Addis Ababa time (UTC+3). A new invitation replaces any active invitation for this application."), "button": _("Send interview invitation")})


@login_required
@require_POST
def interview_response(request, pk):
    interview = get_object_or_404(Interview.objects.select_related("application"), pk=pk)
    if interview.application.applicant_id != request.user.pk:
        raise PermissionDenied
    form = InterviewResponseForm(request.POST)
    if form.is_valid():
        try:
            respond_to_interview(pk, request.user, form.cleaned_data["status"], form.cleaned_data["note"])
        except HiringConflict as error:
            return conflict(request, interview.application_id, error)
        else:
            messages.success(request, _("Your interview response has been saved."))
            return redirect("application", pk=interview.application_id)
    return render(request, "opportunities/form.html", {"form": form, "title": _("Respond to the interview"), "button": _("Save response")}, status=400)


@login_required
@require_POST
def interview_cancel(request, pk):
    interview = get_object_or_404(Interview, pk=pk)
    cancel_interview(pk, request.user)
    messages.success(request, _("The active interview has been cancelled."))
    return redirect("application", pk=interview.application_id)


@login_required
@require_POST
def placement_response(request, pk):
    report = get_object_or_404(PlacementReport.objects.select_related("application"), pk=pk)
    if report.application.applicant_id != request.user.pk:
        raise PermissionDenied
    form = PlacementResponseForm(request.POST)
    if form.is_valid():
        try:
            respond_to_placement(pk, request.user, form.cleaned_data["response"])
        except HiringConflict as error:
            return conflict(request, report.application_id, error)
        else:
            messages.success(request, _("Your placement response has been recorded."))
            return redirect("application", pk=report.application_id)
    return render(request, "opportunities/form.html", {"form": form, "title": _("Confirm your placement outcome"), "button": _("Save response")}, status=400)


def calendar_text(value):
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_calendar_line(line):
    parts, current = [], ""
    for character in line:
        if len((current + character).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += character
    return "\r\n".join(parts + [current])


@login_required
@never_cache
def interview_calendar(request, pk):
    interview = get_object_or_404(Interview.objects.select_related("application__opportunity__employer"), pk=pk)
    application = interview.application
    if request.user.pk not in [application.applicant_id, application.opportunity.employer.user_id] and not request.user.has_perm("opportunities.view_interview"):
        raise PermissionDenied
    stamp = lambda value: value.astimezone(utc_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    status = "CANCELLED" if interview.status in ["cancelled", "replaced"] else "CONFIRMED" if interview.status == "accepted" else "TENTATIVE"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Together for Better//Interview//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
             f"UID:{interview.request_key}@togetherforbetter", f"DTSTAMP:{stamp(timezone.now())}", f"DTSTART:{stamp(interview.scheduled_at)}",
             f"DTEND:{stamp(interview.scheduled_at + timedelta(minutes=interview.duration_minutes))}",
             "SUMMARY:" + calendar_text(application.opportunity.title + " · " + str(_("Interview"))),
             "LOCATION:" + calendar_text(interview.location or interview.get_mode_display()),
             "DESCRIPTION:" + calendar_text(interview.details + ("\n" + interview.meeting_url if interview.meeting_url else "")), f"STATUS:{status}", "END:VEVENT", "END:VCALENDAR"]
    response = HttpResponse("\r\n".join(fold_calendar_line(line) for line in lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="interview.ics"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@never_cache
def application_withdraw(request, pk):
    application = get_object_or_404(Application, pk=pk, applicant=request.user)
    if application.status == "withdrawn":
        return redirect("application", pk=pk)
    if application.status in ["hired", "declined"]:
        return conflict(request, pk, _("This application changed or is already closed. Reload before continuing."))
    form = WithdrawalForm(request.POST if request.method == "POST" else None, initial={"expected_status": application.status})
    if request.method == "POST" and form.is_valid():
        try:
            withdraw_application(pk, request.user, form.cleaned_data["expected_status"])
        except HiringConflict as error:
            return conflict(request, pk, error)
        messages.success(request, _("Your application has been withdrawn. The employer has been notified."))
        return redirect("application", pk=pk)
    return render(request, "opportunities/form.html", {"form": form, "title": _("Withdraw application"), "subtitle": _("Withdrawal cancels active interviews and closes this application permanently. You cannot apply again to this opportunity. The employer retains your application and access to your current profile and CV. Already downloaded calendar entries must be removed manually."), "button": _("Confirm withdrawal")})
