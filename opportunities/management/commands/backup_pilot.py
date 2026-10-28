from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from opportunities.backups import create_backup


class Command(BaseCommand):
    help = 'Create a private SQLite and CV snapshot after stopping web and worker processes.'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--offline', action='store_true', help='Confirm web, workers and other writers have been stopped.')

    def handle(self, *args, **options):
        if not options['offline']:
            raise CommandError('Stop all writers and pass --offline to acknowledge the maintenance window.')
        database = settings.DATABASES['default']
        if database['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('This backup command supports file-backed SQLite only.')
        output = Path(options['output']).resolve()
        public = Path(settings.STATIC_ROOT).resolve()
        if output == public or public in output.parents:
            raise CommandError('Backups must not be stored in the public static directory.')
        try:
            count = create_backup(database['NAME'], settings.MEDIA_ROOT, options['output'])
        except Exception:
            raise CommandError('Backup failed. No new archive was retained. Check paths, permissions, and available disk space.') from None
        self.stdout.write(f'Private backup complete: database and {count} uploaded files. Keep the archive confidential.')
