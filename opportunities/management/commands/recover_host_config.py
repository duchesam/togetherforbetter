"""Repair missing JSON braces/settings while preserving credentials and live data."""
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from config.production import production_config
from deploy.host_environment import ALLOWED_KEYS, initial_configuration


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate keys')
        result[key] = value
    return result


class Command(BaseCommand):
    help = 'Recover private configuration without changing the database or displaying credentials.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--directory', required=True)
        parser.add_argument('--hostname', required=True)
        parser.add_argument('--replace-missing-secret', action='store_true', help='Acknowledge that a missing key must be replaced, invalidating existing sessions/links.')

    def handle(self, *args, **options):
        directory = Path(options['directory'])
        hostname = options['hostname'].lower()
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise CommandError('Use the existing absolute private directory, not a symlink.')
        directory = directory.resolve()
        project = Path(settings.BASE_DIR).resolve()
        if directory == project or project in directory.parents or directory in project.parents:
            raise CommandError('Private configuration must be outside the repository.')
        if directory.stat().st_mode & 0o077:
            raise CommandError('Set private directory permissions to 0700 first.')
        if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', hostname):
            raise CommandError('Supply the exact existing host name without scheme, path or port.')
        path = directory / 'production.json'
        if path.is_symlink() or not path.is_file():
            raise CommandError('The existing production.json must be a regular file.')
        raw = path.read_bytes()
        if len(raw) > 128 * 1024:
            raise CommandError('Configuration is too large for automatic recovery.')
        try:
            text = raw.decode('utf-8').strip()
        except UnicodeError:
            raise CommandError('Configuration must be UTF-8 text.') from None
        previous = None
        for candidate in (text, '{' + text + '}', '{' + text, text + '}'):
            try:
                value = json.loads(candidate, object_pairs_hook=unique_pairs)
            except ValueError:
                continue
            if isinstance(value, dict):
                previous = value
                break
        if previous is None or not all(key in ALLOWED_KEYS and isinstance(value, str) for key, value in previous.items()):
            raise CommandError('Cannot safely recover these settings. File was not changed; do not share its contents.')
        replacing = not previous.get('DJANGO_SECRET_KEY')
        if replacing and not options['replace_missing_secret']:
            raise CommandError('Original secret is missing. Use --replace-missing-secret only after accepting that sessions and signed links will be invalidated.')
        config = initial_configuration(directory, hostname) | previous
        if config['DJANGO_DEBUG'] != '0' or config['PUBLIC_SITE_URL'] != 'https://' + hostname:
            raise CommandError('Existing debug/host settings differ; automatic recovery will not override them.')
        if Path(config['DJANGO_DATA_DIR']).resolve() != directory:
            raise CommandError('Existing data directory differs. Recovery will not move or recreate the database.')
        try:
            production_config(config, project, config['PUBLIC_SITE_URL'], config['DJANGO_SECRET_KEY'])
        except (RuntimeError, TypeError, ValueError):
            raise CommandError('Recovered production settings did not validate. File was not changed.') from None
        backup = directory / ('production.before-recovery-' + uuid.uuid4().hex + '.json')
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as saved:
            saved.write(raw)
            saved.flush()
            os.fsync(saved.fileno())
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.production-recovery-', dir=directory)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
                json.dump(config, destination, indent=2)
                destination.write('\n')
                destination.flush()
                os.fsync(destination.fileno())
            # Reject an edit made after we read the file rather than overwriting it.
            if path.read_bytes() != raw:
                raise CommandError('Configuration changed during recovery. Retry after closing the editor.')
            os.replace(temporary, path)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
        self.stdout.write('Configuration recovered. Existing email credentials were preserved. A private copy of the previous file was saved. Database and uploaded files were not changed.')
        if replacing:
            self.stdout.write('A new secret was required. Reload the web app and sign in again; previously signed links must be requested again.')
        else:
            self.stdout.write('The original secret key was preserved.')
