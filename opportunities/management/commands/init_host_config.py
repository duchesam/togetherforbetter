import json
import os
from pathlib import Path
import re

from deploy.host_environment import initial_configuration
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Initialize a new private host configuration without displaying secrets.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--directory', required=True, help='Absolute private data directory outside the repository')
        parser.add_argument('--hostname', required=True, help='Your actual hosting hostname, without scheme or path')

    def handle(self, *args, **options):
        directory = Path(options['directory'])
        hostname = options['hostname'].lower()
        if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', hostname):
            raise CommandError('Supply an exact hosting hostname without scheme, path, wildcards or port.')
        if not directory.is_absolute() or directory.is_symlink():
            raise CommandError('Use an absolute, non-symlink private directory outside the repository.')
        directory = directory.resolve()
        project = Path(settings.BASE_DIR).resolve()
        if directory == project or project in directory.parents or directory in project.parents:
            raise CommandError('The private directory must be separate from the repository.')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise CommandError('The private directory must have owner-only permissions (0700).')
        config = initial_configuration(directory, hostname)
        try:
            descriptor = os.open(directory / 'production.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise CommandError('Configuration already exists. It was not changed and its secret was not rotated.') from None
        with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
            json.dump(config, destination, indent=2)
            destination.write('\n')
        self.stdout.write('Private host configuration created. SMTP sender/credentials and proxy behavior still require configuration before launch.')
