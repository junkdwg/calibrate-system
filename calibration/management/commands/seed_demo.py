import secrets

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from calibration.models import Department, Equipment
from calibration.permissions import APPROVER, REVIEWER, TECHNICIAN

DEPTS = [("EXT", "Extrusion"), ("CPD", "Compound"), ("PHL", "Physical Lab"),
         ("CHL", "Chemical Lab"), ("MTN", "Maintenance"), ("NRT2", "Office NRT-2")]
# Codes below are PLACEHOLDERS - replace with the real equipment codes on import.
PH_METERS = [("PHL-PH-01", "เครื่องวัดค่า PH", "EUTECH / PH700", "PHL"),
             ("PHL-PH-02", "เครื่องวัดค่า PH", "EUTECH / PH700", "PHL"),
             ("CHL-PH-01", "เครื่องวัดค่า PH", "EUTECH / PH1710", "CHL"),
             ("CHL-PH-02", "เครื่องวัดค่า PH", "EUTECH / PH1710", "CHL")]
USERS = [("tech1", TECHNICIAN), ("reviewer1", REVIEWER), ("approver1", APPROVER)]


class Command(BaseCommand):
    help = "Create demo departments, pH meters and users (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="allow when DEBUG is off")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("Demo data is for development. Use --force to override.")
        call_command("setup_roles")
        depts = {c: Department.objects.get_or_create(code=c, defaults={"name": n})[0]
                 for c, n in DEPTS}
        for code, name, model, d in PH_METERS:
            Equipment.objects.get_or_create(code=code, defaults=dict(
                name=name, brand_model=model, department=depts[d], form_code="F-MTN-025"))
        for username, role in USERS:
            if not User.objects.filter(username=username).exists():
                pwd = secrets.token_urlsafe(12)
                u = User.objects.create_user(username, password=pwd)
                u.groups.add(Group.objects.get(name=role))
                self.stdout.write(f"user {username} / {pwd}   ({role})")
