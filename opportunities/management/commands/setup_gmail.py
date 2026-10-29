"""Validate Gmail credentials privately before changing production configuration."""
import getpass
import json
import os
from pathlib import Path
import smtplib
import sys
import tempfile
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from deploy.host_environment import activate
from opportunities.gmail import GmailEmailBackend


class Command(BaseCommand):
    help = 'Privately test Gmail SMTP authentication, then save only verified email settings. Sends no email.'
    requires_system_checks = []

    def handle(self, *args, **options):
        if not sys.stdin.isatty():
            raise CommandError('Run this command in an interactive Bash console; passwords are never read with echo enabled.')
        path = Path(settings.DATA_DIR) / 'production.json'
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if data.get('DJANGO_SECRET_KEY') != settings.SECRET_KEY or data.get('DJANGO_DATA_DIR') != str(settings.DATA_DIR):
                raise ValueError
            activate(path)
        except (OSError, ValueError, RuntimeError):
            raise CommandError('Cannot safely load the active private configuration. No settings were changed.') from None
        self.stdout.write('Use the same Google account that created the app password. Password input is hidden.')
        current = data.get('EMAIL_HOST_USER', '')
        address = input(f'Google email address [{current}]: ').strip() or current
        try:
            validate_email(address)
        except ValidationError:
            raise CommandError('Enter a complete Google email address. Nothing was saved.') from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = ''.join(getpass.getpass('Google app password (hidden): ').split())
        except getpass.GetPassWarning:
            raise CommandError('Hidden terminal input is unavailable. Nothing was saved.') from None
        if len(password) != 16 or not password.isascii() or not password.isalnum():
            raise CommandError('Expected a complete 16-character Google app password, not the normal account password. Nothing was saved.')
        backend = GmailEmailBackend(host='smtp.gmail.com', port=587, username=address, password=password, use_tls=True, use_ssl=False, timeout=15)
        try:
            backend.open()
        except smtplib.SMTPAuthenticationError as error:
            raise CommandError(f'Gmail rejected authentication (code {error.smtp_code}). Confirm the app password was created by this exact Google account. Nothing was saved.') from None
        except (OSError, smtplib.SMTPException, ValueError) as error:
            raise CommandError(f'Gmail connection failed ({type(error).__name__}). Nothing was saved.') from None
        finally:
            connection = backend.connection or backend._partial_connection
            if connection:
                try:
                    connection.close()
                except OSError:
                    pass
        data.update(EMAIL_BACKEND='opportunities.gmail.GmailEmailBackend', EMAIL_HOST='smtp.gmail.com', EMAIL_PORT='587', EMAIL_USE_TLS='1', EMAIL_HOST_USER=address, EMAIL_HOST_PASSWORD=password, DEFAULT_FROM_EMAIL=f'Together for Better <{address}>')
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.gmail-config-', dir=path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(data, output, indent=2)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            if path.read_bytes() != raw:
                raise CommandError('Configuration changed during setup. Nothing was saved; retry after closing the editor.')
            os.replace(temporary, path)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
        self.stdout.write('Gmail authentication succeeded and verified email settings were saved. No email sent. Other settings and the secret key were preserved. Reload the web app and restart its mail worker.')
