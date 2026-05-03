from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path("health/", health_check),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("literature/", include("apps.literature.urls")),
    path("assessment/", include("apps.assessment.urls")),
    path("summaries/", include("apps.summaries.urls")),
    path("claims/", include("apps.claims.urls")),
    path("safety/", include("apps.safety.urls")),
    path("kol/", include("apps.kol.urls")),
    path("medinfo/", include("apps.medinfo.urls")),
    path("engagement/", include("apps.engagement.urls")),
    path("ai-search/", include("apps.aisearch.urls")),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
