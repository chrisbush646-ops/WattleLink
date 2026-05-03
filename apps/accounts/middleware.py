from django.shortcuts import redirect

from .managers import set_current_tenant

_CONSENT_EXEMPT_PREFIXES = (
    "/accounts/consent/",
    "/accounts/logout/",
    "/admin/",
    "/__debug__/",
)


class ConsentMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from .models import CURRENT_CONSENT_VERSION
            needs_consent = request.user.consent_version < CURRENT_CONSENT_VERSION
            if needs_consent and not any(request.path.startswith(p) for p in _CONSENT_EXEMPT_PREFIXES):
                return redirect(f"/accounts/consent/?next={request.path}")
        return self.get_response(request)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None
        if request.user.is_authenticated and hasattr(request.user, "tenant"):
            tenant = request.user.tenant
        request.tenant = tenant
        set_current_tenant(tenant)

        # Flag inactive tenants so views can respond appropriately
        request.tenant_inactive = bool(tenant and not tenant.is_active)

        response = self.get_response(request)

        set_current_tenant(None)
        return response
