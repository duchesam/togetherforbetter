"""Permission-scoped staff reviews with signed, expiring review snapshots."""
import hashlib
import json

from django import forms
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache

from .models import Employer, Opportunity


class ReviewForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=())
    reason = forms.CharField(max_length=1500, widget=forms.Textarea, label=gettext_lazy("Review reason"))


def permitted(user, kind):
    return user.is_active and user.is_staff and user.has_perm(f"opportunities.change_{kind}")


def fingerprint(obj):
    values = {field.attname: getattr(obj, field.attname) for field in obj._meta.fields}
    if isinstance(obj, Opportunity):
        values["organization"] = fingerprint(obj.employer)
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


@login_required
@never_cache
def moderation_queue(request):
    kinds = [kind for kind in ["employer", "opportunity"] if permitted(request.user, kind)]
    if not kinds:
        raise PermissionDenied
    kind = request.GET.get("kind", kinds[0])
    if kind not in kinds:
        raise PermissionDenied
    all_items = request.GET.get("state") == "all"
    if kind == "employer":
        items = Employer.objects.all().order_by("pk")
        if not all_items:
            items = items.filter(verified=False)
    else:
        items = Opportunity.objects.select_related("employer").order_by("created_at")
        if not all_items:
            items = items.filter(published=False, closed_at__isnull=True)
    return render(request, "opportunities/moderation_queue.html", {"page": Paginator(items, 12).get_page(request.GET.get("page")), "kind": kind, "kinds": kinds, "all_items": all_items})


@login_required
@never_cache
def moderation_review(request, kind, pk):
    if kind not in ["employer", "opportunity"] or not permitted(request.user, kind):
        raise PermissionDenied
    model = Employer if kind == "employer" else Opportunity
    with transaction.atomic():
        obj = get_object_or_404(model.objects.select_for_update(), pk=pk)
        if kind == "opportunity":
            obj.employer = Employer.objects.select_for_update().get(pk=obj.employer_id)
        owner_id = obj.user_id if kind == "employer" else obj.employer.user_id
        if owner_id == request.user.pk:
            raise PermissionDenied
        state = fingerprint(obj)
        form = ReviewForm(request.POST if request.method == "POST" else None, initial={"snapshot": signing.dumps({"kind": kind, "pk": pk, "state": state, "actor": request.user.pk}, salt="staff-review")})
        form.fields["decision"].label = _("Decision")
        form.fields["decision"].choices = [("approve", _("Approve")), ("withdraw", _("Withhold or withdraw approval"))]
        status = 200
        if request.method == "POST" and form.is_valid():
            try:
                snapshot = signing.loads(form.cleaned_data["snapshot"], salt="staff-review", max_age=3600)
            except signing.BadSignature:
                snapshot = None
            if snapshot != {"kind": kind, "pk": pk, "state": state, "actor": request.user.pk}:
                form.add_error(None, _("This review changed or expired. Reload before making a decision."))
                status = 409
            elif form.cleaned_data["decision"] == "approve" and kind == "opportunity" and (obj.closed_at or obj.is_expired or not obj.employer.verified):
                form.add_error(None, _("Approval requires a verified employer, an open listing, and a current deadline."))
            else:
                approved = form.cleaned_data["decision"] == "approve"
                field = "verified" if kind == "employer" else "published"
                setattr(obj, field, approved)
                fields = [field]
                if kind == "opportunity":
                    obj.version += 1
                    fields.append("version")
                obj.save(update_fields=fields)
                LogEntry.objects.log_actions(user_id=request.user.pk, queryset=model.objects.filter(pk=pk), action_flag=CHANGE, change_message=f"{form.cleaned_data['decision']}: {form.cleaned_data['reason']}")
                messages.success(request, _("Review decision saved."))
                return redirect("moderation_queue")
        history = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(model), object_id=str(pk)).select_related("user").order_by("-action_time")[:20]
        return render(request, "opportunities/moderation_review.html", {"item": obj, "kind": kind, "form": form, "history": history}, status=status)
