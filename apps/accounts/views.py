import json
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from .models import CURRENT_CONSENT_VERSION, PLATFORM_MODULES, Invitation, Tenant, User

logger = logging.getLogger(__name__)


@login_required
@require_POST
def set_view_mode(request):
    mode = request.POST.get("mode", "team")
    if mode not in ("team", "personal"):
        mode = "team"
    request.session["view_mode"] = mode
    return HttpResponseRedirect(request.POST.get("next", "/"))


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    user = request.user
    saved = False
    error = None

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = {}

        first_name = data.get("first_name", "").strip()
        last_name = data.get("last_name", "").strip()

        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=["first_name", "last_name"])
        saved = True

    return render(request, "accounts/profile.html", {
        "saved": saved,
        "error": error,
    })


# ── Platform Admin ────────────────────────────────────────────────────────────

def _require_admin(request):
    if not request.user.is_authenticated or not request.user.is_admin_role:
        raise PermissionDenied


@login_required
def admin_dashboard(request):
    _require_admin(request)
    users = User.all_objects.select_related("tenant").order_by("email")
    tenants = Tenant.objects.order_by("name")
    error = None
    success = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_user":
            email = request.POST.get("email", "").strip().lower()
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            role = request.POST.get("role", User.Role.MEDICAL_AFFAIRS)
            tenant_id = request.POST.get("tenant_id", "").strip()
            password = request.POST.get("password", "")

            if not email or not password:
                error = "Email and password are required."
            elif User.all_objects.filter(email__iexact=email).exists():
                error = f"A user with email {email} already exists."
            else:
                tenant = None
                if tenant_id:
                    try:
                        tenant = Tenant.objects.get(pk=tenant_id)
                    except Tenant.DoesNotExist:
                        error = "Selected tenant does not exist."

                if not error:
                    user = User.all_objects.create(
                        username=email,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        role=role,
                        tenant=tenant,
                    )
                    user.set_password(password)
                    user.save(update_fields=["password"])
                    logger.info("Admin %s created user %s", request.user.email, email)
                    success = f"User {email} created successfully."
                    users = User.all_objects.select_related("tenant").order_by("email")

        elif action == "delete_user":
            user_id = request.POST.get("user_id")
            target = get_object_or_404(User.all_objects, pk=user_id)
            if target == request.user:
                error = "You cannot delete your own account."
            else:
                email = target.email
                target.delete()
                logger.info("Admin %s deleted user %s", request.user.email, email)
                success = f"User {email} deleted."
                users = User.all_objects.select_related("tenant").order_by("email")

        elif action == "update_role":
            user_id = request.POST.get("user_id")
            new_role = request.POST.get("role")
            target = get_object_or_404(User.all_objects, pk=user_id)
            if new_role in User.Role.values:
                target.role = new_role
                target.save(update_fields=["role"])
                success = f"Role updated for {target.email}."
                users = User.all_objects.select_related("tenant").order_by("email")
            else:
                error = "Invalid role."

        elif action == "create_tenant":
            tenant_name = request.POST.get("tenant_name", "").strip()
            billing_email = request.POST.get("billing_email", "").strip()
            plan = request.POST.get("plan", Tenant.Plan.TRIAL)

            if not tenant_name:
                error = "Organisation name is required."
            else:
                slug = _unique_slug(slugify(tenant_name))
                Tenant.objects.create(
                    name=tenant_name,
                    slug=slug,
                    billing_email=billing_email,
                    plan=plan,
                    is_active=True,
                    trial_ends_at=timezone.now() + timedelta(days=14),
                )
                success = f'Organisation "{tenant_name}" created.'
                tenants = Tenant.objects.order_by("name")

        elif action == "toggle_tenant":
            tenant_id = request.POST.get("tenant_id")
            target_tenant = get_object_or_404(Tenant, pk=tenant_id)
            target_tenant.is_active = not target_tenant.is_active
            target_tenant.save(update_fields=["is_active"])
            state = "activated" if target_tenant.is_active else "suspended"
            success = f'Organisation "{target_tenant.name}" {state}.'
            tenants = Tenant.objects.order_by("name")

        elif action == "delete_tenant":
            tenant_id = request.POST.get("tenant_id")
            target_tenant = get_object_or_404(Tenant, pk=tenant_id)
            name = target_tenant.name
            target_tenant.delete()
            success = f'Organisation "{name}" deleted.'
            tenants = Tenant.objects.order_by("name")
            users = User.all_objects.select_related("tenant").order_by("email")

    return render(request, "accounts/admin_dashboard.html", {
        "platform_users": users,
        "tenants": tenants,
        "plan_choices": Tenant.Plan.choices,
        "role_choices": User.Role.choices,
        "error": error,
        "success": success,
    })


@login_required
def admin_edit_user(request, pk):
    _require_admin(request)
    target = get_object_or_404(User.all_objects, pk=pk)

    if request.method == "POST":
        target.first_name = request.POST.get("first_name", "").strip()
        target.last_name = request.POST.get("last_name", "").strip()
        new_role = request.POST.get("role", target.role)
        if new_role in User.Role.values:
            target.role = new_role

        # Collect per-module permission overrides
        perms = {}
        for module_key, _ in PLATFORM_MODULES:
            val = request.POST.get(f"mod_{module_key}", "")
            if val in ("editor", "viewer", "none"):
                perms[module_key] = val
        target.tab_permissions = perms
        target.save(update_fields=["first_name", "last_name", "role", "tab_permissions"])
        logger.info("Admin %s edited user %s", request.user.email, target.email)

        # Primary: empty panel to collapse it. OOB: updated user row.
        return render(request, "accounts/partials/user_row_oob.html", {
            "u": target,
            "role_choices": User.Role.choices,
            "request": request,
        })

    # GET: return the expanded edit panel content
    # Pre-compute (key, label, current_permission) so the template needs no custom filter
    tab_perms = target.tab_permissions or {}
    module_perms = [
        (key, label, tab_perms.get(key, ""))
        for key, label in PLATFORM_MODULES
    ]
    return render(request, "accounts/partials/user_edit_panel.html", {
        "u": target,
        "module_perms": module_perms,
        "role_choices": User.Role.choices,
    })


@login_required
@require_POST
def admin_delete_user(request, pk):
    _require_admin(request)
    target = get_object_or_404(User.all_objects, pk=pk)
    if target == request.user:
        messages.error(request, "You cannot delete your own account.")
        return HttpResponseRedirect(reverse("accounts_app:admin_dashboard"))
    email = target.email
    target.delete()
    logger.info("Admin %s deleted user %s", request.user.email, email)
    return HttpResponseRedirect(reverse("accounts_app:admin_dashboard"))


# ── Self-Signup ────────────────────────────────────────────────────────────────

def _unique_slug(base_slug):
    """Return base_slug, or base_slug-2, base_slug-3, ... until unique."""
    slug = base_slug
    counter = 2
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


@require_http_methods(["GET", "POST"])
def company_signup(request):
    if request.method == "GET":
        return render(request, "accounts/signup.html")

    company_name = request.POST.get("company_name", "").strip()
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip().lower()
    password1 = request.POST.get("password1", "")
    password2 = request.POST.get("password2", "")

    # Validation
    if not company_name:
        return render(request, "accounts/signup.html", {"error": "Company name is required.", "post": request.POST})
    if not email:
        return render(request, "accounts/signup.html", {"error": "Email address is required.", "post": request.POST})
    if not password1:
        return render(request, "accounts/signup.html", {"error": "Password is required.", "post": request.POST})
    if password1 != password2:
        return render(request, "accounts/signup.html", {"error": "Passwords do not match.", "post": request.POST})
    if len(password1) < 8:
        return render(request, "accounts/signup.html", {"error": "Password must be at least 8 characters.", "post": request.POST})
    if User.all_objects.filter(email__iexact=email).exists():
        return render(request, "accounts/signup.html", {"error": "An account with that email already exists.", "post": request.POST})
    if not request.POST.get("consent"):
        return render(request, "accounts/signup.html", {"error": "You must acknowledge the co-pilot terms to continue.", "post": request.POST})

    # Create tenant
    base_slug = slugify(company_name) or "tenant"
    slug = _unique_slug(base_slug)
    tenant = Tenant.objects.create(
        name=company_name,
        slug=slug,
        plan=Tenant.Plan.TRIAL,
        trial_ends_at=timezone.now() + timedelta(days=14),
        billing_email=email,
    )

    # Create admin user
    user = User.all_objects.create(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=User.Role.ADMIN,
        tenant=tenant,
        consent_version=CURRENT_CONSENT_VERSION,
    )
    user.set_password(password1)
    user.save(update_fields=["password"])

    # Mark email verified via allauth
    try:
        from allauth.account.models import EmailAddress
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
    except Exception:
        pass  # Non-fatal — verification can be done later

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    logger.info("New tenant signup: %s (slug=%s) by %s", company_name, slug, email)
    return HttpResponseRedirect("/dashboard/")


# ── Team Management ────────────────────────────────────────────────────────────

def _send_invite_email(invitation, request):
    accept_url = request.build_absolute_uri(
        reverse("accounts_app:invite_accept", args=[invitation.token])
    )
    send_mail(
        subject=f"You've been invited to join {invitation.tenant.name} on WattleLink",
        message=f"Accept your invitation: {accept_url}\n\nThis link expires in 7 days.",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wattlelink.com"),
        recipient_list=[invitation.email],
        fail_silently=True,
    )


@login_required
@require_http_methods(["GET", "POST"])
def team_view(request):
    if not request.user.is_admin_role:
        raise PermissionDenied

    tenant = request.user.tenant
    error = None
    success = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "invite":
            email = request.POST.get("email", "").strip().lower()
            role = request.POST.get("role", User.Role.MEDICAL_AFFAIRS)
            if not email:
                error = "Email address is required."
            elif role not in User.Role.values:
                error = "Invalid role."
            else:
                token = secrets.token_urlsafe(48)
                invitation = Invitation.objects.create(
                    tenant=tenant,
                    email=email,
                    role=role,
                    invited_by=request.user,
                    token=token,
                    expires_at=timezone.now() + timedelta(days=7),
                )
                _send_invite_email(invitation, request)
                logger.info("Invitation sent to %s by %s", email, request.user.email)
                success = f"Invitation sent to {email}."

        elif action == "remove_user":
            user_pk = request.POST.get("user_pk")
            try:
                target = User.all_objects.get(pk=user_pk, tenant=tenant)
            except User.DoesNotExist:
                error = "User not found."
            else:
                if target == request.user:
                    error = "You cannot remove yourself."
                else:
                    target.delete()
                    logger.info("User %s removed by %s", target.email, request.user.email)
                    success = f"{target.email} has been removed."

        elif action == "change_role":
            user_pk = request.POST.get("user_pk")
            new_role = request.POST.get("role")
            if new_role not in User.Role.values:
                error = "Invalid role."
            else:
                try:
                    target = User.all_objects.get(pk=user_pk, tenant=tenant)
                except User.DoesNotExist:
                    error = "User not found."
                else:
                    target.role = new_role
                    target.save(update_fields=["role"])
                    success = f"Role updated for {target.email}."

    team_members = User.all_objects.filter(tenant=tenant).order_by("email")
    pending_invitations = Invitation.objects.filter(tenant=tenant, accepted_at__isnull=True).order_by("-created_at")

    return render(request, "accounts/team.html", {
        "team_members": team_members,
        "pending_invitations": pending_invitations,
        "role_choices": User.Role.choices,
        "error": error,
        "success": success,
    })


@login_required
@require_POST
def send_invitation(request):
    if not request.user.is_admin_role:
        raise PermissionDenied

    tenant = request.user.tenant
    email = request.POST.get("email", "").strip().lower()
    role = request.POST.get("role", User.Role.MEDICAL_AFFAIRS)

    if not email or role not in User.Role.values:
        return render(request, "accounts/partials/invitation_row.html", {
            "error": "Invalid email or role.",
        })

    token = secrets.token_urlsafe(48)
    invitation = Invitation.objects.create(
        tenant=tenant,
        email=email,
        role=role,
        invited_by=request.user,
        token=token,
        expires_at=timezone.now() + timedelta(days=7),
    )
    _send_invite_email(invitation, request)
    logger.info("Invitation sent to %s by %s", email, request.user.email)
    return render(request, "accounts/partials/invitation_row.html", {
        "invitation": invitation,
    })


# ── Invitation Accept ──────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
def invite_accept(request, token):
    try:
        invitation = Invitation.objects.select_related("tenant").get(token=token)
    except Invitation.DoesNotExist:
        return render(request, "accounts/invite_accept.html", {
            "invitation_invalid": True,
            "error_message": "This invitation link is invalid.",
        })

    if invitation.is_accepted:
        return render(request, "accounts/invite_accept.html", {
            "invitation_invalid": True,
            "error_message": "This invitation has already been accepted.",
        })

    if invitation.is_expired:
        return render(request, "accounts/invite_accept.html", {
            "invitation_invalid": True,
            "error_message": "This invitation has expired. Please ask your admin to send a new one.",
        })

    if request.method == "GET":
        return render(request, "accounts/invite_accept.html", {"invitation": invitation})

    # POST — create the user
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    password1 = request.POST.get("password1", "")
    password2 = request.POST.get("password2", "")

    if password1 != password2:
        return render(request, "accounts/invite_accept.html", {
            "invitation": invitation,
            "error": "Passwords do not match.",
            "post": request.POST,
        })
    if len(password1) < 8:
        return render(request, "accounts/invite_accept.html", {
            "invitation": invitation,
            "error": "Password must be at least 8 characters.",
            "post": request.POST,
        })
    if not request.POST.get("consent"):
        return render(request, "accounts/invite_accept.html", {
            "invitation": invitation,
            "error": "You must acknowledge the co-pilot terms to continue.",
            "post": request.POST,
        })
    if User.all_objects.filter(email__iexact=invitation.email).exists():
        return render(request, "accounts/invite_accept.html", {
            "invitation_invalid": True,
            "error_message": "An account with that email already exists. Please sign in instead.",
        })

    user = User.all_objects.create(
        username=invitation.email,
        email=invitation.email,
        first_name=first_name,
        last_name=last_name,
        role=invitation.role,
        tenant=invitation.tenant,
        consent_version=CURRENT_CONSENT_VERSION,
    )
    user.set_password(password1)
    user.save(update_fields=["password"])

    try:
        from allauth.account.models import EmailAddress
        EmailAddress.objects.create(user=user, email=invitation.email, primary=True, verified=True)
    except Exception:
        pass

    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    logger.info("Invitation accepted by %s for tenant %s", invitation.email, invitation.tenant.name)
    return HttpResponseRedirect("/dashboard/")


# ── Consent ────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def consent_view(request):
    if request.method == "POST":
        if request.POST.get("consent") == "1":
            request.user.consent_version = CURRENT_CONSENT_VERSION
            request.user.save(update_fields=["consent_version"])
            next_url = request.GET.get("next", "/dashboard/")
            if not next_url.startswith("/"):
                next_url = "/dashboard/"
            return HttpResponseRedirect(next_url)
        return render(request, "accounts/consent.html", {"error": True})
    return render(request, "accounts/consent.html")
