import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language

from .forms import AccountPreferencesForm, DeleteAccountForm
from .models import Notification, Profile
from .notifications import queue_verification, valid_verification_token


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)


def set_language(request):
    response = django_set_language(request)
    language = request.POST.get("language") if request.method == "POST" else None
    if request.user.is_authenticated and language in dict(settings.LANGUAGES):
        Profile.objects.filter(user=request.user).update(preferred_language=language)
    return response


@login_required
@never_cache
def account_settings(request):
    profile, created = Profile.objects.get_or_create(user=request.user, defaults={"full_name": request.user.username})
    form = AccountPreferencesForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        language = form.cleaned_data["preferred_language"]
        translation.activate(language)
        messages.success(request, _("Account preferences saved."))
        response = redirect("account_settings")
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=settings.LANGUAGE_COOKIE_AGE, secure=settings.LANGUAGE_COOKIE_SECURE, httponly=settings.LANGUAGE_COOKIE_HTTPONLY, samesite=settings.LANGUAGE_COOKIE_SAMESITE)
        return response
    return render(request, "opportunities/account.html", {"profile": profile, "form": form})


@login_required
@require_POST
@never_cache
def verification_request(request):
    profile = get_object_or_404(Profile.objects.select_related("user"), user=request.user)
    try:
        validate_email(request.user.email)
    except ValidationError:
        messages.error(request, _("Your account needs a valid email address. Contact the platform administrator."))
        return redirect("account_settings")
    if queue_verification(profile):
        messages.success(request, _("Verification instructions have been queued for your email address."))
    else:
        messages.info(request, _("Your email address is already verified."))
    return redirect("account_settings")


@login_required
@never_cache
def email_verify(request, token):
    if request.method not in ["GET", "POST"]:
        return HttpResponseNotAllowed(["GET", "POST"])
    with transaction.atomic():
        profile = get_object_or_404(Profile.objects.select_for_update().select_related("user"), user=request.user)
        valid = valid_verification_token(profile, token)
        if valid and request.method == "POST":
            profile.verified_email = profile.user.email.strip()
            profile.email_verified_at = timezone.now()
            profile.verification_nonce = uuid.uuid4()
            profile.save(update_fields=["verified_email", "email_verified_at", "verification_nonce"])
            messages.success(request, _("Your email address is verified."))
            return redirect("account_settings")
    return render(request, "opportunities/email_verify.html", {"valid_link": valid}, status=200 if valid else 400)


@login_required
@never_cache
def account_delete(request):
    profile = get_object_or_404(Profile, user=request.user)
    if profile.role != Profile.Role.SEEKER or request.user.is_staff or request.user.is_superuser:
        raise PermissionDenied(_("Organization and staff accounts require administrator-managed closure."))
    form = DeleteAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            current_user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            current_profile = Profile.objects.select_for_update().get(user=current_user)
            if current_user.is_staff or current_user.is_superuser or current_profile.role != Profile.Role.SEEKER:
                raise PermissionDenied
            if not current_user.check_password(form.cleaned_data["password"]):
                form.add_error("password", _("Your password was incorrect. Your account has not been deleted."))
            else:
                current_user.delete()
                logout(request)
                messages.success(request, _("Your account has been deleted."))
                return redirect("home")
    return render(request, "opportunities/delete_account.html", {"form": form})


@login_required
@never_cache
def notification_inbox(request):
    notices = request.user.notifications.select_related("application__opportunity")
    page = Paginator(notices, 20).get_page(request.GET.get("page"))
    return render(request, "opportunities/notifications.html", {"page": page})


@login_required
@require_POST
def notification_open(request, pk):
    notice = get_object_or_404(Notification, pk=pk, recipient=request.user)
    Notification.objects.filter(pk=notice.pk, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("application", pk=notice.application_id)
