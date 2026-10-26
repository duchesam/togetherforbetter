"""Retry private-document removal without losing the deletion request."""
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db.models import F
from django.utils import timezone

from .models import PrivateFileCleanup, Profile


def remove_private_file(pk, storage=None):
    task = PrivateFileCleanup.objects.filter(pk=pk, failed_at__isnull=True).first()
    if not task:
        return "skipped"
    # Never remove a document that a live profile still references.
    if Profile.objects.filter(cv=task.name).exists():
        PrivateFileCleanup.objects.filter(pk=pk).delete()
        return "in_use"
    try:
        (storage or default_storage).delete(task.name)
    except Exception as error:
        terminal = task.attempts + 1 >= 5
        PrivateFileCleanup.objects.filter(pk=pk).update(
            attempts=F("attempts") + 1,
            available_at=timezone.now() + timedelta(minutes=min(60, 2 ** task.attempts)),
            failed_at=timezone.now() if terminal else None,
            last_error_type=type(error).__name__[:100],
        )
        return "failed" if terminal else "deferred"
    PrivateFileCleanup.objects.filter(pk=pk).delete()
    return "removed"


def cleanup_pending_files(limit=100):
    keys = list(PrivateFileCleanup.objects.filter(available_at__lte=timezone.now(), failed_at__isnull=True).values_list("pk", flat=True)[:limit])
    return [remove_private_file(pk) for pk in keys]
