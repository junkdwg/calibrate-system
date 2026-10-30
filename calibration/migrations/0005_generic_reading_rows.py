import decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    """std_ph -> std_value (RenameField keeps existing data), wider decimals, no hidden tolerance default."""

    dependencies = [("calibration", "0004_form_no_default")]

    operations = [
        migrations.RenameField("calibrationrow", "std_ph", "std_value"),
        migrations.AlterField(
            "calibrationrow", "std_value",
            models.DecimalField(decimal_places=4, max_digits=12, verbose_name="ค่ามาตรฐาน")),
        migrations.AlterField(
            "calibrationrow", "std_instr_error",
            models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True,
                                verbose_name="ค่าความผิดพลาดเครื่องมือมาตรฐาน")),
        migrations.AlterField(
            "calibrationrow", "before_reading",
            models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True,
                                verbose_name="ก่อนปรับ: ค่าที่อ่านได้")),
        migrations.AlterField(
            "calibrationrow", "after_reading",
            models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True,
                                verbose_name="หลังปรับ: ค่าที่อ่านได้")),
        migrations.AlterField(
            "calibrationrecord", "tolerance",
            models.DecimalField(
                decimal_places=4, max_digits=10, verbose_name="เกณฑ์ผ่าน ±",
                validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.0001"))])),
    ]
