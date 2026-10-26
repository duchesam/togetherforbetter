"""Remove obsolete private files only after their database change commits."""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Profile, PrivateFileCleanup
from .file_cleanup import remove_private_file


def delete_after_commit(storage, name):
    if name:
        task, created = PrivateFileCleanup.objects.get_or_create(name=name)
        transaction.on_commit(lambda: remove_private_file(task.pk, storage), robust=True)


@receiver(pre_save, sender=Profile)
def remember_old_cv(sender, instance, **kwargs):
    fields = kwargs.get("update_fields")
    if fields is not None and "cv" not in fields:
        instance._old_cv_name = None
        return
    instance._old_cv_name = (
        sender.objects.filter(pk=instance.pk).values_list("cv", flat=True).first()
        if instance.pk else None
    )


@receiver(post_save, sender=Profile)
def remove_replaced_cv(sender, instance, **kwargs):
    old_name = getattr(instance, "_old_cv_name", None)
    if old_name and old_name != instance.cv.name:
        delete_after_commit(instance.cv.storage, old_name)


@receiver(post_delete, sender=Profile)
def remove_deleted_cv(sender, instance, **kwargs):
    delete_after_commit(instance.cv.storage, instance.cv.name)
