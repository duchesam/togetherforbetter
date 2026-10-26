"""Atomic, shared fixed-window limits. Never trust client-supplied proxy headers."""
import math
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import F
from django.shortcuts import render
from django.utils import timezone as django_timezone
from django.utils.crypto import salted_hmac
from django.utils.deprecation import MiddlewareMixin

from .models import RequestBucket


class RequestLimitMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != "POST":
            return None
        name = request.resolver_match.url_name
        rule = settings.REQUEST_LIMITS.get(name)
        if not rule:
            return None
        limit, seconds = rule
        now = django_timezone.now()
        window = math.floor(now.timestamp() / seconds)
        identity = (
            f"user:{request.user.pk}" if request.user.is_authenticated
            else f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        key = salted_hmac("together.request-limits", f"{name}:{identity}:{window}", algorithm="sha256").hexdigest()
        expiry = datetime.fromtimestamp((window + 1) * seconds, tz=timezone.utc)
        RequestBucket.objects.get_or_create(key=key, defaults={"expires_at": expiry})
        admitted = RequestBucket.objects.filter(key=key, attempts__lt=limit).update(attempts=F("attempts") + 1)
        if admitted:
            return None
        retry = max(1, math.ceil((expiry - now).total_seconds()))
        response = render(request, "opportunities/rate_limited.html", {"retry_minutes": max(1, math.ceil(retry / 60))}, status=429)
        response["Retry-After"] = str(retry)
        response["Cache-Control"] = "no-store"
        return response
