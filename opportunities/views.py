from django.utils.translation import gettext as _
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.db.models import Prefetch
from django.views.decorators.cache import never_cache
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import get_language
from .forms import SignupForm, ProfileForm, EmployerForm, OpportunityForm, ApplicationForm, StatusForm, ReportForm, InterviewResponseForm, PlacementResponseForm
from .models import Profile, Employer, Opportunity, Application, OpportunityReport, EmailDelivery, PrivateFileCleanup, Interview, InterviewEvent, PlacementReport, SavedOpportunity
from .notifications import application_received, change_application_status, queue_verification

def public_jobs():
    jobs = Opportunity.objects.filter(published=True, closed_at__isnull=True, employer__verified=True, deadline__gte=timezone.localdate()).select_related("employer")
    return jobs if settings.DEBUG else jobs.filter(employer__is_demo=False)

def home(request):
    jobs = public_jobs()
    q = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    kind = request.GET.get("kind", "")
    category = request.GET.get("category", "")
    if q:
        jobs = jobs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(employer__name__icontains=q) | Q(category__icontains=q))
    if location:
        jobs = jobs.filter(location__icontains=location)
    if kind:
        jobs = jobs.filter(kind=kind)
    if category:
        jobs = jobs.filter(category=category)
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "opportunities/home.html", {"page": Paginator(jobs, 6).get_page(request.GET.get("page")), "query_params": params.urlencode(), "q": q, "location": location, "kind": kind, "category": category, "kinds": Opportunity.Kind.choices, "categories": public_jobs().order_by("category").values_list("category", flat=True).distinct(), "total": public_jobs().count(), "employer_count": Employer.objects.filter(verified=True).count()})

@never_cache
def detail(request, pk):
    job = get_object_or_404(public_jobs(), pk=pk)
    applied = request.user.is_authenticated and Application.objects.filter(opportunity=job, applicant=request.user).exists()
    saved = SavedOpportunity.objects.filter(user=request.user, opportunity=job).first() if request.user.is_authenticated else None
    return render(request, "opportunities/detail.html", {"job": job, "applied": applied, "saved": saved})

def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None, initial={"role": "employer" if request.GET.get("role") == "employer" else "seeker"})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            profile = Profile.objects.create(user=user, full_name=form.cleaned_data["full_name"], role=form.cleaned_data["role"], preferred_language=get_language(), email_verification_required=True)
            if form.cleaned_data["role"] == "employer":
                Employer.objects.create(user=user, name=form.cleaned_data["organization_name"])
            queue_verification(profile)
        login(request, user)
        messages.success(request, _("Welcome! Your account is ready."))
        return redirect("dashboard")
    return render(request, "opportunities/form.html", {"form": form, "title": _("Your next chapter starts here"), "subtitle": _("Join our community. Always free for job seekers."), "button": _("Create account")})

@login_required
def dashboard(request):
    profile, created = Profile.objects.get_or_create(user=request.user, defaults={"full_name": request.user.get_full_name() or request.user.username})
    context = {"profile": profile, "reports": request.user.opportunity_reports.select_related("opportunity"), "unread_notifications": request.user.notifications.filter(read_at__isnull=True).count()}
    if profile.role == "employer":
        employer = get_object_or_404(Employer, user=request.user)
        context.update(unread_reviews=employer.review_decisions.filter(read_at__isnull=True).count(), employer=employer, jobs=employer.opportunities.all(), applications=Application.objects.filter(opportunity__employer=employer).select_related("opportunity", "applicant__profile"))
    else:
        context["applications"] = request.user.applications.select_related("opportunity__employer")
    return render(request, "opportunities/dashboard.html", context)

@login_required
def profile_edit(request):
    profile, created = Profile.objects.get_or_create(user=request.user, defaults={"full_name": request.user.username})
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, _("Your profile has been updated."))
        return redirect("dashboard")
    return render(request, "opportunities/form.html", {"form": form, "profile": profile, "title": _("Make your experience count"), "subtitle": _("Your profile and optional CV are private. Employers can see your current profile and CV when you apply to their opportunities."), "button": _("Save profile")})


@login_required
def download_cv(request, pk):
    profile = get_object_or_404(Profile.objects.select_related("user"), pk=pk)
    is_owner = profile.user_id == request.user.pk
    is_admin = request.user.has_perm("opportunities.view_profile")
    is_hiring_employer = Application.objects.filter(
        applicant_id=profile.user_id,
        opportunity__employer__user=request.user,
    ).exists()
    if not (is_owner or is_admin or is_hiring_employer):
        raise PermissionDenied
    if not profile.cv:
        raise Http404(_("No CV is available."))
    try:
        document = profile.cv.open("rb")
    except FileNotFoundError:
        raise Http404(_("The CV is unavailable. Please ask the applicant to upload it again."))
    response = FileResponse(
        document, as_attachment=True, filename="candidate-cv.pdf",
        content_type="application/octet-stream",
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response

@login_required
def employer_edit(request):
    employer = get_object_or_404(Employer, user=request.user)
    form = EmployerForm(request.POST or None, instance=employer)
    if request.method == "POST" and form.is_valid():
        org = form.save(commit=False)
        org.verified = False
        org.save()
        messages.success(request, _("Organization updated and submitted for verification."))
        return redirect("dashboard")
    return render(request, "opportunities/form.html", {"form": form, "title": _("Introduce your organization"), "subtitle": _("Changes require a new verification review before your listings are visible."), "button": _("Save organization")})

@login_required
def post_job(request):
    employer = get_object_or_404(Employer, user=request.user)
    if request.user.profile.needs_email_verification:
        messages.info(request, _("Verify your email address before posting an opportunity."))
        return redirect("account_settings")
    form = OpportunityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        job = form.save(commit=False)
        job.employer = employer
        job.save()
        messages.success(request, _("Opportunity submitted. It will appear after organization verification and listing review."))
        return redirect("dashboard")
    return render(request, "opportunities/form.html", {"form": form, "title": _("Open a door for someone"), "subtitle": _("Create a clear, honest opportunity. All listings are reviewed before publication."), "button": _("Submit for review")})

@login_required
def apply(request, pk):
    job = get_object_or_404(public_jobs(), pk=pk)
    profile = get_object_or_404(Profile, user=request.user)
    if profile.role != "seeker":
        raise PermissionDenied(_("Only job seekers can apply."))
    if profile.needs_email_verification:
        messages.info(request, _("Verify your email address before applying."))
        return redirect("account_settings")
    if Application.objects.filter(opportunity=job, applicant=request.user).exists():
        messages.info(request, _("You have already applied for this opportunity."))
        return redirect("dashboard")
    form = ApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            current_job = get_object_or_404(public_jobs().select_for_update(), pk=pk)
            application, created = Application.objects.get_or_create(opportunity=current_job, applicant=request.user, defaults={"cover_letter": form.cleaned_data["cover_letter"]})
            if created:
                application_received(application)
        messages.success(request, _("Application sent. Track its progress in your dashboard."))
        return redirect("dashboard")
    return render(request, "opportunities/form.html", {"form": form, "title": _("Apply for %(title)s") % {"title": job.title}, "subtitle": _("Your current profile, CV (if uploaded), email, and this message will be shared with %(employer)s. Later profile and CV updates will also be visible to this employer. Update your profile before applying.") % {"employer": job.employer.name}, "button": _("Send application")})

@login_required
@never_cache
def application_detail(request, pk):
    application = get_object_or_404(Application.objects.select_related("opportunity__employer", "applicant__profile"), pk=pk)
    owner = application.opportunity.employer.user_id == request.user.id
    if not owner and application.applicant_id != request.user.id:
        raise PermissionDenied
    if request.method == "POST" and not owner:
        return HttpResponseForbidden()
    form = StatusForm(request.POST or None, instance=application)
    if request.method == "POST" and form.is_valid():
        change_application_status(application.pk, request.user, form.cleaned_data["status"])
        messages.success(request, _("Application status updated."))
        return redirect("application", pk=pk)
    interviews = list(application.interviews.order_by("-pk").prefetch_related(Prefetch("events", queryset=InterviewEvent.objects.order_by("-created_at", "-pk")[:5], to_attr="recent_events"))[:5])
    is_open = application.status not in ["hired", "declined"]
    for index, interview in enumerate(interviews):
        interview.can_respond = not owner and index == 0 and interview.status not in ["cancelled", "replaced"] and interview.scheduled_at > timezone.now() and is_open
        interview.response_form = InterviewResponseForm(initial={"status": interview.status if interview.status in ["accepted", "declined", "reschedule"] else "", "note": interview.response_note})
    report = application.placement_reports.filter(superseded_at__isnull=True).first()
    return render(request, "opportunities/application.html", {
        "application": application, "form": form, "owner": owner,
        "interviews": interviews, "can_schedule": owner and is_open,
        "placement_report": report, "placement_response_form": PlacementResponseForm(initial={"response": report.response}) if report else None,
        "placement_history": list(report.events.order_by("-created_at", "-pk")[:5]) if report else [],
    })

def about(request):
    return render(request, "opportunities/about.html")


@login_required
def report_job(request, pk):
    job = get_object_or_404(public_jobs(), pk=pk)
    if job.employer.user_id == request.user.pk:
        raise PermissionDenied
    existing = OpportunityReport.objects.filter(reporter=request.user, opportunity=job).first()
    if existing:
        return redirect("report_detail", pk=existing.pk)
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report, created = OpportunityReport.objects.get_or_create(
            reporter=request.user, opportunity=job,
            defaults={"reason": form.cleaned_data["reason"], "details": form.cleaned_data["details"]},
        )
        messages.success(request, _("Your report has been received. Our moderators will review it."))
        return redirect("report_detail", pk=report.pk)
    return render(request, "opportunities/form.html", {
        "form": form, "title": _("Report a concern"), "button": _("Send report"),
        "subtitle": _("Help keep the community safe. The employer will not see your identity or report. Reports are reviewed before any action is taken."),
    })


@login_required
def report_detail(request, pk):
    report = get_object_or_404(OpportunityReport.objects.select_related("opportunity"), pk=pk, reporter=request.user)
    return render(request, "opportunities/report.html", {"report": report})


@staff_member_required
def impact(request):
    applications = Application.objects.filter(opportunity__employer__is_demo=False)
    outcomes = PlacementReport.objects.filter(superseded_at__isnull=True, application__status="hired", application__opportunity__employer__is_demo=False)
    confirmed = outcomes.filter(response="confirmed").count()
    disputed = outcomes.filter(response="disputed").count()
    return render(request, "opportunities/impact.html", {
        "seekers": Profile.objects.filter(role="seeker", user__is_active=True).count(),
        "verified_employers": Employer.objects.filter(verified=True, is_demo=False).count(),
        "pending_employers": Employer.objects.filter(verified=False, is_demo=False).count(),
        "pending_reports": OpportunityReport.objects.filter(opportunity__employer__is_demo=False, status__in=["open", "investigating"]).count(),
        "pending_emails": EmailDelivery.objects.filter(sent_at__isnull=True, cancelled_at__isnull=True, failed_at__isnull=True).count(),
        "failed_emails": EmailDelivery.objects.filter(failed_at__isnull=False, cancelled_at__isnull=True).count(),
        "pending_file_cleanup": PrivateFileCleanup.objects.filter(failed_at__isnull=True).count(),
        "failed_file_cleanup": PrivateFileCleanup.objects.filter(failed_at__isnull=False).count(),
        "live_jobs": public_jobs().filter(employer__is_demo=False).count(),
        "application_count": applications.count(),
        "placements": applications.filter(status="hired").count(),
        "applicant_confirmed": confirmed,
        "disputed_placements": disputed,
        "awaiting_placements": applications.filter(status="hired").count() - confirmed - disputed,
        "confirmed_people": outcomes.filter(response="confirmed").values("application__applicant").distinct().count(),
        "people_placed": applications.filter(status="hired").values("applicant").distinct().count(),
        "recent_placements": applications.filter(status="hired").select_related("applicant__profile", "opportunity__employer").prefetch_related(Prefetch("placement_reports", queryset=PlacementReport.objects.filter(superseded_at__isnull=True), to_attr="current_placement_reports")).order_by("-updated_at")[:10],
    })
