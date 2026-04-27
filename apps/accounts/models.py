from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import TenantUserManager, UnfilteredManager


class Tenant(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class User(AbstractUser):
    class Role(models.TextChoices):
        MEDICAL_AFFAIRS = "MEDICAL_AFFAIRS", "Medical Affairs"
        COMMERCIAL = "COMMERCIAL", "Commercial"
        ADMIN = "ADMIN", "Admin"

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

    objects = TenantUserManager()
    all_objects = UnfilteredManager()

    def __str__(self):
        return self.email or self.username

    @property
    def is_medical_affairs(self):
        return self.role == self.Role.MEDICAL_AFFAIRS

    @property
    def is_commercial(self):
        return self.role == self.Role.COMMERCIAL

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    def get_initials(self):
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        if self.email:
            return self.email[0].upper()
        return "?"

    class Meta:
        ordering = ["email"]
