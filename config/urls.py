from django.contrib import admin
from django.urls import path, include
from opportunities.account_views import set_language
urlpatterns = [path("admin/", admin.site.urls), path("i18n/setlang/", set_language, name="set_language"), path("", include("opportunities.urls"))]
