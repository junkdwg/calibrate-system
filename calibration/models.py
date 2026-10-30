from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .formdefs import FORM_CHOICES, FORMS
from .utils import add_months

ZERO = Decimal("0")
POINT_FIELDS = {"before": ["before_reading", "before_p2", "before_p3", "before_p4", "before_p5"],
                "after": ["after_reading", "after_p2", "after_p3", "after_p4", "after_p5"]}


class Department(models.Model):
    code = models.CharField("รหัสแผนก", max_length=20, unique=True)
    name = models.CharField("ชื่อแผนก", max_length=100)

    class Meta:
        ordering = ["code"]
        verbose_name = "แผนก"
        verbose_name_plural = "แผนก"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Equipment(models.Model):
    code = models.CharField("รหัสเครื่องมือ", max_length=50, unique=True)
    name = models.CharField("ชื่อเครื่องมือ", max_length=150)
    brand_model = models.CharField("ยี่ห้อ/รุ่น", max_length=100, blank=True)
    serial_no = models.CharField("S/N", max_length=100, blank=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, verbose_name="หน่วยงาน")
    form_code = models.CharField("แบบฟอร์ม", max_length=20, choices=FORM_CHOICES)
    interval_months = models.PositiveSmallIntegerField(
        "รอบสอบเทียบ (เดือน)", default=12,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        help_text="เช่น 2, 3, 6, 12 (= 1 ปี), 24 (= 2 ปี)")
    last_calibrated = models.DateField("สอบเทียบล่าสุด", null=True, blank=True)
    active = models.BooleanField("ใช้งานอยู่", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "เครื่องมือ"
        verbose_name_plural = "เครื่องมือ"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def next_due(self):
        """Last calibration date + N months, same day of month (27/10 + 2 months = 27/12)."""
        if not self.last_calibrated:
            return None
        return add_months(self.last_calibrated, self.interval_months)

    @property
    def due_status(self):
        """'never' | 'overdue' | 'soon' | 'ok'"""
        from datetime import timedelta
        if not self.next_due:
            return "never"
        today = timezone.localdate()
        if self.next_due < today:
            return "overdue"
        if self.next_due <= today + timedelta(days=settings.DUE_SOON_DAYS):
            return "soon"
        return "ok"


class CalibrationRecord(models.Model):
    DRAFT, SUBMITTED, REVIEWED, APPROVED = "draft", "submitted", "reviewed", "approved"
    STATUS_CHOICES = [
        (DRAFT, "ร่าง"),
        (SUBMITTED, "รอทบทวน"),
        (REVIEWED, "รออนุมัติ"),
        (APPROVED, "อนุมัติแล้ว"),
    ]
    EXT_RESULTS = [("pass", "ผ่าน"), ("fail", "ไม่ผ่าน")]

    form_code = models.CharField(max_length=20, choices=FORM_CHOICES)
    # null only for "batch" forms (F-MTN-029) where every row names its own equipment
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True,
                                  verbose_name="เครื่องมือ")
    cal_date = models.DateField("วันที่สอบเทียบ", default=timezone.localdate)
    tolerance = models.DecimalField("เกณฑ์ผ่าน ±", max_digits=10, decimal_places=4, null=True,
                                    blank=True, validators=[MinValueValidator(Decimal("0.0001"))])
    tolerance2 = models.DecimalField("เกณฑ์ผ่าน ± (ตารางที่ 2)", max_digits=10, decimal_places=4,
                                     null=True, blank=True,
                                     validators=[MinValueValidator(Decimal("0.0001"))])
    # external calibration (sent to an outside lab)
    lab_name = models.CharField("ห้องปฏิบัติการ/ผู้สอบเทียบภายนอก", max_length=150, blank=True)
    cert_no = models.CharField("เลขที่ใบรับรอง", max_length=100, blank=True)
    ext_result = models.CharField("ผลการสอบเทียบภายนอก", max_length=10, choices=EXT_RESULTS, blank=True)
    note = models.TextField("หมายเหตุ", blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)

    calibrator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="+", verbose_name="ผู้สอบเทียบ")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="+", verbose_name="ผู้ทบทวน")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="+", verbose_name="ผู้อนุมัติ")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cal_date", "-id"]
        verbose_name = "ใบรายงานการสอบเทียบ"
        verbose_name_plural = "ใบรายงานการสอบเทียบ"

    def __str__(self):
        return f"{self.title_text} @ {self.cal_date}"

    @property
    def form(self):
        return FORMS[self.form_code]

    @property
    def title_text(self):
        if self.equipment_id:
            return self.equipment.code
        n = self.rows.count() if self.pk else 0
        return f"{self.form_code} (หลายเครื่อง {n})"

    def tolerance_for(self, table_no):
        return self.tolerance if table_no == 1 else self.tolerance2

    def calibrated_equipment(self):
        """Equipment that this approved record counts as calibrated."""
        if self.equipment_id:
            return [self.equipment]
        ids = {r.equipment_id for r in self.rows.all() if r.equipment_id}
        return list(Equipment.objects.filter(pk__in=ids))

    @property
    def is_locked(self):
        return self.status != self.DRAFT

    @property
    def overall_pass(self):
        """True/False/None. After-adjust value decides if present, else before-adjust."""
        if self.form.external:
            return {"pass": True, "fail": False}.get(self.ext_result)
        results = []
        for r in self.rows.all():
            res = r.after_pass if r.after_error is not None else r.before_pass
            if res is not None:
                results.append(res)
        return all(results) if results else None


class CalibrationRow(models.Model):
    record = models.ForeignKey(CalibrationRecord, on_delete=models.CASCADE, related_name="rows")
    table_no = models.PositiveSmallIntegerField(default=1)          # F-MTN-015 has two tables
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="+", verbose_name="เครื่องมือ")   # batch forms only
    std_value = models.DecimalField("ค่ามาตรฐาน", max_digits=12, decimal_places=4, null=True, blank=True)
    std_instr_error = models.DecimalField("ค่าความผิดพลาดเครื่องมือมาตรฐาน", max_digits=12,
                                          decimal_places=4, null=True, blank=True)
    before_reading = models.DecimalField("ก่อนปรับ: ค่าที่อ่านได้ (จุดที่ 1)", max_digits=12,
                                         decimal_places=4, null=True, blank=True)
    before_p2 = models.DecimalField("ก่อนปรับ จุดที่ 2", max_digits=12, decimal_places=4, null=True, blank=True)
    before_p3 = models.DecimalField("ก่อนปรับ จุดที่ 3", max_digits=12, decimal_places=4, null=True, blank=True)
    before_p4 = models.DecimalField("ก่อนปรับ จุดที่ 4", max_digits=12, decimal_places=4, null=True, blank=True)
    before_p5 = models.DecimalField("ก่อนปรับ จุดที่ 5", max_digits=12, decimal_places=4, null=True, blank=True)
    before_measured = models.DecimalField("ก่อนปรับ: ค่าที่วัดได้", max_digits=12, decimal_places=4,
                                          null=True, blank=True)
    after_reading = models.DecimalField("หลังปรับ: ค่าที่อ่านได้ (จุดที่ 1)", max_digits=12,
                                        decimal_places=4, null=True, blank=True)
    after_p2 = models.DecimalField("หลังปรับ จุดที่ 2", max_digits=12, decimal_places=4, null=True, blank=True)
    after_p3 = models.DecimalField("หลังปรับ จุดที่ 3", max_digits=12, decimal_places=4, null=True, blank=True)
    after_p4 = models.DecimalField("หลังปรับ จุดที่ 4", max_digits=12, decimal_places=4, null=True, blank=True)
    after_p5 = models.DecimalField("หลังปรับ จุดที่ 5", max_digits=12, decimal_places=4, null=True, blank=True)
    after_measured = models.DecimalField("หลังปรับ: ค่าที่วัดได้", max_digits=12, decimal_places=4,
                                         null=True, blank=True)
    remark = models.CharField("หมายเหตุ", max_length=200, blank=True)

    class Meta:
        ordering = ["table_no", "id"]

    @property
    def table(self):
        return self.record.form.tables[self.table_no - 1]

    def deviation(self, phase):
        """How far the unit under test is from the reference, by the table's rule."""
        t, std = self.table, self.std_value
        g = lambda n: getattr(self, n)  # noqa: E731
        if t.kind == "nominal":                # reading - standard
            r = g(f"{phase}_reading")
            return None if r is None or std is None else r - std
        if t.kind == "offset":                 # measured - (standard + fixed start offset)
            m = g(f"{phase}_measured")
            return None if m is None or std is None else m - (std + t.offset)
        if t.kind == "points":                 # worst of up to 5 weighing positions
            pts = [g(n) for n in POINT_FIELDS[phase] if g(n) is not None]
            return None if not pts or std is None else max((p - std for p in pts), key=abs)
        if t.kind == "compare":                # display - measured by the reference
            r, m = g(f"{phase}_reading"), g(f"{phase}_measured")
            return None if r is None or m is None else r - m
        raise ValueError(t.kind)

    def error(self, phase):
        """Reported error = standard's own error + deviation (company rule)."""
        dev = self.deviation(phase)
        if dev is None:
            return None
        add = (self.std_instr_error or ZERO) if self.table.add_std_error else ZERO
        return dev + add

    def _pass(self, err):
        tol = self.record.tolerance_for(self.table_no)
        return None if err is None or tol is None else abs(err) <= tol

    @property
    def before_error(self):
        return self.error("before")

    @property
    def after_error(self):
        return self.error("after")

    @property
    def before_pass(self):
        return self._pass(self.before_error)

    @property
    def after_pass(self):
        return self._pass(self.after_error)

    @property
    def final_pass(self):
        return self.after_pass if self.after_error is not None else self.before_pass


class AuditLog(models.Model):
    at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                             related_name="+")
    action = models.CharField(max_length=30)
    record = models.ForeignKey(CalibrationRecord, on_delete=models.SET_NULL, null=True, blank=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "Audit log"
        verbose_name_plural = "Audit log"

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.user} {self.action}"
