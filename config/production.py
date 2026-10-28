"""Validate persistent storage and host boundaries before a production process starts."""
from pathlib import Path
from urllib.parse import urlsplit


def production_config(environ, base_dir, public_url, secret):
    if len(secret) < 50 or len(set(secret)) < 5:
        raise RuntimeError('Production DJANGO_SECRET_KEY must be a strong independent key of at least 50 characters')
    value = environ.get('DJANGO_DATA_DIR', '')
    if not value or not Path(value).is_absolute():
        raise RuntimeError('Set DJANGO_DATA_DIR to an absolute persistent private directory')
    data = Path(value).resolve()
    static = Path(environ.get('DJANGO_STATIC_ROOT', str(base_dir / 'staticfiles'))).resolve()
    if data == static or data in static.parents or static in data.parents:
        raise RuntimeError('Private data and public static directories must be separate')
    hosts = [value.strip() for value in environ.get('DJANGO_ALLOWED_HOSTS', urlsplit(public_url).hostname).split(',')]
    if not hosts or any(not host or '*' in host or '/' in host or ':' in host or host.startswith('.') for host in hosts):
        raise RuntimeError('Production DJANGO_ALLOWED_HOSTS must contain explicit hostnames without wildcards or ports')
    if urlsplit(public_url).hostname not in hosts:
        raise RuntimeError('DJANGO_ALLOWED_HOSTS must include the PUBLIC_SITE_URL hostname')
    return data, static, hosts
