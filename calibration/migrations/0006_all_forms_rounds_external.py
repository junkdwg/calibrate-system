import decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

from calibration.formdefs import FORM_CHOICES

D4 = dict(max_digits=12, decimal_places=4, null=True, blank=True)


def days_to_months(apps, schema_editor):
    Equipment = apps.get_model("calibration", "Equipment")
    for e in Equipment.objects.all():
        e.interval_months = max(1, round((e.interval_days or 365) / 30.4375))   # 365 -> 12, 180 -> 6
        e.save(update_fields=["interval_months"])


def fill_record_form_code(apps, schema_editor):
    Record = apps.get_model("calibration", "CalibrationRecord")
    for r in Record.objects.select_related("equipment"):
        r.form_code = r.equipment.form_code
        r.save(update_fields=["form_code"])


class Migration(migrations.Migration):
    """Rounds in months, external calibration, 026/029/030/015 row fields. Data is preserved."""

    dependencies = [("calibration", "0005_generic_reading_rows")]

    operations = [
        # --- equipment: interval in months ---
        migrations.AddField("equipment", "interval_months", models.PositiveSmallIntegerField(
            default=12, help_text="เช่น 2, 3, 6, 12 (= 1 ปี), 24 (= 2 ปี)",
            validators=[django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(120)],
            verbose_name="รอบสอบเทียบ (เดือน)")),
        migrations.RunPython(days_to_months, migrations.RunPython.noop),
        migrations.RemoveField("equipment", "interval_days"),
        migrations.AlterField("equipment", "form_code", models.CharField(
            choices=FORM_CHOICES, max_length=20, verbose_name="แบบฟอร์ม")),

        # --- record: form code, batch (no equipment), external, 2nd tolerance ---
        migrations.AddField("calibrationrecord", "form_code", models.CharField(
            choices=FORM_CHOICES, default="F-MTN-025", max_length=20), preserve_default=False),
        migrations.RunPython(fill_record_form_code, migrations.RunPython.noop),
        migrations.AlterField("calibrationrecord", "equipment", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            to="calibration.equipment", verbose_name="เครื่องมือ")),
        migrations.AlterField("calibrationrecord", "tolerance", models.DecimalField(
            blank=True, decimal_places=4, max_digits=10, null=True, verbose_name="เกณฑ์ผ่าน ±",
            validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.0001"))])),
        migrations.AddField("calibrationrecord", "tolerance2", models.DecimalField(
            blank=True, decimal_places=4, max_digits=10, null=True, verbose_name="เกณฑ์ผ่าน ± (ตารางที่ 2)",
            validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.0001"))])),
        migrations.AddField("calibrationrecord", "lab_name", models.CharField(
            blank=True, max_length=150, verbose_name="ห้องปฏิบัติการ/ผู้สอบเทียบภายนอก")),
        migrations.AddField("calibrationrecord", "cert_no", models.CharField(
            blank=True, max_length=100, verbose_name="เลขที่ใบรับรอง")),
        migrations.AddField("calibrationrecord", "ext_result", models.CharField(
            blank=True, choices=[("pass", "ผ่าน"), ("fail", "ไม่ผ่าน")], max_length=10,
            verbose_name="ผลการสอบเทียบภายนอก")),

        # --- rows ---
        migrations.AddField("calibrationrow", "table_no", models.PositiveSmallIntegerField(default=1)),
        migrations.AddField("calibrationrow", "equipment", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
            to="calibration.equipment", verbose_name="เครื่องมือ")),
        migrations.AlterField("calibrationrow", "std_value", models.DecimalField(
            blank=True, decimal_places=4, max_digits=12, null=True, verbose_name="ค่ามาตรฐาน")),
        *[migrations.AddField("calibrationrow", f"{ph}_p{i}", models.DecimalField(
            verbose_name=f"{'ก่อนปรับ' if ph == 'before' else 'หลังปรับ'} จุดที่ {i}", **D4))
          for ph in ("before", "after") for i in (2, 3, 4, 5)],
        migrations.AddField("calibrationrow", "before_measured", models.DecimalField(
            verbose_name="ก่อนปรับ: ค่าที่วัดได้", **D4)),
        migrations.AddField("calibrationrow", "after_measured", models.DecimalField(
            verbose_name="หลังปรับ: ค่าที่วัดได้", **D4)),
        migrations.AddField("calibrationrow", "remark", models.CharField(
            blank=True, max_length=200, verbose_name="หมายเหตุ")),
        migrations.AlterField("calibrationrow", "before_reading", models.DecimalField(
            verbose_name="ก่อนปรับ: ค่าที่อ่านได้ (จุดที่ 1)", **D4)),
        migrations.AlterField("calibrationrow", "after_reading", models.DecimalField(
            verbose_name="หลังปรับ: ค่าที่อ่านได้ (จุดที่ 1)", **D4)),
        migrations.AlterModelOptions("calibrationrow", options={"ordering": ["table_no", "id"]}),
    ]
