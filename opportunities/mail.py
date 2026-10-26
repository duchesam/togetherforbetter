"""A development inbox that keeps password-reset messages private on disk."""
import os

from django.conf import settings
from django.core.mail.backends.filebased import EmailBackend as FileEmailBackend


class PrivateFileEmailBackend(FileEmailBackend):
    def __init__(self, *args, file_path=None, **kwargs):
        private_path = file_path or settings.EMAIL_FILE_PATH
        os.makedirs(private_path, mode=0o700, exist_ok=True)
        super().__init__(*args, file_path=private_path, **kwargs)

    def open(self):
        if self.stream:
            return False
        try:
            descriptor = os.open(self._get_filename(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            self.stream = os.fdopen(descriptor, "ab")
            return True
        except OSError:
            if not self.fail_silently:
                raise
            return False
