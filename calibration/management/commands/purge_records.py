"""Delete calibration records (e.g. test data). Dry-run by default, nothing is deleted without --apply.

The web app and /admin/ deliberately have NO delete button (approved sheets must not disappear).
This command is the controlled way for an administrator to clean up. ALWAYS back up first.

Examples
  python manage.py purge_records                                  # preview: drafts/pending only
  python manage.py purge_records --apply                          # delete drafts / waiting-review / waiting-approval
  python manage.py purge_records --equipment PHL-PH-01 --apply    # only one equipment
  python manage.py purge_records --before 2026-11-01 --apply      # only sheets dated before 1 Nov 2026
  python manage.py purge_records --include-approved --apply       # ALSO approved sheets (full test reset)
  python manage.py purge_records --id 12 --id 13 --include-approved --apply
Equipment, users, departments are never touched (except last_calibrated, see below).
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from calibration.models import AuditLog, CalibrationRecord, Equipment

PENDING = ["draft", "submitted", "reviewed"]


def latest_approved_date(eq):
    """Newest approved calibration date still on file for this equipment (None if none)."""
    dates = [r.cal_date for r in CalibrationRecord.objects.filter(
        status=CalibrationRecord.APPROVED, equipment=eq)]
    dates += [r.cal_date for r in CalibrationRecord.objects.filter(
        status=CalibrationRecord.APPROVED, equipment__isnull=True, rows__equipment=eq).distinct()]
    return max(dates) if dates else None


class Command(BaseCommand):
    help = "Delete calibration records (dry-run unless --apply). Back up first."

    def add_arguments(self, p):
        p.add_argument("--status", action="append", choices=[s for s, _ in CalibrationRecord.STATUS_CHOICES],
                       help="status to delete, repeatable (default: draft, submitted, reviewed)")
        p.add_argument("--include-approved", action="store_true",
                       help="allow deleting approved sheets (needed to remove approved test data)")
        p.add_argument("--before", help="only sheets with calibration date before YYYY-MM-DD")
        p.add_argument("--equipment", help="only sheets of this equipment code")
        p.add_argument("--id", type=int, action="append", help="only these record ids, repeatable")
        p.add_argument("--with-audit", action="store_true", help="also delete their audit-log rows")
        p.add_argument("--apply", action="store_true", help="really delete (otherwise preview only)")

    def handle(self, *args, **o):
        statuses = o["status"] or (PENDING + ["approved"] if o["include_approved"] else PENDING)
        if "approved" in statuses and not o["include_approved"]:
            raise CommandError("Approved sheets are protected: add --include-approved to delete them.")
        qs = CalibrationRecord.objects.filter(status__in=statuses)
        if o["before"]:
            try:
                qs = qs.filter(cal_date__lt=date.fromisoformat(o["before"]))
            except ValueError:
                raise CommandError("--before must look like 2026-11-01")
        if o["equipment"]:
            from django.db.models import Q
            qs = qs.filter(Q(equipment__code=o["equipment"]) | Q(rows__equipment__code=o["equipment"])).distinct()
        if o["id"]:
            qs = qs.filter(pk__in=o["id"])

        records = list(qs.select_related("equipment").order_by("id"))
        if not records:
            self.stdout.write("Nothing matches. No records would be deleted.")
            return
        for r in records:
            self.stdout.write(f"  #{r.pk:<5} {r.form_code:<10} {r.cal_date}  {r.get_status_display():<12} {r.title_text}")
        n_rows = sum(r.rows.count() for r in records)
        self.stdout.write(f"\n{len(records)} record(s), {n_rows} row(s) match "
                          f"(statuses: {', '.join(statuses)}).")

        if not o["apply"]:
            self.stdout.write(self.style.WARNING("DRY-RUN: nothing deleted. Back up, then add --apply."))
            return

        with transaction.atomic():
            # equipment whose last_calibrated was set by a sheet we are about to delete
            fix = {}
            for r in records:
                if r.status == CalibrationRecord.APPROVED:
                    for eq in r.calibrated_equipment():
                        fix.setdefault(eq.pk, (eq, set()))[1].add(r.cal_date)
            ids = [r.pk for r in records]
            if o["with_audit"]:
                AuditLog.objects.filter(record_id__in=ids).delete()
            CalibrationRecord.objects.filter(pk__in=ids).delete()      # rows cascade
            for eq, deleted_dates in fix.values():
                eq = Equipment.objects.get(pk=eq.pk)
                if eq.last_calibrated in deleted_dates:               # it came from a deleted sheet
                    eq.last_calibrated = latest_approved_date(eq)
                    eq.save(update_fields=["last_calibrated"])
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(ids)} record(s). Equipment due dates recomputed where needed."))
