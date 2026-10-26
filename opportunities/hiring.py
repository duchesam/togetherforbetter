"""Hiring actions are serialized on their application and recorded transactionally."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Application, EmailDelivery, Interview, InterviewEvent, Notification, PlacementReport, PlacementResponseEvent
from .notifications import record_notification


class HiringConflict(Exception):
    pass


def locked_application(pk):
    return Application.objects.select_for_update().select_related("opportunity__employer__user", "applicant").get(pk=pk)


def notify_interview(interview, recipient):
    notice = record_notification(interview.application, recipient, Notification.Kind.INTERVIEW)
    notice.interview = interview
    notice.save(update_fields=["interview"])


def end_interview(interview, actor, status):
    if not interview.is_active:
        return False
    EmailDelivery.objects.filter(notification__interview=interview, sent_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=timezone.now())
    interview.status = status
    interview.save(update_fields=["status", "updated_at"])
    InterviewEvent.objects.create(interview=interview, actor=actor, status=status)
    notify_interview(interview, interview.application.applicant)
    return True


@transaction.atomic
def invite_to_interview(application_id, actor, data):
    application = locked_application(application_id)
    if application.opportunity.employer.user_id != actor.pk:
        raise PermissionDenied
    existing = Interview.objects.filter(request_key=data["request_key"]).first()
    fields = ["scheduled_at", "duration_minutes", "mode", "location", "meeting_url", "details"]
    if existing:
        if existing.application_id != application.pk or any(getattr(existing, field) != data.get(field, "") for field in fields):
            raise HiringConflict(_("This invitation was already submitted with different details. Reload the page."))
        return existing
    if application.status in [Application.Status.HIRED, Application.Status.DECLINED]:
        raise HiringConflict(_("This application is closed to interview scheduling."))
    # Validation happens before any existing invitation is changed.
    interview = Interview(application=application, **{field: data.get(field, "") for field in fields}, request_key=data["request_key"])
    interview.full_clean(validate_constraints=False)
    for previous in application.interviews.filter(status__in=["pending", "accepted", "reschedule"]):
        end_interview(previous, actor, Interview.Status.REPLACED)
    interview.save()
    InterviewEvent.objects.create(interview=interview, actor=actor, status=Interview.Status.PENDING)
    notify_interview(interview, application.applicant)
    return interview


@transaction.atomic
def respond_to_interview(pk, actor, status, note=""):
    application_id = Interview.objects.values_list("application_id", flat=True).get(pk=pk)
    application = locked_application(application_id)
    if application.applicant_id != actor.pk:
        raise PermissionDenied
    interview = Interview.objects.select_for_update().get(pk=pk)
    latest_pk = application.interviews.order_by("-pk").values_list("pk", flat=True).first()
    if (interview.pk != latest_pk or interview.status in ["cancelled", "replaced"]
            or interview.scheduled_at <= timezone.now() or application.status in ["hired", "declined"]):
        raise HiringConflict(_("This invitation is no longer available for a response."))
    if status not in ["accepted", "declined", "reschedule"] or len(note) > 500:
        raise ValidationError(_("Choose a valid interview response."))
    if status == "reschedule" and not note.strip():
        raise ValidationError(_("Suggest another time in your message."))
    if interview.status != status or interview.response_note != note:
        interview.status = status
        interview.response_note = note
        interview.save(update_fields=["status", "response_note", "updated_at"])
        InterviewEvent.objects.create(interview=interview, actor=actor, status=status, note=note)
        notify_interview(interview, application.opportunity.employer.user)
    return interview


@transaction.atomic
def cancel_interview(pk, actor):
    application_id = Interview.objects.values_list("application_id", flat=True).get(pk=pk)
    application = locked_application(application_id)
    if application.opportunity.employer.user_id != actor.pk:
        raise PermissionDenied
    interview = Interview.objects.select_for_update().get(pk=pk)
    end_interview(interview, actor, Interview.Status.CANCELLED)
    return interview


def sync_after_status_change(application, actor=None):
    if application.status == Application.Status.HIRED:
        PlacementReport.objects.get_or_create(application=application, superseded_at__isnull=True, defaults={"reported_by": actor or application.opportunity.employer.user})
    else:
        PlacementReport.objects.filter(application=application, superseded_at__isnull=True).update(superseded_at=timezone.now())
    if application.status in [Application.Status.HIRED, Application.Status.DECLINED]:
        for interview in application.interviews.filter(status__in=["pending", "accepted", "reschedule"]):
            end_interview(interview, actor or application.opportunity.employer.user, Interview.Status.CANCELLED)


@transaction.atomic
def respond_to_placement(pk, actor, response):
    application_id = PlacementReport.objects.values_list("application_id", flat=True).get(pk=pk)
    application = locked_application(application_id)
    if application.applicant_id != actor.pk:
        raise PermissionDenied
    report = PlacementReport.objects.select_for_update().get(pk=pk)
    if report.superseded_at or application.status != Application.Status.HIRED:
        raise HiringConflict(_("This placement report is no longer current."))
    if response not in [PlacementReport.Response.CONFIRMED, PlacementReport.Response.DISPUTED]:
        raise ValidationError(_("Choose a valid placement response."))
    if report.response != response:
        report.response = response
        report.responded_at = timezone.now()
        report.save(update_fields=["response", "responded_at"])
        PlacementResponseEvent.objects.create(report=report, response=response)
        notice = record_notification(application, application.opportunity.employer.user, Notification.Kind.PLACEMENT)
        notice.placement_report = report
        notice.save(update_fields=["placement_report"])
    return report
