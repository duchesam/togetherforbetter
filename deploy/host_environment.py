"""Load a private production configuration for host-managed WSGI and worker tasks."""
import json
import os
from pathlib import Path
import stat

ALLOWED_KEYS = {
    'DJANGO_DEBUG', 'DJANGO_SECRET_KEY', 'PUBLIC_SITE_URL', 'DJANGO_ALLOWED_HOSTS',
    'DJANGO_CSRF_TRUSTED_ORIGINS', 'DJANGO_DATA_DIR', 'DJANGO_STATIC_ROOT',
    'DJANGO_TRUST_PROXY_SSL_HEADER', 'EMAIL_BACKEND', 'EMAIL_HOST', 'EMAIL_PORT',
    'EMAIL_USE_TLS', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL',
    'OPENAI_API_KEY', 'RESUME_AI_MODEL',
}


def activate(config_file):
    path = Path(config_file)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError('Use an absolute, non-symlink production configuration path')
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
        raise RuntimeError('Production configuration must be a regular owner-only file (mode 0600)')
    if path.parent.stat().st_mode & 0o077:
        raise RuntimeError('Production configuration directory must be owner-only (mode 0700)')
    with path.open(encoding='utf-8') as source:
        values = json.load(source)
    if not isinstance(values, dict) or not all(key in ALLOWED_KEYS and isinstance(value, str) for key, value in values.items()):
        raise RuntimeError('Production configuration contains invalid keys or value types')
    if values.get('DJANGO_DEBUG') != '0':
        raise RuntimeError('Host configuration must explicitly disable debug mode')
    required = ['DJANGO_SECRET_KEY', 'PUBLIC_SITE_URL', 'DJANGO_DATA_DIR', 'DJANGO_STATIC_ROOT']
    if any(not values.get(key) for key in required):
        raise RuntimeError('Production configuration is incomplete')
    # Do not inherit deployment-specific credentials/proxy trust from a different app.
    for key in ALLOWED_KEYS:
        os.environ.pop(key, None)
    os.environ.update(values)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
