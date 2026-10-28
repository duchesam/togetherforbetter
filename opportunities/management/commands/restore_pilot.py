from django.core.management.base import BaseCommand, CommandError
from opportunities.backups import restore_backup


class Command(BaseCommand):
    help = 'Verify and restore a backup into a new private directory; never overwrite live data.'

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True)
        parser.add_argument('--destination', required=True)

    def handle(self, *args, **options):
        try:
            count = restore_backup(options['archive'], options['destination'])
        except FileExistsError:
            raise CommandError('Destination already exists. Choose a new directory; live data is never overwritten.') from None
        except Exception:
            raise CommandError('Restore failed validation. No new restored directory was retained.') from None
        self.stdout.write(f'Restore verified: database and {count} uploaded files. Keep writers stopped until configuration and recovery checks are complete.')
