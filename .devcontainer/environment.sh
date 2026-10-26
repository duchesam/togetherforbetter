# Sourced by setup/start so both processes share one workspace-specific session key.
pilot_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PILOT_RUNTIME_DIR="${PILOT_RUNTIME_DIR:-$pilot_root/.pilot-runtime}"
umask 077
mkdir -p "$PILOT_RUNTIME_DIR"
chmod 700 "$PILOT_RUNTIME_DIR"
if [[ -z "${DJANGO_SECRET_KEY:-}" ]]; then
  python - "$PILOT_RUNTIME_DIR/django-secret" <<'PY'
import os, secrets, sys
try:
    descriptor = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(secrets.token_urlsafe(64))
PY
  export DJANGO_SECRET_KEY="$(cat "$PILOT_RUNTIME_DIR/django-secret")"
fi
export DJANGO_DEBUG=1
export EMAIL_BACKEND=opportunities.mail.PrivateFileEmailBackend
export PILOT_PORT="${PILOT_PORT:-8000}"
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  pilot_hostname="${CODESPACE_NAME}-${PILOT_PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,$pilot_hostname"
  export DJANGO_CSRF_TRUSTED_ORIGINS="https://$pilot_hostname"
  export PUBLIC_SITE_URL="https://$pilot_hostname"
  export DJANGO_TRUST_PROXY_SSL_HEADER=1
else
  export PUBLIC_SITE_URL="${PUBLIC_SITE_URL:-http://127.0.0.1:$PILOT_PORT}"
fi
