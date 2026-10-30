import subprocess

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dashboard as dash
from . import exporter
from .display import table_blocks
from .formdefs import FORMS, IMPLEMENTED_CODES
from .forms import RecordForm, make_formset
from .models import AuditLog, CalibrationRecord, CalibrationRow, Department, Equipment
from .permissions import APPROVER, REVIEWER, TECHNICIAN, available_actions, can_edit, has_role


def audit(request, action, record=None, detail=""):
    AuditLog.objects.create(user=request.user, action=action, record=record, detail=detail[:300])


@login_required
def dashboard(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
    except ValueError:
        year = today.year
    if year not in dash.available_years():
        year = today.year
    dept = request.GET.get("dept", "")
    items = dash.build_plan(year, dept)
    all_pending = CalibrationRecord.objects
    return render(request, "calibration/dashboard.html", {
        "year": year, "years": dash.available_years(), "dept": dept,
        "departments": Department.objects.all(),
        "items": items, "s": dash.summarize(items),
        "chart": dash.monthly_chart(items), "depts": dash.by_department(items),
        "alerts": [i for i in items if i["state"] in ("overdue", "never", "soon")][:8],
        "wait_review": all_pending.filter(status=CalibrationRecord.SUBMITTED).count(),
        "wait_approve": all_pending.filter(status=CalibrationRecord.REVIEWED).count(),
        "is_reviewer": has_role(request.user, REVIEWER),
        "is_approver": has_role(request.user, APPROVER),
        "can_create": has_role(request.user, TECHNICIAN),
        "today": today,
    })


@login_required
def record_list(request):
    status = request.GET.get("status", "")
    qs = CalibrationRecord.objects.select_related("equipment", "calibrator")
    if status:
        qs = qs.filter(status=status)
    return render(request, "calibration/record_list.html", {
        "records": qs[:200], "status": status,
        "statuses": CalibrationRecord.STATUS_CHOICES,
    })


def _save_formsets(record, formsets):
    """Save each table's rows; remember which table (1/2) a row belongs to."""
    for no, fs in enumerate(formsets, start=1):
        fs.instance = record
        for obj in fs.save(commit=False):
            obj.record, obj.table_no = record, no
            obj.save()
        for obj in fs.deleted_objects:
            obj.delete()


def _build_formsets(formdef, data, instance=None, initial=None):
    sets = []
    for idx, t in enumerate(formdef.tables):
        extra = t.max_rows if instance is None else max(
            0, t.max_rows - instance.rows.filter(table_no=idx + 1).count())
        FormSet = make_formset(formdef, idx, extra)
        kwargs = {"prefix": f"t{idx + 1}", "queryset": CalibrationRow.objects.filter(table_no=idx + 1)}
        if instance is not None:
            kwargs["instance"] = instance
        if initial and idx == 0 and data is None:
            kwargs["initial"] = initial
        fs = FormSet(data, **kwargs)
        fs.title, fs.formula, fs.max_rows = t.title, t.formula, t.max_rows
        fs.column_labels = [t.labels.get(f, f) for f in t.fields]
        sets.append(fs)
    return sets


@login_required
def record_create(request):
    if not has_role(request.user, TECHNICIAN):
        messages.error(request, "ต้องเป็นสิทธิ์ช่างสอบเทียบ (Technician)")
        return redirect("record_list")
    params = request.POST if request.method == "POST" else request.GET
    code, eq_id = params.get("form"), params.get("equipment")
    eq = None
    if code:                                  # batch form (F-MTN-029): rows name their own equipment
        formdef = FORMS.get(code)
        if not formdef or not formdef.implemented or not formdef.batch:
            raise Http404
    elif eq_id:
        eq = get_object_or_404(Equipment, pk=eq_id, active=True, form_code__in=IMPLEMENTED_CODES)
        formdef = FORMS[eq.form_code]
        if formdef.batch:
            return redirect(f"{request.path}?form={formdef.code}&equipment={eq.pk}")
    else:                                     # step 1: pick the equipment; the form type follows from it
        return render(request, "calibration/record_pick.html", {
            "equipment": Equipment.objects.filter(active=True, form_code__in=IMPLEMENTED_CODES)
                                          .exclude(form_code__in=[c for c, f in FORMS.items() if f.batch])
                                          .select_related("department").order_by("form_code", "code"),
            "batch_forms": [f for f in FORMS.values() if f.batch and f.implemented]})
    form = RecordForm(request.POST or None, formdef=formdef)
    prefill = [{"equipment": eq_id}] if code and eq_id else None
    formsets = _build_formsets(formdef, request.POST or None, initial=prefill)
    if request.method == "POST" and form.is_valid() and all(fs.is_valid() for fs in formsets):
        with transaction.atomic():
            record = form.save(commit=False)
            record.form_code, record.calibrator = formdef.code, request.user
            record.equipment = None if formdef.batch else eq
            record.save()
            _save_formsets(record, formsets)
            audit(request, "create", record)
        messages.success(request, "บันทึกร่างแล้ว")
        return redirect("record_detail", pk=record.pk)
    return render(request, "calibration/record_form.html", {
        "form": form, "formsets": formsets, "equipment": eq, "formdef": formdef,
        "hidden": {"form": formdef.code} if formdef.batch else {"equipment": eq.pk},
        "title": f"สร้างใบสอบเทียบ {formdef.code} {formdef.title}"})


@login_required
def record_edit(request, pk):
    record = get_object_or_404(CalibrationRecord.objects.select_related("equipment__department"), pk=pk)
    if not can_edit(request.user, record):
        messages.error(request, "ไม่สามารถแก้ไขได้ (ล็อกแล้ว หรือไม่ใช่ผู้สอบเทียบ)")
        return redirect("record_detail", pk=pk)
    formdef = record.form
    form = RecordForm(request.POST or None, instance=record, formdef=formdef)
    formsets = _build_formsets(formdef, request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid() and all(fs.is_valid() for fs in formsets):
        with transaction.atomic():
            form.save()
            _save_formsets(record, formsets)
            audit(request, "edit", record)
        messages.success(request, "บันทึกแล้ว")
        return redirect("record_detail", pk=pk)
    return render(request, "calibration/record_form.html", {
        "form": form, "formsets": formsets, "equipment": record.equipment, "formdef": formdef,
        "hidden": {}, "title": f"แก้ไขใบสอบเทียบ #{record.pk}"})


@login_required
def record_detail(request, pk):
    record = get_object_or_404(
        CalibrationRecord.objects.select_related("equipment__department", "calibrator",
                                                  "reviewer", "approver").prefetch_related("rows__equipment"),
        pk=pk)
    return render(request, "calibration/record_detail.html", {
        "record": record, "formdef": record.form,
        "blocks": table_blocks(record) if not record.form.external else [],
        "actions": available_actions(request.user, record),
        "can_edit": can_edit(request.user, record),
        "can_download": not record.form.external,
        "logs": AuditLog.objects.filter(record=record).select_related("user")[:20],
    })


@login_required
@require_POST
def record_action(request, pk, action):
    with transaction.atomic():
        record = get_object_or_404(CalibrationRecord.objects.select_for_update(), pk=pk)
        if action not in available_actions(request.user, record):
            messages.error(request, "ไม่มีสิทธิ์ทำรายการนี้ หรือสถานะไม่ถูกต้อง")
            return redirect("record_detail", pk=pk)

        now = timezone.now()
        if action == "submit":
            if record.overall_pass is None:
                messages.error(request, "ต้องมีค่าที่วัดได้อย่างน้อย 1 จุดก่อนส่ง")
                return redirect("record_detail", pk=pk)
            record.status, record.submitted_at = record.SUBMITTED, now
        elif action == "review":
            record.status, record.reviewer, record.reviewed_at = record.REVIEWED, request.user, now
        elif action == "approve":
            record.status, record.approver, record.approved_at = record.APPROVED, request.user, now
            for eq in record.calibrated_equipment():
                if not eq.last_calibrated or record.cal_date >= eq.last_calibrated:
                    eq.last_calibrated = record.cal_date
                    eq.save(update_fields=["last_calibrated"])
        elif action == "reject":
            record.status = record.DRAFT
            record.reviewer = record.approver = None
            record.submitted_at = record.reviewed_at = None
        record.save()
        audit(request, action, record, request.POST.get("reason", ""))
    messages.success(request, "ดำเนินการแล้ว")
    return redirect("record_detail", pk=pk)


@login_required
def record_download(request, pk, fmt):
    record = get_object_or_404(
        CalibrationRecord.objects.select_related("equipment__department", "calibrator",
                                                  "reviewer", "approver").prefetch_related("rows__equipment"),
        pk=pk)
    if record.form.external:
        messages.error(request, "การสอบเทียบภายนอกไม่มีแบบฟอร์มให้พิมพ์ (ใช้ใบรับรองจากห้องปฏิบัติการ)")
        return redirect("record_detail", pk=pk)
    if fmt == "xlsx":
        data = exporter.build_xlsx(record)
        ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "pdf":
        try:
            data = exporter.build_pdf(record)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            messages.error(request, "สร้าง PDF ไม่สำเร็จ (ตรวจสอบ LibreOffice บนเซิร์ฟเวอร์)")
            return redirect("record_detail", pk=pk)
        ctype = "application/pdf"
    else:
        return redirect("record_detail", pk=pk)
    audit(request, f"download_{fmt}", record)
    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{exporter.safe_filename(record, fmt)}"'
    resp["Cache-Control"] = "no-store"
    return resp


def healthz(request):
    """Liveness/readiness for Docker healthcheck: no login, no data, just 'app + DB reachable'."""
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        return HttpResponse("db error", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
