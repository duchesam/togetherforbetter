import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from opportunities.notifications import deliver_one, pending_deliveries
from opportunities.file_cleanup import cleanup_pending_files


class Command(BaseCommand):
    help = "Deliver queued account emails with bounded retries. Never prints recipients or tokens."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=5)

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["interval"] < 1:
            raise CommandError("Limit and interval must be positive.")
        while True:
            close_old_connections()
            cleanup = Counter(cleanup_pending_files(options["limit"]))
            if cleanup:
                self.stdout.write("Private document cleanup: " + ", ".join(f"{key}={value}" for key, value in sorted(cleanup.items())))
            keys = list(pending_deliveries(timezone.now()).values_list("pk", flat=True)[:options["limit"]])
            totals = Counter(deliver_one(pk) for pk in keys)
            if keys or not options["watch"]:
                self.stdout.write("Email queue: " + ", ".join(f"{key}={value}" for key, value in sorted(totals.items())) if totals else "Email queue: no eligible messages.")
            if not options["watch"]:
                break
            try:
                time.sleep(options["interval"])
            except KeyboardInterrupt:
                break
