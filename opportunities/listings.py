"""Employer-owned listing changes; publication always remains a moderation action."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Opportunity, OpportunityChange

EDIT_FIELDS = ["title", "kind", "location", "category", "description", "requirements", "compensation", "deadline"]


class ListingConflict(Exception):
    pass


@transaction.atomic
def change_listing(pk, actor, action, expected_version, data=None):
    job = Opportunity.objects.select_for_update().select_related("employer").get(pk=pk)
    if job.employer.user_id != actor.pk:
        raise PermissionDenied
    if action not in ["edited", "closed", "reopened"]:
        raise ValidationError(_("Choose a valid listing action."))
    if action == "closed" and job.closed_at is not None:
        return job
    if action == "reopened" and job.closed_at is None:
        return job
    if job.version != expected_version:
        raise ListingConflict(_("This listing changed while you were working. Reload it before submitting again."))
    if action != "closed" and actor.profile.needs_email_verification:
        raise ValidationError(_("Verify your email address before editing or reopening a listing."))
    changed = []
    if action == "edited":
        for field in EDIT_FIELDS:
            if getattr(job, field) != data[field]:
                setattr(job, field, data[field])
                changed.append(field)
        if not changed:
            return job
        if job.deadline < timezone.localdate():
            raise ValidationError(_("Choose today or a future date."))
        job.full_clean()
    elif action == "closed":
        job.closed_at = timezone.now()
        changed = ["closed_at"]
    else:
        if job.deadline < timezone.localdate():
            raise ValidationError(_("Update the expired deadline before reopening this listing."))
        job.closed_at = None
        changed = ["closed_at"]
    job.published = False
    job.version += 1
    job.save(update_fields=changed + ["published", "version"])
    OpportunityChange.objects.create(opportunity=job, actor=actor, action=action, fields_changed=changed)
    return job
