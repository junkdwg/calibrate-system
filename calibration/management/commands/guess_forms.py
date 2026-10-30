"""Suggest the right form (F-MTN-0xx) for equipment from its name/model.

Why: before v2 every equipment was saved with form F-MTN-025 by default.
Dry-run by default (changes nothing). Use --apply to save. Only touches equipment
currently set to F-MTN-025 whose name does NOT look like a pH meter.
"""
import re

from django.core.management.base import BaseCommand

from calibration.models import Equipment

# first match wins; unmatched items are left alone and listed for manual choice
RULES = [
    ("F-MTN-025", r"\bph\d*\b|พีเอช"),
    ("F-MTN-015", r"เทนไซด์|เทนไซล์|tensile|tensite"),
    ("F-MTN-016", r"เครื่องตัดยาง"),
    ("F-MTN-029", r"เตาอบ|ถาดน้ำ|ถาดซิลิโคน|ถาดซิลิโคลน|ถัง\s*c|ถังคอมปาวด์"),
    ("F-MTN-030", r"ตู้\s*อบ|ตู้แช่|water\s*bath|หม้อน้ำเย็น"),
    ("F-MTN-014", r"weight\s*scale|bench\s*scale|hopper\s*scale|เครื่องชั่ง|scale"),
]


def propose(eq):
    text = f"{eq.name} {eq.brand_model}".lower()
    for code, pattern in RULES:
        if re.search(pattern, text, re.I):
            return code
    return None


class Command(BaseCommand):
    help = "Suggest/fix equipment form codes (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="save the suggestions")

    def handle(self, *args, **opts):
        changes, unknown = [], []
        for eq in Equipment.objects.filter(form_code="F-MTN-025").order_by("code"):
            new = propose(eq)
            if new is None:
                unknown.append(eq)
            elif new != "F-MTN-025":
                changes.append((eq, new))

        for eq, new in changes:
            self.stdout.write(f"{eq.code:<14} {eq.name[:28]:<28} F-MTN-025 -> {new}")
        self.stdout.write(f"\nจะเปลี่ยน {len(changes)} รายการ, ไม่แน่ใจ {len(unknown)} รายการ (คงเป็น F-MTN-025 ไว้ ให้ตั้งเองใน Admin)")
        for eq in unknown[:30]:
            self.stdout.write(f"  ? {eq.code} {eq.name} {eq.brand_model}")

        if opts["apply"]:
            for eq, new in changes:
                Equipment.objects.filter(pk=eq.pk).update(form_code=new)
            self.stdout.write(self.style.SUCCESS(f"บันทึกแล้ว {len(changes)} รายการ"))
        else:
            self.stdout.write("(dry-run: ยังไม่ได้บันทึก — เพิ่ม --apply เพื่อบันทึก)")
