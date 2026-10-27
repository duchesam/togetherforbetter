"""Owner-only review receipts. Internal moderation reasons never enter this view."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Employer, ReviewDecision


@login_required
@never_cache
def employer_reviews(request):
    employer = get_object_or_404(Employer, user=request.user)
    reviews = employer.review_decisions.select_related("opportunity")
    listing = None
    if request.GET.get("listing"):
        listing = get_object_or_404(employer.opportunities, pk=request.GET["listing"] if request.GET["listing"].isdigit() else 0)
        reviews = reviews.filter(opportunity=listing)
    return render(request, "opportunities/employer_reviews.html", {"employer": employer, "listing": listing, "page": Paginator(reviews, 12).get_page(request.GET.get("page"))})


@login_required
@require_POST
def review_read(request, pk):
    review = get_object_or_404(ReviewDecision, pk=pk, employer__user=request.user)
    ReviewDecision.objects.filter(pk=review.pk, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("employer_reviews")
