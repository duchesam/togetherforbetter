from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import ListingActionForm, OpportunityEditForm
from .listings import change_listing, ListingConflict
from .models import Opportunity, Profile, SavedOpportunity
from .views import public_jobs


def owner_listing(request, pk):
    return get_object_or_404(Opportunity.objects.select_related("employer"), pk=pk, employer__user=request.user)


@login_required
@never_cache
def listing_manage(request, pk):
    job = owner_listing(request, pk)
    return render(request, "opportunities/listing_manage.html", {"job": job, "action_form": ListingActionForm(initial={"expected_version": job.version}), "changes": job.changes.select_related("actor")[:10]})


@login_required
@never_cache
def listing_edit(request, pk):
    job = owner_listing(request, pk)
    if request.user.profile.needs_email_verification:
        messages.info(request, _("Verify your email address before editing or reopening a listing."))
        return redirect("account_settings")
    form = OpportunityEditForm(request.POST or None, instance=job, initial={"expected_version": job.version})
    if request.method == "POST" and form.is_valid():
        try:
            change_listing(pk, request.user, "edited", form.cleaned_data["expected_version"], form.cleaned_data)
        except ListingConflict as error:
            return render(request, "opportunities/listing_conflict.html", {"job": job, "reason": str(error)}, status=409)
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, _("Listing saved. Changed listings require review; closed listings stay closed."))
            return redirect("listing_manage", pk=pk)
    return render(request, "opportunities/form.html", {"form": form, "title": _("Edit opportunity"), "subtitle": _("Changes remove the listing from public search until an administrator reviews it. Existing applications are retained."), "button": _("Save for review")})


@login_required
@require_POST
def listing_action(request, pk, action):
    job = owner_listing(request, pk)
    form = ListingActionForm(request.POST)
    if not form.is_valid():
        return render(request, "opportunities/listing_conflict.html", {"job": job, "reason": _("Reload the listing before submitting this action.")}, status=400)
    try:
        change_listing(pk, request.user, action, form.cleaned_data["expected_version"])
    except ListingConflict as error:
        return render(request, "opportunities/listing_conflict.html", {"job": job, "reason": str(error)}, status=409)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, _("Listing closed to new applications.") if action == "closed" else _("Listing reopened for administrator review."))
    return redirect("listing_manage", pk=pk)


def require_seeker(request):
    if not Profile.objects.filter(user=request.user, role=Profile.Role.SEEKER).exists():
        raise PermissionDenied


@login_required
@require_POST
def save_opportunity(request, pk):
    require_seeker(request)
    with transaction.atomic():
        job = get_object_or_404(public_jobs().select_for_update(), pk=pk)
        SavedOpportunity.objects.get_or_create(user=request.user, opportunity=job, defaults={"title": job.title, "employer_name": job.employer.name, "location": job.location})
    messages.success(request, _("Opportunity saved to your private list."))
    return redirect("detail", pk=pk)


@login_required
@never_cache
def saved_opportunities(request):
    require_seeker(request)
    saves = request.user.saved_opportunities.select_related("opportunity__employer")
    return render(request, "opportunities/saved.html", {"page": Paginator(saves, 12).get_page(request.GET.get("page"))})


@login_required
@require_POST
def remove_saved(request, pk):
    require_seeker(request)
    saved = get_object_or_404(SavedOpportunity, pk=pk, user=request.user)
    saved.delete()
    messages.success(request, _("Opportunity removed from your saved list."))
    return redirect("saved_opportunities")
