from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import TenantUserManager, UnfilteredManager

CURRENT_CONSENT_VERSION = 1

PLATFORM_MODULES = [
    ("aisearch",      "AI Search"),
    ("dashboard",     "Dashboard"),
    ("search",        "Search & Ingest"),
    ("library",       "Literature Database"),
    ("assessment",    "Quality Assessment"),
    ("summaries",     "Summaries"),
    ("claims",        "Core Claims"),
    ("safety",        "Safety Signals"),
    ("kol_discovery", "KOL Discovery"),
    ("kol_directory", "Accepted KOLs"),
    ("medinfo",       "Medical Information"),
    ("engagement",    "Events"),
    ("commercial",    "Commercial Dashboard"),
]


class Tenant(models.Model):
    class Plan(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        STARTER = "STARTER", "Starter"
        PROFESSIONAL = "PROFESSIONAL", "Professional"
        ENTERPRISE = "ENTERPRISE", "Enterprise"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    billing_email = models.EmailField(blank=True)
    plan = models.CharField(max_length=20, choices=Plan.choices, default="TRIAL")
    is_active = models.BooleanField(default=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    max_users = models.PositiveIntegerField(default=10)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class User(AbstractUser):
    password = models.CharField(max_length=256)  # passlib pbkdf2_sha512 hashes exceed Django's default 128

    class Role(models.TextChoices):
        MEDICAL_LEAD = "MEDICAL_LEAD", "Medical Lead"       # MD/PharmD — certifies claims (MA Code §8)
        MEDICAL_AFFAIRS = "MEDICAL_AFFAIRS", "Medical Affairs"
        COMMERCIAL = "COMMERCIAL", "Commercial"
        ADMIN = "ADMIN", "Admin"
        EDITOR = "EDITOR", "Editor"
        VIEWER = "VIEWER", "Viewer"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEDICAL_AFFAIRS,
    )
    tab_permissions = models.JSONField(
        default=dict,
        help_text="Per-module overrides: {module_key: 'editor'|'viewer'|'none'}",
    )
    consent_version = models.PositiveIntegerField(default=0)

    objects = TenantUserManager()
    all_objects = UnfilteredManager()

    def __str__(self):
        return self.email or self.username

    @property
    def is_medical_lead(self):
        return self.role == self.Role.MEDICAL_LEAD

    @property
    def is_medical_affairs(self):
        return self.role in (self.Role.MEDICAL_AFFAIRS, self.Role.MEDICAL_LEAD)

    @property
    def can_certify_claims(self):
        return self.role == self.Role.MEDICAL_LEAD

    @property
    def is_commercial(self):
        return self.role == self.Role.COMMERCIAL

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_viewer(self):
        return self.role == self.Role.VIEWER

    @property
    def can_edit(self):
        return self.role not in (self.Role.VIEWER,)

    def get_module_permission(self, module_key):
        """Return effective permission for a module: 'editor', 'viewer', or 'none'."""
        if module_key in (self.tab_permissions or {}):
            return self.tab_permissions[module_key]
        if self.role in (self.Role.ADMIN, self.Role.MEDICAL_LEAD,
                         self.Role.MEDICAL_AFFAIRS, self.Role.EDITOR):
            return "editor"
        if self.role in (self.Role.VIEWER, self.Role.COMMERCIAL):
            return "viewer"
        return "editor"

    def get_initials(self):
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        if self.email:
            return self.email[0].upper()
        return "?"

    class Meta:
        ordering = ["email"]


class Invitation(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=User.Role.choices,
        default=User.Role.MEDICAL_AFFAIRS,
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    def __str__(self):
        return f"Invite {self.email} → {self.tenant.name}"
