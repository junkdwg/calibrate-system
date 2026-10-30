from django import forms
from django.forms import inlineformset_factory

from .models import CalibrationRecord, CalibrationRow, Equipment

NUMERIC = {"std_value", "std_instr_error", "before_reading", "before_p2", "before_p3", "before_p4",
           "before_p5", "before_measured", "after_reading", "after_p2", "after_p3", "after_p4",
           "after_p5", "after_measured"}


def tolerance_label(formdef, idx):
    t = formdef.tables[idx]
    unit = f" ({t.unit})" if t.unit else " (หน่วยเดียวกับค่าที่กรอก)"
    where = f" — {t.title}" if len(formdef.tables) > 1 else ""
    return f"เกณฑ์ผ่าน ±{unit}{where}"


class RecordForm(forms.ModelForm):
    """Header of a calibration sheet. Equipment / form type are fixed by the view."""

    class Meta:
        model = CalibrationRecord
        fields = ["cal_date", "tolerance", "tolerance2", "lab_name", "cert_no", "ext_result", "note"]
        widgets = {
            "cal_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2}),
            "tolerance": forms.NumberInput(attrs={"step": "any"}),
            "tolerance2": forms.NumberInput(attrs={"step": "any"}),
        }

    def __init__(self, *args, formdef, **kwargs):
        super().__init__(*args, **kwargs)
        if formdef.external:
            for name in ("tolerance", "tolerance2"):
                del self.fields[name]
            for name in ("lab_name", "cert_no", "ext_result"):
                self.fields[name].required = True
            return
        for name in ("lab_name", "cert_no", "ext_result"):
            del self.fields[name]
        self.fields["tolerance"].required = True
        self.fields["tolerance"].label = tolerance_label(formdef, 0)
        if len(formdef.tables) > 1:
            self.fields["tolerance2"].required = True
            self.fields["tolerance2"].label = tolerance_label(formdef, 1)
        else:
            del self.fields["tolerance2"]
        t = formdef.tables[0]
        if not self.instance.pk and t.default_tolerance:
            self.fields["tolerance"].initial = t.default_tolerance
            self.fields["tolerance"].help_text = "ค่าเริ่มต้น — ยืนยันกับ QA ก่อนใช้จริง"


def make_formset(formdef, idx, extra):
    t = formdef.tables[idx]

    class RowForm(forms.ModelForm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            if "equipment" in self.fields:
                self.fields["equipment"].queryset = Equipment.objects.filter(
                    active=True, form_code=formdef.code).select_related("department")

        def clean(self):
            data = super().clean()
            if "std_value" in t.fields and data.get("std_value") is None and not self.errors:
                self.add_error("std_value", "กรอกค่ามาตรฐาน")
            if "equipment" in t.fields and data.get("equipment") is None and not self.errors:
                self.add_error("equipment", "เลือกเครื่องมือ")
            if t.value_min is not None:
                for name in ("std_value", "before_reading", "after_reading"):
                    v = data.get(name)
                    if v is not None and not (t.value_min <= v <= t.value_max):
                        self.add_error(name, f"ต้องอยู่ระหว่าง {t.value_min} ถึง {t.value_max}")
            return data

    widgets = {f: forms.NumberInput(attrs={"step": "any"}) for f in t.fields if f in NUMERIC}
    widgets["remark"] = forms.TextInput()
    return inlineformset_factory(
        CalibrationRecord, CalibrationRow, form=RowForm, fields=list(t.fields),
        labels={f: t.labels.get(f, f) for f in t.fields},
        extra=extra, max_num=t.max_rows, validate_max=True,
        min_num=1 if idx == 0 else 0, validate_min=idx == 0, can_delete=True,
        widgets={k: v for k, v in widgets.items() if k in t.fields},
    )
