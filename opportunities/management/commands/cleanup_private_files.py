from collections import Counter
from django.core.management.base import BaseCommand
from opportunities.file_cleanup import cleanup_pending_files
from opportunities.models import PrivateFileCleanup
from django.utils import timezone


class Command(BaseCommand):
    help = "Retry pending private document removals without printing filenames."

    def add_arguments(self, parser):
        parser.add_argument("--retry-failed", action="store_true", help="Requeue failed deletions after fixing the storage problem.")

    def handle(self, *args, **options):
        if options["retry_failed"]:
            PrivateFileCleanup.objects.filter(failed_at__isnull=False).update(failed_at=None, attempts=0, available_at=timezone.now(), last_error_type="")
        totals = Counter(cleanup_pending_files())
        self.stdout.write("Private document cleanup: " + ", ".join(f"{key}={value}" for key, value in sorted(totals.items())) if totals else "Private document cleanup: no eligible files.")
