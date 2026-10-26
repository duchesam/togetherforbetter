from django.core.management.base import BaseCommand
from django.utils import timezone
from opportunities.models import RequestBucket


class Command(BaseCommand):
    help = "Delete expired request-limit counters. Safe to run regularly."

    def handle(self, *args, **options):
        count, _ = RequestBucket.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f"Removed {count} expired request-limit counters.")
