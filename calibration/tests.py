from datetime import date, timedelta
from decimal import Decimal
import zipfile
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from . import dashboard as dash
from . import exporter
from .models import CalibrationRecord, CalibrationRow, Department, Equipment


def make_user(name, role):
    u = User.objects.create_user(name, password="x" * 12)
    u.groups.add(Group.objects.get(name=role))
    return u


class Base(TestCase):
    def setUp(self):
        call_command("setup_roles")
        d = Department.objects.create(code="PHL", name="Physical Lab")
        self.eq = Equipment.objects.create(code="PHL-PH-01", name="pH meter",
                                           brand_model="EUTECH / PH700", department=d,
                                           form_code="F-MTN-025")
        self.tech = make_user("tech", "Technician")
        self.rev = make_user("rev", "Reviewer")
        self.app = make_user("app", "Approver")
        self.rec = CalibrationRecord.objects.create(form_code="F-MTN-025", equipment=self.eq,
                                                    cal_date=date(2026, 10, 1),
                                                    tolerance=Decimal("0.05"), calibrator=self.tech)
        CalibrationRow.objects.create(record=self.rec, std_value=Decimal("4.01"),
                                      before_reading=Decimal("4.10"), after_reading=Decimal("4.02"))
        CalibrationRow.objects.create(record=self.rec, std_value=Decimal("7.00"),
                                      before_reading=Decimal("7.03"), after_reading=Decimal("7.01"))

    def act(self, user, action):
        self.client.force_login(user)
        return self.client.post(reverse("record_action", args=[self.rec.pk, action]))


class CalcTests(Base):
    def test_errors_and_pass(self):
        r1, r2 = self.rec.rows.all()
        self.assertEqual(r1.before_error, Decimal("0.09"))
        self.assertFalse(r1.before_pass)          # 0.09 > 0.05
        self.assertTrue(r1.after_pass)            # 0.01
        self.assertTrue(r2.before_pass)
        self.assertTrue(self.rec.overall_pass)    # uses after-adjust values

    def test_boundary_is_pass(self):
        row = CalibrationRow(record=self.rec, std_value=Decimal("7.00"), before_reading=Decimal("7.05"))
        self.assertTrue(row.before_pass)


class WorkflowTests(Base):
    def test_full_flow_and_lock(self):
        self.act(self.tech, "submit")
        self.rec.refresh_from_db(); self.assertEqual(self.rec.status, "submitted")
        self.act(self.rev, "review")
        self.act(self.app, "approve")
        self.rec.refresh_from_db(); self.eq.refresh_from_db()
        self.assertEqual(self.rec.status, "approved")
        self.assertEqual(self.eq.last_calibrated, date(2026, 10, 1))
        # locked: technician cannot edit
        self.client.force_login(self.tech)
        r = self.client.get(reverse("record_edit", args=[self.rec.pk]))
        self.assertEqual(r.status_code, 302)

    def test_wrong_role_blocked(self):
        self.act(self.tech, "submit")
        self.act(self.tech, "review")            # technician cannot review
        self.rec.refresh_from_db(); self.assertEqual(self.rec.status, "submitted")

    def test_segregation_of_duties(self):
        both = make_user("both", "Technician")
        both.groups.add(Group.objects.get(name="Reviewer"))
        self.rec.calibrator = both; self.rec.save()
        self.act(both, "submit")
        self.act(both, "review")                 # own work: blocked
        self.rec.refresh_from_db(); self.assertEqual(self.rec.status, "submitted")

    def test_reject_returns_to_draft(self):
        self.act(self.tech, "submit")
        self.act(self.rev, "reject")
        self.rec.refresh_from_db(); self.assertEqual(self.rec.status, "draft")

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse("record_list"))
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("record_download", args=[self.rec.pk, "xlsx"]))
        self.assertEqual(r.status_code, 302)

    def test_action_requires_post(self):
        self.client.force_login(self.tech)
        r = self.client.get(reverse("record_action", args=[self.rec.pk, "submit"]))
        self.assertEqual(r.status_code, 405)


class ExportTests(Base):
    def test_xlsx_filled(self):
        ws = load_workbook(BytesIO(exporter.build_xlsx(self.rec))).worksheets[0]
        self.assertIn("PHL-PH-01", ws["I5"].value)
        self.assertEqual(ws["C9"].value, "4.01")
        self.assertEqual(ws["G9"].value, "0.09")
        self.assertEqual(ws["H9"].value, "ไม่ผ่าน")
        self.assertEqual(ws["K9"].value, "ผ่าน")

    def test_single_copy_and_font(self):
        ws = load_workbook(BytesIO(exporter.build_xlsx(self.rec))).worksheets[0]
        self.assertLessEqual(ws.max_row, 21)               # second copy removed
        self.assertEqual(ws.print_area, "'F-MTN-025ฟอร์ม'!$B$2:$K$21")
        for ref in ("B4", "C9", "I5", "C18"):
            f = ws[ref].font
            self.assertEqual((f.name, f.sz), ("AngsanaUPC", 16), ref)

    def test_download_view(self):
        self.client.force_login(self.tech)
        r = self.client.get(reverse("record_download", args=[self.rec.pk, "xlsx"]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])


class UiTests(Base):
    def test_create_via_form(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("record_create")).status_code, 200)
        data = {
            "equipment": self.eq.pk, "cal_date": "2026-10-16", "tolerance": "0.05", "note": "",
            "t1-TOTAL_FORMS": "8", "t1-INITIAL_FORMS": "0",
            "t1-MIN_NUM_FORMS": "1", "t1-MAX_NUM_FORMS": "8",
            "t1-0-std_value": "4.01", "t1-0-before_reading": "4.03", "t1-0-after_reading": "4.01",
        }
        for i in range(1, 8):
            for f in ("std_value", "std_instr_error", "before_reading", "after_reading"):
                data[f"t1-{i}-{f}"] = ""
        r = self.client.post(reverse("record_create"), data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and [f.errors for f in r.context["formsets"]])
        rec = CalibrationRecord.objects.latest("id")
        self.assertEqual(rec.rows.count(), 1)
        self.assertEqual(self.client.get(reverse("record_detail", args=[rec.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("record_list")).status_code, 200)

    def test_pH_out_of_range_rejected(self):
        self.client.force_login(self.tech)
        data = {"equipment": self.eq.pk, "cal_date": "2026-10-16", "tolerance": "0.05",
                "t1-TOTAL_FORMS": "1", "t1-INITIAL_FORMS": "0",
                "t1-MIN_NUM_FORMS": "1", "t1-MAX_NUM_FORMS": "8",
                "t1-0-std_value": "15", "t1-0-before_reading": "7"}
        r = self.client.post(reverse("record_create"), data)
        self.assertEqual(r.status_code, 200)   # re-rendered with errors


class LimitTests(Base):
    def test_max_two_technicians(self):
        make_user("tech2", "Technician")                   # 2nd technician: ok (tech is 1st)
        u3 = User.objects.create_user("u3", password="x" * 12)
        with self.assertRaises(ValidationError), transaction.atomic():
            u3.groups.add(Group.objects.get(name="Technician"))
        with self.assertRaises(ValidationError), transaction.atomic():   # reverse path too
            Group.objects.get(name="Technician").user_set.add(u3)
        self.assertEqual(User.objects.filter(groups__name="Technician").count(), 2)

    def test_superuser_cannot_enter_data(self):
        su = User.objects.create_superuser("root", password="x" * 12)
        self.client.force_login(su)
        r = self.client.get(reverse("record_create"))
        self.assertEqual(r.status_code, 302)               # redirected: no Technician role

    def test_admin_form_blocks_third_technician(self):
        make_user("tech2", "Technician")
        su = User.objects.create_superuser("root", password="x" * 12)
        u3 = User.objects.create_user("u3", password="x" * 12)
        self.client.force_login(su)
        r = self.client.post(reverse("admin:auth_user_change", args=[u3.pk]), {
            "username": "u3", "password": u3.password, "is_active": "on",
            "groups": [Group.objects.get(name="Technician").pk],
            "date_joined_0": "2026-10-01", "date_joined_1": "00:00:00"})
        self.assertEqual(r.status_code, 200)               # form re-shown with error
        self.assertFalse(u3.groups.exists())


class DashboardTests(Base):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        d = self.eq.department
        self.never = Equipment.objects.create(code="N", name="never", department=d, form_code="F-MTN-025")
        self.late = Equipment.objects.create(code="L", name="late", department=d, form_code="F-MTN-025",
                                             last_calibrated=self.today - timedelta(days=400))
        self.ok = Equipment.objects.create(code="K", name="ok", department=d, form_code="F-MTN-025",
                                           last_calibrated=self.today - timedelta(days=5))
        self.eq.last_calibrated = None; self.eq.save()

    def states(self):
        """equipment code -> state of its FIRST round"""
        out = {}
        for i in dash.build_plan(self.today.year):
            out.setdefault(i["eq"].code, i["state"])
        return out

    def test_states(self):
        st = self.states()
        self.assertEqual(st["N"], "never")
        self.assertEqual(st["L"], "overdue")
        self.assertNotIn("K", st)                          # next due is next year

    def test_done_when_approved_this_year(self):
        self.rec.status = "approved"; self.rec.cal_date = self.today; self.rec.save()
        self.eq.last_calibrated = self.today; self.eq.save()        # what the approve action does
        self.assertEqual(self.states()["PHL-PH-01"], "done")
        s = dash.summarize(dash.build_plan(self.today.year))
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["total"], s["done"] + s["pending"])

    def test_pages_render(self):
        self.client.force_login(self.tech)
        for url in (reverse("dashboard"), reverse("dashboard") + "?dept=PHL",
                    reverse("dashboard") + "?year=abc", reverse("record_list")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_chart_buckets(self):
        c = dash.monthly_chart(dash.build_plan(self.today.year))
        self.assertEqual(len(c), 13)
        self.assertEqual(sum(b["total"] for b in c), len(dash.build_plan(self.today.year)))


class FullFormTests(Base):
    def _drawing(self, data):
        z = zipfile.ZipFile(BytesIO(data))
        x = z.read("xl/drawings/drawing1.xml").decode()
        return x.count("<xdr:pic>"), x.count("<xdr:sp ") + x.count("<xdr:sp>"), z

    def test_tensile_form_registered_whole(self):
        from .formdefs import FORMS
        f = FORMS["F-MTN-015"]
        self.assertEqual((f.copy_start_row, f.print_area), (0, "B2:T40"))
        self.assertTrue(f.implemented)
        data = exporter.build_blank_xlsx("F-MTN-015")
        ws = load_workbook(BytesIO(data)).worksheets[0]
        self.assertGreaterEqual(ws.max_row, 40)            # nothing cut
        self.assertEqual(ws["B8"].value, "น้ำหนัก")         # table 1 (Kg.)
        self.assertEqual(ws["B21"].value, "ระยะ")            # table 2 (mm.)
        self.assertEqual(ws["O37"].value, "ผู้อนุมัติผล")     # signatures
        self.assertEqual(ws.print_area, "'F-MTN-015ฟอร์ม'!$B$2:$T$40")
        pics, shapes, _ = self._drawing(data)
        self.assertEqual((pics, shapes), (1, 3))           # logo + 3 check boxes kept

    def test_ph_form_keeps_logo_and_boxes_single_copy(self):
        pics, shapes, z = self._drawing(exporter.build_xlsx(self.rec))
        self.assertEqual((pics, shapes), (1, 3))           # one copy only, but not stripped bare
        self.assertTrue(any(n.startswith("xl/media/") for n in z.namelist()))


class GuessFormsTests(Base):
    def test_dry_run_and_apply(self):
        from io import StringIO
        d = self.eq.department
        scale = Equipment.objects.create(code="S1", name="Digital Weight Scale", brand_model="OHAUS / AR2140",
                                         department=d, form_code="F-MTN-025")
        oven = Equipment.objects.create(code="O1", name="ตู้อบ AGING", brand_model="Memmert", department=d,
                                        form_code="F-MTN-025")
        odd = Equipment.objects.create(code="X1", name="STEEL RULER", department=d, form_code="F-MTN-025")
        call_command("guess_forms", stdout=StringIO())            # dry-run: nothing saved
        scale.refresh_from_db(); self.assertEqual(scale.form_code, "F-MTN-025")
        call_command("guess_forms", "--apply", stdout=StringIO())
        for e in (scale, oven, odd, self.eq):
            e.refresh_from_db()
        self.assertEqual(scale.form_code, "F-MTN-014")
        self.assertEqual(oven.form_code, "F-MTN-030")
        self.assertEqual(odd.form_code, "F-MTN-025")              # unknown: untouched
        self.assertEqual(self.eq.form_code, "F-MTN-025")          # real pH meter stays


class HealthTests(TestCase):
    def test_healthz_open_and_ok(self):
        r = self.client.get(reverse("healthz"), HTTP_HOST="localhost")
        self.assertEqual((r.status_code, r.content), (200, b"ok"))

    def test_healthz_exposes_nothing_else(self):
        r = self.client.get(reverse("record_list"))      # still needs login
        self.assertEqual(r.status_code, 302)


class MoreFormsTests(Base):
    """F-MTN-014 (scale) and F-MTN-016 (cutter) use the same reading-table engine as 025."""

    def _record(self, code, rows, tol="0.5"):
        eq = Equipment.objects.create(code=f"EQ-{code}", name="เครื่องทดสอบ", brand_model="X / 1",
                                      serial_no="SN1", department=self.eq.department, form_code=code)
        rec = CalibrationRecord.objects.create(form_code=code, equipment=eq, cal_date=date(2026, 10, 1),
                                               tolerance=Decimal(tol), calibrator=self.tech)
        for std, before, after in rows:
            CalibrationRow.objects.create(record=rec, std_value=Decimal(std),
                                          before_reading=Decimal(before), after_reading=Decimal(after))
        return rec

    def test_014_export(self):
        rec = self._record("F-MTN-014", [("100", "100.8", "100.2"), ("200", "199.9", "200.1")])
        data = exporter.build_xlsx(rec)
        ws = load_workbook(BytesIO(data)).worksheets[0]
        self.assertLessEqual(ws.max_row, 27)                         # only one copy
        self.assertIn("EQ-F-MTN-014", ws["M5"].value)
        self.assertEqual((ws["D9"].value, ws["F9"].value, ws["H9"].value, ws["J9"].value),
                         ("100.00", "100.80", "0.80", "ไม่ผ่าน"))    # 0.8 > tol 0.5
        self.assertEqual((ws["L9"].value, ws["N9"].value, ws["P9"].value), ("100.20", "0.20", "ผ่าน"))
        self.assertEqual(ws["C10"].value, 2)
        self.assertEqual(ws["D26"].value, "tech")                    # calibrator name on signature line
        self.assertIn("ผลรวม: ผ่าน", ws["C24"].value)                # after-adjust values decide
        self.assertEqual((ws["C9"].font.name, ws["C9"].font.sz), ("AngsanaUPC", 16))

    def test_016_export(self):
        rec = self._record("F-MTN-016", [("98.23", "98.25", "98.23")], tol="0.05")
        ws = load_workbook(BytesIO(exporter.build_xlsx(rec))).worksheets[0]
        self.assertLessEqual(ws.max_row, 20)
        self.assertEqual((ws["B8"].value, ws["D8"].value, ws["E8"].value, ws["F8"].value),
                         ("98.23", "98.25", "0.02", "ผ่าน"))
        self.assertIn("mm.", ws["A16"].value)

    def test_logo_and_boxes_kept(self):
        for code in ("F-MTN-014", "F-MTN-016"):
            rec = self._record(code, [("1", "1", "1")])
            z = zipfile.ZipFile(BytesIO(exporter.build_xlsx(rec)))
            x = z.read("xl/drawings/drawing1.xml").decode()
            self.assertEqual(x.count("<xdr:pic>"), 1, code)           # logo (copy 2's removed)
            self.assertGreaterEqual(x.count("<xdr:sp>") + x.count("<xdr:sp "), 1, code)

    def test_picker_and_tolerance_required(self):
        eq = Equipment.objects.create(code="W1", name="scale", department=self.eq.department,
                                      form_code="F-MTN-014")
        self.client.force_login(self.tech)
        r = self.client.get(reverse("record_create"))                 # step 1: picker
        self.assertContains(r, "เลือกเครื่องมือ")
        self.assertContains(r, "F-MTN-014")
        self.assertEqual(self.client.get(reverse("record_create") + f"?equipment={eq.pk}").status_code, 200)
        post = {"equipment": eq.pk, "cal_date": "2026-10-16", "tolerance": "",   # tolerance missing
                "t1-TOTAL_FORMS": "1", "t1-INITIAL_FORMS": "0",
                "t1-MIN_NUM_FORMS": "1", "t1-MAX_NUM_FORMS": "15",
                "t1-0-std_value": "100", "t1-0-before_reading": "100.1"}
        r = self.client.post(reverse("record_create"), post)
        self.assertEqual(r.status_code, 200)                          # no hidden default for 014
        post["tolerance"] = "0.5"
        r = self.client.post(reverse("record_create"), post)
        self.assertEqual(r.status_code, 302)
        rec = CalibrationRecord.objects.latest("id")
        self.assertEqual(rec.equipment_id, eq.pk)
        self.assertEqual(self.client.get(reverse("record_detail", args=[rec.pk])).status_code, 200)

    def test_inactive_equipment_cannot_be_used(self):
        eq = Equipment.objects.create(code="T1", name="old", department=self.eq.department,
                                      form_code="F-MTN-014", active=False)
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("record_create") + f"?equipment={eq.pk}").status_code, 404)

    def test_fmt_dec(self):
        from .utils import fmt_dec
        self.assertEqual([fmt_dec(Decimal(x)) for x in ("7.0000", "0.0900", "5000", "98.2300", "0.125")],
                         ["7.00", "0.09", "5000.00", "98.23", "0.125"])


# ======================= v3: rules for every form, months, rounds, external =======================
from unittest.mock import patch

from .utils import add_months


def D(x):
    return Decimal(str(x))


class RuleTests(Base):
    """Error = standard's own error + deviation; pass when |error| <= tolerance."""

    def make(self, code, tol="0.05", tol2=None, **kw):
        eq = Equipment.objects.create(code=f"R-{code}", name="x", department=self.eq.department,
                                      form_code=code)
        return CalibrationRecord.objects.create(
            form_code=code, equipment=None if code == "F-MTN-029" else eq, calibrator=self.tech,
            cal_date=date(2026, 10, 27), tolerance=D(tol), tolerance2=D(tol2) if tol2 else None, **kw)

    def test_nominal_adds_standard_error(self):             # 014 / 016 / 025 / 015 table 1
        rec = self.make("F-MTN-014", "0.5")
        row = CalibrationRow.objects.create(record=rec, std_value=D(100), std_instr_error=D("0.3"),
                                            before_reading=D("100.1"), after_reading=D("100.3"))
        self.assertEqual(row.before_error, D("0.4"))        # 0.3 + (100.1 - 100)
        self.assertTrue(row.before_pass)
        self.assertEqual(row.after_error, D("0.6"))         # 0.3 + 0.3 > 0.5
        self.assertFalse(row.after_pass)

    def test_015_distance_offset_76(self):                   # std 200 -> expect 276 on the ruler
        rec = self.make("F-MTN-015", "0.1", "1")
        ok = CalibrationRow.objects.create(record=rec, table_no=2, std_value=D(200), std_instr_error=D(0),
                                           before_reading=D(200), before_measured=D(276))
        self.assertEqual(ok.before_error, D(0))
        self.assertTrue(ok.before_pass)
        bad = CalibrationRow.objects.create(record=rec, table_no=2, std_value=D(200), std_instr_error=D(0),
                                            before_reading=D(200), before_measured=D(278))
        self.assertEqual(bad.before_error, D(2))
        self.assertFalse(bad.before_pass)                    # tolerance2 = 1 is used for table 2
        w = CalibrationRow.objects.create(record=rec, table_no=1, std_value=D(5), std_instr_error=D("0.01"),
                                          before_reading=D(5))
        self.assertEqual(w.before_error, D("0.01"))          # 0.01 + 0, tolerance (table 1) = 0.1
        self.assertTrue(w.before_pass)

    def test_026_five_points_user_example(self):            # 0.033 + 0.001 = 0.034
        rec = self.make("F-MTN-026", "0.05")
        row = CalibrationRow.objects.create(
            record=rec, std_value=D(100), std_instr_error=D("0.033"),
            before_reading=D("100.001"), before_p2=D("100.000"), before_p3=D("99.999"),
            before_p4=D("100.000"), before_p5=D("100.000"))
        self.assertEqual(row.before_error, D("0.034"))
        self.assertTrue(row.before_pass)
        row.before_p4 = D("100.030")                          # worst point decides: 0.033 + 0.030
        self.assertEqual(row.before_error, D("0.063"))
        self.assertFalse(row.before_pass)

    def test_030_reading_vs_measured_no_standard_error(self):
        rec = self.make("F-MTN-030", "2")
        row = CalibrationRow.objects.create(record=rec, before_reading=D(80), before_measured=D(77.5))
        self.assertEqual(row.before_error, D("2.5"))
        self.assertFalse(row.before_pass)
        row.after_reading, row.after_measured = D(80), D(79)
        row.save()
        self.assertTrue(row.after_pass)
        self.assertTrue(rec.overall_pass)                     # after-adjust decides

    def test_029_adds_thermometer_error(self):
        rec = self.make("F-MTN-029", "2")
        row = CalibrationRow.objects.create(record=rec, equipment=self.eq, std_instr_error=D("0.5"),
                                            before_reading=D(100), before_measured=D(98.8))
        self.assertEqual(row.before_error, D("1.7"))
        self.assertTrue(row.before_pass)


class MonthsAndRoundsTests(Base):
    def test_add_months_same_day(self):
        self.assertEqual(add_months(date(2026, 10, 27), 2), date(2026, 12, 27))
        self.assertEqual(add_months(date(2026, 10, 27), 6), date(2027, 4, 27))
        self.assertEqual(add_months(date(2026, 10, 27), 12), date(2027, 10, 27))
        self.assertEqual(add_months(date(2026, 10, 27), 24), date(2028, 10, 27))
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))   # month-end clamp

    def test_equipment_next_due_in_months(self):
        self.eq.last_calibrated, self.eq.interval_months = date(2026, 10, 27), 2
        self.assertEqual(self.eq.next_due, date(2026, 12, 27))
        self.eq.interval_months = 6
        self.assertEqual(self.eq.next_due, date(2027, 4, 27))

    def test_rounds_remaining_in_year(self):
        today = date(2026, 10, 27)
        d = self.eq.department
        mk = lambda c, m, last: Equipment.objects.create(          # noqa: E731
            code=c, name=c, department=d, form_code="F-MTN-014", interval_months=m, last_calibrated=last)
        mk("M1", 1, date(2026, 10, 20))     # next 20/11, 20/12 -> 2 left; + 1 done below = 3 rounds
        mk("M3", 3, date(2026, 6, 27))      # next 27/9 overdue -> 1 round now, next would be 2027
        mk("Y1", 12, date(2025, 12, 1))     # next 1/12/2026 -> 1 round
        mk("Y2", 24, date(2026, 5, 1))      # next 2028 -> nothing this year
        self.eq.last_calibrated = None; self.eq.save()
        m1 = Equipment.objects.get(code="M1")
        rec = CalibrationRecord.objects.create(form_code="F-MTN-014", equipment=m1, calibrator=self.tech,
                                               cal_date=date(2026, 10, 20), tolerance=D(1),
                                               status="approved")
        with patch("django.utils.timezone.localdate", return_value=today):
            items = dash.build_plan(2026)
        by = {}
        for i in items:
            by.setdefault(i["eq"].code, []).append(i)
        self.assertEqual([(i["state"], i["round_no"], i["rounds_total"], i["remaining"]) for i in by["M1"]],
                         [("soon", 2, 3, 2), ("pending", 3, 3, 2), ("done", 1, 3, 2)])
        self.assertEqual(sorted(i["round_no"] for i in by["M1"]), [1, 2, 3])
        self.assertTrue(all(i["rounds_total"] == 3 for i in by["M1"]))
        self.assertEqual(len(by["M3"]), 1)
        self.assertEqual(by["M3"][0]["state"], "overdue")
        self.assertEqual(len(by["Y1"]), 1)
        self.assertNotIn("Y2", by)
        s = dash.summarize(items)
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["total"], s["done"] + s["pending"])
        self.assertGreaterEqual(s["equipment"], 3)


class ExternalAndBatchTests(Base):
    def test_external_calibration_flow(self):
        eq = Equipment.objects.create(code="W-EXT", name="ลูกตุ้มน้ำหนัก", department=self.eq.department,
                                      form_code="EXT-CAL", interval_months=12)
        self.client.force_login(self.tech)
        post = {"equipment": eq.pk, "cal_date": "2026-10-27", "lab_name": "NIMT",
                "cert_no": "CAL-2026-001", "ext_result": "pass", "note": ""}
        r = self.client.post(reverse("record_create"), post)
        self.assertEqual(r.status_code, 302)
        rec = CalibrationRecord.objects.latest("id")
        self.assertEqual((rec.form_code, rec.lab_name, rec.overall_pass), ("EXT-CAL", "NIMT", True))
        self.assertEqual(self.client.post(reverse("record_create"), {**post, "cert_no": ""}).status_code, 200)
        self.act_on(rec, self.tech, "submit"); self.act_on(rec, self.rev, "review"); self.act_on(rec, self.app, "approve")
        eq.refresh_from_db()
        self.assertEqual(eq.last_calibrated, date(2026, 10, 27))
        self.assertEqual(eq.next_due, date(2027, 10, 27))
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("record_detail", args=[rec.pk])).status_code, 200)
        r = self.client.get(reverse("record_download", args=[rec.pk, "pdf"]))
        self.assertEqual(r.status_code, 302)                  # no company form for external

    def act_on(self, rec, user, action):
        self.client.force_login(user)
        self.client.post(reverse("record_action", args=[rec.pk, action]))
        rec.refresh_from_db()

    def test_batch_029_create_approve_export(self):
        d = self.eq.department
        e1 = Equipment.objects.create(code="OV-1", name="เตาอบล่าง 1", department=d, form_code="F-MTN-029",
                                      interval_months=3)
        e2 = Equipment.objects.create(code="OV-2", name="เตาอบล่าง 2", department=d, form_code="F-MTN-029",
                                      interval_months=3)
        self.client.force_login(self.tech)
        r = self.client.get(reverse("record_create") + f"?equipment={e1.pk}")      # redirect to batch form
        self.assertEqual(r.status_code, 302)
        self.assertIn("form=F-MTN-029", r["Location"])
        self.assertEqual(self.client.get(r["Location"]).status_code, 200)
        data = {"form": "F-MTN-029", "cal_date": "2026-10-27", "tolerance": "2", "note": "",
                "t1-TOTAL_FORMS": "2", "t1-INITIAL_FORMS": "0", "t1-MIN_NUM_FORMS": "1",
                "t1-MAX_NUM_FORMS": "12",
                "t1-0-equipment": e1.pk, "t1-0-std_instr_error": "0.5", "t1-0-before_reading": "100",
                "t1-0-before_measured": "98.8", "t1-0-after_reading": "100", "t1-0-after_measured": "99.8",
                "t1-0-remark": "ok",
                "t1-1-equipment": e2.pk, "t1-1-std_instr_error": "0.5", "t1-1-before_reading": "100",
                "t1-1-before_measured": "99.5"}
        self.assertEqual(self.client.post(reverse("record_create"), data).status_code, 302)
        rec = CalibrationRecord.objects.latest("id")
        self.assertIsNone(rec.equipment)
        self.assertEqual(rec.rows.count(), 2)
        self.act_on(rec, self.tech, "submit"); self.act_on(rec, self.rev, "review"); self.act_on(rec, self.app, "approve")
        for e in (e1, e2):
            e.refresh_from_db()
            self.assertEqual(e.last_calibrated, date(2026, 10, 27))      # every row's equipment updated
        ws = load_workbook(BytesIO(exporter.build_xlsx(rec))).worksheets[0]
        self.assertLessEqual(ws.max_row, 24)
        self.assertEqual((ws["B9"].value, ws["B10"].value), ("OV-1", "OV-2"))
        self.assertEqual((ws["F9"].value, ws["G9"].value, ws["H9"].value, ws["I9"].value),
                         ("100.00", "98.80", "100.00", "99.80"))
        self.assertIn("ผ่าน", ws["J9"].value)
        self.assertIn("เกณฑ์ผ่าน ± 2", ws["B21"].value)
        self.assertIn("27/10/2026", ws["B5"].value)
        # a row for equipment with another form is refused
        bad = {**data, "t1-1-equipment": self.eq.pk}
        self.client.force_login(self.tech)
        self.assertEqual(self.client.post(reverse("record_create"), bad).status_code, 200)


class ExportAllFormsTests(Base):
    def _mk(self, code, rows, tol="0.5", tol2=None, equipment=True):
        eq = Equipment.objects.create(code=f"X-{code[-3:]}", name="เครื่องทดสอบ", brand_model="M1",
                                      serial_no="S1", department=self.eq.department, form_code=code)
        rec = CalibrationRecord.objects.create(form_code=code, equipment=eq, calibrator=self.tech,
                                               cal_date=date(2026, 10, 27), tolerance=D(tol),
                                               tolerance2=D(tol2) if tol2 else None)
        for kw in rows:
            CalibrationRow.objects.create(record=rec, **kw)
        return rec

    def test_015_both_tables_one_page_whole(self):
        rec = self._mk("F-MTN-015", [
            dict(table_no=1, std_value=D(5), std_instr_error=D("0.01"), before_reading=D(5), after_reading=D(5)),
            dict(table_no=1, std_value=D(10), std_instr_error=D("0.021"), before_reading=D(10), after_reading=D(10)),
            dict(table_no=2, std_value=D(200), std_instr_error=D(0), before_reading=D(200), before_measured=D(276),
                 after_reading=D(200), after_measured=D(276))], tol="0.1", tol2="1")
        data = exporter.build_xlsx(rec)
        ws = load_workbook(BytesIO(data)).worksheets[0]
        self.assertGreaterEqual(ws.max_row, 40)
        self.assertEqual((ws["B10"].value, ws["D10"].value, ws["G10"].value, ws["I10"].value),
                         ("5.00", "0.010", "0.01", "ผ่าน"))
        self.assertEqual((ws["B11"].value, ws["G11"].value), ("10.00", "0.021"))
        self.assertEqual((ws["B23"].value, ws["E23"].value, ws["G23"].value, ws["I23"].value, ws["K23"].value),
                         ("200.00", "200.00", "276.00", "0.00", "ผ่าน"))
        self.assertIn("ตารางน้ำหนัก", ws["B34"].value)
        self.assertIn("ตารางระยะ", ws["B34"].value)
        self.assertEqual(ws["D38"].value, "tech")
        z = zipfile.ZipFile(BytesIO(data)).read("xl/drawings/drawing1.xml").decode()
        self.assertEqual(z.count("<xdr:pic>"), 1)

    def test_026_export(self):
        rec = self._mk("F-MTN-026", [dict(std_value=D(100), std_instr_error=D("0.033"),
                                          before_reading=D("100.001"), before_p2=D(100), before_p3=D(100),
                                          before_p4=D(100), before_p5=D(100))], tol="0.05")
        ws = load_workbook(BytesIO(exporter.build_xlsx(rec))).worksheets[0]
        self.assertLessEqual(ws.max_row, 27)
        self.assertEqual((ws["D9"].value, ws["E9"].value, ws["F9"].value, ws["G9"].value, ws["J9"].value),
                         ("100.00", "0.033", "100.001", "100.00", "100.00"))
        self.assertEqual((ws["K9"].value, ws["M9"].value), ("0.034", "ผ่าน"))

    def test_030_export(self):
        rec = self._mk("F-MTN-030", [dict(before_reading=D(80), before_measured=D(77), after_reading=D(80),
                                          after_measured=D(79), remark="ปรับแล้ว")], tol="2")
        ws = load_workbook(BytesIO(exporter.build_xlsx(rec))).worksheets[0]
        self.assertLessEqual(ws.max_row, 20)
        self.assertIn("X-030", ws["A4"].value)
        self.assertIn("27/10/2026", ws["A5"].value)
        self.assertEqual((ws["B8"].value, ws["C8"].value, ws["D8"].value), ("80.00", "77.00", "ไม่ผ่าน"))
        self.assertEqual((ws["E8"].value, ws["F8"].value, ws["G8"].value, ws["H8"].value),
                         ("80.00", "79.00", "ผ่าน", "ปรับแล้ว"))
        self.assertEqual(ws["A8"].value, 1)

    def test_every_template_loads_and_keeps_logo(self):
        for code in ("F-MTN-014", "F-MTN-015", "F-MTN-016", "F-MTN-025", "F-MTN-026", "F-MTN-029", "F-MTN-030"):
            data = exporter.build_blank_xlsx(code)
            x = zipfile.ZipFile(BytesIO(data)).read("xl/drawings/drawing1.xml").decode()
            self.assertGreaterEqual(x.count("<xdr:pic>"), 1, code)
