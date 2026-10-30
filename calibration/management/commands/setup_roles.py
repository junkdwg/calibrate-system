from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from calibration.permissions import ROLES


class Command(BaseCommand):
    help = "Create the role groups (Technician / Reviewer / Approver)."

    def handle(self, *args, **opts):
        for name in ROLES:
            _, created = Group.objects.get_or_create(name=name)
            self.stdout.write(f"{'created' if created else 'exists'}: {name}")
