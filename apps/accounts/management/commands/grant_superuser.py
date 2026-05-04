from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Grant is_superuser, is_staff, and role=ADMIN to a user by email"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)

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
        user.save()
        self.stdout.write(
            f"OK — {user.email}: is_superuser={user.is_superuser} is_staff={user.is_staff} role={user.role}"
        )
