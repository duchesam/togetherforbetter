import os
from urllib.parse import urlsplit
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-together-for-better-change-before-deployment")
if not DEBUG and SECRET_KEY.startswith("development-only"):
    raise RuntimeError("Set DJANGO_SECRET_KEY for production")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",")
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x]
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "opportunities"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.locale.LocaleMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware", "opportunities.middleware.RequestLimitMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages", "opportunities.context_processors.pilot_notice"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}, {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}, {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}, {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}]
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("am", "አማርኛ")]
LOCALE_PATHS = [BASE_DIR / "locale"]
FORMAT_MODULE_PATH = ["config.formats"]
LANGUAGE_COOKIE_HTTPONLY = True
LANGUAGE_COOKIE_SAMESITE = "Lax"
# Shared database limits work across application workers, without a Redis dependency.
# Counts are per direct client address for anonymous endpoints, per user otherwise.
REQUEST_LIMITS = {
    "application_withdraw": (10, 3600),
    "review_read": (60, 3600),
    "moderation_review": (60, 3600),
    "login": (10, 600), "signup": (10, 3600), "password_reset": (5, 900),
    "apply": (30, 3600), "post_job": (10, 3600), "report_job": (10, 3600),
    "profile": (30, 3600),
    "verification_request": (3, 900), "account_delete": (5, 3600),
    "account_settings": (30, 3600),
    "interview_invite": (10, 3600), "interview_response": (20, 3600),
    "interview_cancel": (20, 3600), "placement_response": (20, 3600),
    "listing_edit": (20, 3600), "listing_close": (20, 3600), "listing_reopen": (10, 3600),
    "save_opportunity": (60, 3600), "remove_saved": (60, 3600),
}
TIME_ZONE = "Africa/Addis_Ababa"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"
MEDIA_ROOT = BASE_DIR / ".private_uploads"
# Private uploads are deliberately absent from URL configuration.
MEDIA_URL = "/private-media/"
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "opportunities.mail.PrivateFileEmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_FILE_PATH = BASE_DIR / ".private_mail"
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Together for Better <noreply@example.invalid>")
# Codespaces supplies this header through its authenticated forwarding proxy.
# Keep trust disabled for ordinary environments unless their proxy is configured.
if os.getenv("DJANGO_TRUST_PROXY_SSL_HEADER", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
PASSWORD_RESET_TIMEOUT = 3600
EMAIL_VERIFICATION_TIMEOUT = 86400
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "http://127.0.0.1:8000" if DEBUG else "").rstrip("/")
_public_origin = urlsplit(PUBLIC_SITE_URL)
if not PUBLIC_SITE_URL or (not _public_origin.hostname or _public_origin.scheme not in ["http", "https"] or _public_origin.username or _public_origin.password or _public_origin.path or _public_origin.query or _public_origin.fragment):
    raise RuntimeError("PUBLIC_SITE_URL must be an HTTP(S) origin without credentials, path, query, or fragment")
if not DEBUG and not PUBLIC_SITE_URL.startswith("https://"):
    raise RuntimeError("Set PUBLIC_SITE_URL to the production HTTPS origin")
if not DEBUG:
    LANGUAGE_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
