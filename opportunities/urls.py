from django.contrib.auth import views as auth_views
from django.urls import path
from . import views, tracker_views
from . import account_views
from . import hiring_views
from . import listing_views, moderation_views, review_views
from .forms import LockedSetPasswordForm
urlpatterns = [
    path("organization/applicants/", tracker_views.employer_applicants, name="employer_applicants"),
    path("applications/", tracker_views.application_tracker, name="application_tracker"),
    path("applications/<int:pk>/withdraw/", hiring_views.application_withdraw, name="application_withdraw"),
    path("organization/reviews/", review_views.employer_reviews, name="employer_reviews"),
    path("organization/reviews/<int:pk>/read/", review_views.review_read, name="review_read"),
    path("staff/reviews/", moderation_views.moderation_queue, name="moderation_queue"),
    path("staff/reviews/<str:kind>/<int:pk>/", moderation_views.moderation_review, name="moderation_review"),
    path("", views.home, name="home"),
    path("impact/", views.impact, name="impact"),
    path("about/", views.about, name="about"),
    path("opportunities/<int:pk>/", views.detail, name="detail"),
    path("opportunities/<int:pk>/manage/", listing_views.listing_manage, name="listing_manage"),
    path("opportunities/<int:pk>/edit/", listing_views.listing_edit, name="listing_edit"),
    path("opportunities/<int:pk>/close/", listing_views.listing_action, {"action": "closed"}, name="listing_close"),
    path("opportunities/<int:pk>/reopen/", listing_views.listing_action, {"action": "reopened"}, name="listing_reopen"),
    path("opportunities/<int:pk>/save/", listing_views.save_opportunity, name="save_opportunity"),
    path("saved/", listing_views.saved_opportunities, name="saved_opportunities"),
    path("saved/<int:pk>/remove/", listing_views.remove_saved, name="remove_saved"),
    path("opportunities/<int:pk>/apply/", views.apply, name="apply"),
    path("opportunities/<int:pk>/report/", views.report_job, name="report_job"),
    path("reports/<int:pk>/", views.report_detail, name="report_detail"),
    path("join/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(template_name="opportunities/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("account/", account_views.account_settings, name="account_settings"),
    path("account/verification/", account_views.verification_request, name="verification_request"),
    path("account/verify/<str:token>/", account_views.email_verify, name="email_verify"),
    path("account/delete/", account_views.account_delete, name="account_delete"),
    path("notifications/", account_views.notification_inbox, name="notifications"),
    path("notifications/<int:pk>/open/", account_views.notification_open, name="notification_open"),
    path("profile/", views.profile_edit, name="profile"),
    path("profiles/<int:pk>/cv/", views.download_cv, name="download_cv"),
    path("password/reset/", auth_views.PasswordResetView.as_view(
        template_name="opportunities/password_reset_form.html",
        email_template_name="opportunities/password_reset_email.txt",
        subject_template_name="opportunities/password_reset_subject.txt",
    ), name="password_reset"),
    path("password/reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="opportunities/password_reset_done.html",
    ), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", account_views.AccountPasswordResetConfirmView.as_view(
        template_name="opportunities/password_reset_confirm.html",
        form_class=LockedSetPasswordForm,
    ), name="password_reset_confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="opportunities/password_reset_complete.html",
    ), name="password_reset_complete"),
    path("organization/", views.employer_edit, name="employer"),
    path("opportunities/new/", views.post_job, name="post_job"),
    path("applications/<int:pk>/", views.application_detail, name="application"),
    path("applications/<int:pk>/interview/", hiring_views.interview_invite, name="interview_invite"),
    path("interviews/<int:pk>/respond/", hiring_views.interview_response, name="interview_response"),
    path("interviews/<int:pk>/cancel/", hiring_views.interview_cancel, name="interview_cancel"),
    path("interviews/<int:pk>/calendar/", hiring_views.interview_calendar, name="interview_calendar"),
    path("placements/<int:pk>/respond/", hiring_views.placement_response, name="placement_response"),
]
