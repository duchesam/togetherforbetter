from django.apps import AppConfig


class OpportunitiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "opportunities"

    def ready(self):
        from . import signals  # noqa: F401
