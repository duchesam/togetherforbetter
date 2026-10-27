"""Transactional account events and a durable, retryable email outbox."""
import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.crypto import constant_time_compare

from .models import Application, EmailDelivery, Notification, Profile

VERIFICATION_SALT = "together.account.email-verification"
MAX_DELIVERY_ATTEMPTS = 5
CLAIM_TIMEOUT = timedelta(minutes=10)


def email_fingerprint(email):
    return hashlib.sha256(email.strip().casefold().encode()).hexdigest()


def verification_token(profile, *, email=None, nonce=None):
    return signing.dumps({"user": profile.user_id, "email": email_fingerprint(email if email is not None else profile.user.email), "nonce": str(nonce if nonce is not None else profile.verification_nonce)}, salt=VERIFICATION_SALT)


def valid_verification_token(profile, token):
    try:
        payload = signing.loads(token, salt=VERIFICATION_SALT, max_age=settings.EMAIL_VERIFICATION_TIMEOUT)
        return (
            payload["user"] == profile.user_id
            and constant_time_compare(payload["email"], email_fingerprint(profile.user.email))
            and constant_time_compare(payload["nonce"], str(profile.verification_nonce))
        )
    except (signing.BadSignature, KeyError, TypeError):
        return False


def queue_verification(profile):
    with transaction.atomic():
        current = Profile.objects.select_for_update().select_related("user").get(pk=profile.pk)
        if current.is_email_verified:
            return None
        current.verification_nonce = uuid.uuid4()
        current.save(update_fields=["verification_nonce"])
        EmailDelivery.objects.filter(recipient=current.user, kind="verification", sent_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=timezone.now())
        return EmailDelivery.objects.create(
            recipient=current.user, recipient_email=current.user.email,
            kind="verification", verification_nonce=current.verification_nonce,
        )


def record_notification(application, recipient, kind, status_code=""):
    notification = Notification.objects.create(application=application, recipient=recipient, kind=kind, status_code=status_code)
    profile = Profile.objects.select_related("user").filter(user=recipient).first()
    if profile and profile.is_email_verified and profile.email_notifications:
        EmailDelivery.objects.create(recipient=recipient, recipient_email=recipient.email, kind="notification", notification=notification)
    return notification


def application_received(application):
    return record_notification(application, application.opportunity.employer.user, Notification.Kind.APPLICATION)


@transaction.atomic
def application_status_changed(application, actor=None):
    from .hiring import sync_after_status_change
    current = Application.objects.select_for_update().select_related("opportunity__employer__user", "applicant").get(pk=application.pk)
    sync_after_status_change(current, actor)
    return record_notification(current, current.applicant, Notification.Kind.STATUS, current.status)


def change_application_status(pk, actor, status):
    with transaction.atomic():
        application = Application.objects.select_for_update().select_related("opportunity__employer__user", "applicant").get(pk=pk)
        if application.opportunity.employer.user_id != actor.pk and not actor.has_perm("opportunities.change_application"):
            raise PermissionDenied
        # Callers validate the form; keep the service safe for other entry points.
        from .hiring import HiringConflict
        from django.utils.translation import gettext as _
        if application.status == Application.Status.WITHDRAWN or status == Application.Status.WITHDRAWN:
            raise HiringConflict(_("Withdrawn applications cannot be reopened or changed by an employer."))
        if status not in Application.Status.values:
            raise ValueError("Invalid application status")
        if application.status != status:
            application.status = status
            application.save(update_fields=["status", "updated_at"])
            application_status_changed(application, actor)
        return application


def pending_deliveries(now):
    return EmailDelivery.objects.filter(
        sent_at__isnull=True, cancelled_at__isnull=True, failed_at__isnull=True,
        available_at__lte=now,
    ).filter(Q(claimed_at__isnull=True) | Q(claimed_at__lt=now - CLAIM_TIMEOUT))


def delivery_allowed(delivery):
    if not delivery.recipient.is_active or delivery.recipient_email.strip().casefold() != delivery.recipient.email.strip().casefold():
        return False
    profile = Profile.objects.select_related("user").filter(user=delivery.recipient).first()
    if not profile:
        return False
    if delivery.kind == EmailDelivery.Kind.VERIFICATION:
        return bool(not profile.is_email_verified and profile.verification_nonce == delivery.verification_nonce)
    return bool(delivery.notification_id and profile.is_email_verified and profile.email_notifications)


def render_delivery(delivery):
    profile = Profile.objects.select_related("user").get(user=delivery.recipient)
    with translation.override(profile.preferred_language):
        context = {"site_url": settings.PUBLIC_SITE_URL}
        if delivery.kind == EmailDelivery.Kind.VERIFICATION:
            context["verification_url"] = settings.PUBLIC_SITE_URL + reverse("email_verify", args=[verification_token(profile, email=delivery.recipient_email, nonce=delivery.verification_nonce)])
            stem = "email_verification"
        else:
            context["notification"] = delivery.notification
            context["application_url"] = settings.PUBLIC_SITE_URL + reverse("application", args=[delivery.notification.application_id])
            stem = "notification_email"
        subject = " ".join(render_to_string(f"opportunities/{stem}_subject.txt", context).splitlines()).strip()
        body = render_to_string(f"opportunities/{stem}.txt", context)
    return EmailMessage(subject=subject, body=body, to=[delivery.recipient_email])


def deliver_one(pk):
    now = timezone.now()
    claim = uuid.uuid4()
    if not pending_deliveries(now).filter(pk=pk).update(claim_token=claim, claimed_at=now, attempts=F("attempts") + 1):
        return "skipped"
    delivery = EmailDelivery.objects.select_related("recipient", "notification__application__opportunity").filter(pk=pk, claim_token=claim).first()
    if not delivery:
        return "skipped"
    claimed = EmailDelivery.objects.filter(pk=pk, claim_token=claim)
    if delivery.attempts > MAX_DELIVERY_ATTEMPTS:
        claimed.update(failed_at=now, claim_token=None, claimed_at=None, last_error_type="RetryLimitReached")
        return "failed"
    if not delivery_allowed(delivery):
        claimed.update(cancelled_at=timezone.now(), claim_token=None, claimed_at=None)
        return "cancelled"
    try:
        if render_delivery(delivery).send(fail_silently=False) != 1:
            raise RuntimeError("Email backend did not accept the message")
    except Exception as error:
        # Keep credentials, recipient addresses, and token-bearing bodies out of logs.
        terminal = delivery.attempts >= MAX_DELIVERY_ATTEMPTS
        claimed.update(
            last_error_type=type(error).__name__[:100], claim_token=None, claimed_at=None,
            failed_at=timezone.now() if terminal else None,
            available_at=timezone.now() + timedelta(minutes=min(60, 2 ** (delivery.attempts - 1))),
        )
        return "failed" if terminal else "deferred"
    claimed.update(sent_at=timezone.now(), claim_token=None, claimed_at=None, last_error_type="")
    return "sent"
