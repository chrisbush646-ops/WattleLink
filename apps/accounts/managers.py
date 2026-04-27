import threading
from django.contrib.auth.models import UserManager
from django.db import models

_thread_locals = threading.local()


def set_current_tenant(tenant):
    _thread_locals.tenant = tenant


def get_current_tenant():
    return getattr(_thread_locals, "tenant", None)


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager):
    """
    Auto-scopes querysets to the current request's tenant.
    Falls back to unscoped if no tenant is set (e.g. management commands).
    Assign as `objects` on any model that has a `tenant` ForeignKey.
    """

    def get_queryset(self):
        qs = TenantQuerySet(self.model, using=self._db)
        tenant = get_current_tenant()
        if tenant is not None:
            return qs.filter(tenant=tenant)
        return qs


class TenantUserManager(UserManager):
    """
    TenantManager for the User model. Extends Django's UserManager so
    create_user / create_superuser keep working, while get_queryset
    applies tenant scoping when a tenant is active on the thread.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is not None:
            return qs.filter(tenant=tenant)
        return qs


class UnfilteredManager(models.Manager):
    """Cross-tenant access for admin and internal tooling."""

    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)
