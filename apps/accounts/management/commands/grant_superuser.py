from django.core.management.base import BaseCommand
from apps.accounts.models import Tenant, User


class Command(BaseCommand):
    help = "Grant is_superuser, is_staff, role=ADMIN to a user; create and assign a tenant if missing"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        parser.add_argument("--tenant-name", default="WattleLink", type=str)
        parser.add_argument("--tenant-slug", default="wattlelink", type=str)

    def handle(self, *args, **options):
        email = options["email"]
        try:
            user = User.all_objects.get(email=email)
        except User.DoesNotExist:
            self.stderr.write(f"No user found with email: {email}")
            return

        user.is_superuser = True
        user.is_staff = True
        user.role = User.Role.ADMIN

        if not user.tenant_id:
            tenant, created = Tenant.objects.get_or_create(
                slug=options["tenant_slug"],
                defaults={"name": options["tenant_name"], "plan": Tenant.Plan.ENTERPRISE},
            )
            user.tenant = tenant
            action = "created" if created else "found existing"
            self.stdout.write(f"Tenant {action}: {tenant.name} ({tenant.slug})")

        user.save()
        self.stdout.write(
            f"OK — {user.email}: is_superuser={user.is_superuser} "
            f"is_staff={user.is_staff} role={user.role} tenant={user.tenant}"
        )
